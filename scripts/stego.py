#!/usr/bin/env python3
"""Token-level steganography reference demo (the thing the warden defends against).

Per-token Huffman coding over GPT-2's next-token distribution:
  embed   secret bytes -> plausible cover text (bits ride in token choices)
  extract cover text   -> secret bytes (replay the model, read the choices back)

Bit-exactly reversible, so it proves the two practical landmines are handled:
determinism (CPU + float32 + fixed seed) and tokenization (the receiver
re-tokenizes the string and must recover the same ids). This is the DETECTABLE
family (it perturbs the distribution); it exists here to demonstrate a channel
the warden can then destroy. See docs/llm-token-steganography.md.

Heavy deps (torch + transformers): pip install -r requirements-stego.txt

Usage:
    python scripts/stego.py embed   --secret "meet at dawn"
    python scripts/stego.py extract --text "<cover text>"
"""

import argparse
import heapq
import sys

TOP_K = 256
TEMPERATURE = 1.0
CONTEXT = "The weather report for tomorrow says"
MODEL_NAME = "gpt2"


class _Leaf:
    __slots__ = ("token_id",)

    def __init__(self, token_id: int):
        self.token_id = token_id


class _Internal:
    __slots__ = ("left", "right")

    def __init__(self, left: object, right: object):
        self.left = left
        self.right = right


def _build_huffman(candidates: list[tuple[int, float]]) -> object:
    if len(candidates) == 1:
        return _Leaf(candidates[0][0])
    heap: list[tuple[float, int, object]] = []
    counter = 0
    for token_id, weight in candidates:
        heapq.heappush(heap, (weight, counter, _Leaf(token_id)))
        counter += 1
    while len(heap) > 1:
        w1, _, n1 = heapq.heappop(heap)
        w2, _, n2 = heapq.heappop(heap)
        heapq.heappush(heap, (w1 + w2, counter, _Internal(n1, n2)))
        counter += 1
    return heap[0][2]


def _code_table(root: object) -> dict[int, str]:
    table: dict[int, str] = {}
    stack: list[tuple[object, str]] = [(root, "")]
    while stack:
        node, prefix = stack.pop()
        if isinstance(node, _Leaf):
            table[node.token_id] = prefix or "0"
        elif isinstance(node, _Internal):
            stack.append((node.left, prefix + "0"))
            stack.append((node.right, prefix + "1"))
    return table


def _load():  # type: ignore[no-untyped-def]  # returns (tokenizer, model)
    import torch
    from transformers import GPT2LMHeadModel, GPT2TokenizerFast

    torch.manual_seed(0)
    tok = GPT2TokenizerFast.from_pretrained(MODEL_NAME)
    model = GPT2LMHeadModel.from_pretrained(MODEL_NAME).to("cpu").eval()
    torch.set_grad_enabled(False)
    return tok, model


def _candidates(model: object, input_ids: object) -> list[tuple[int, float]]:
    import torch

    logits = model(input_ids).logits[0, -1, :].float() / TEMPERATURE  # type: ignore[operator]
    probs = torch.softmax(logits, dim=-1)
    topk = torch.topk(probs, TOP_K)
    pairs = list(zip(topk.indices.tolist(), topk.values.tolist()))
    return sorted(pairs, key=lambda p: (-p[1], p[0]))


def _to_bits(data: bytes) -> str:
    body = "".join(f"{b:08b}" for b in data)
    return f"{len(body):032b}" + body


def _from_bits(bits: str) -> bytes:
    length = int(bits[:32], 2)
    body = bits[32 : 32 + length]
    return bytes(int(body[i : i + 8], 2) for i in range(0, len(body), 8))


def embed(secret: bytes) -> str:
    import torch

    tok, model = _load()
    bits = _to_bits(secret)
    ctx = tok.encode(CONTEXT, return_tensors="pt")
    out: list[int] = []
    i = 0
    while i < len(bits):
        node = _build_huffman(_candidates(model, ctx))
        while isinstance(node, _Internal):
            bit = bits[i] if i < len(bits) else "0"
            i += 1
            node = node.left if bit == "0" else node.right
        out.append(node.token_id)  # type: ignore[attr-defined]
        ctx = torch.cat([ctx, torch.tensor([[node.token_id]])], dim=1)  # type: ignore[attr-defined]
    return tok.decode(out)


def extract(covertext: str) -> bytes:
    import torch

    tok, model = _load()
    ctx = tok.encode(CONTEXT, return_tensors="pt")
    bits = ""
    header_len: int | None = None
    for token_id in tok.encode(covertext):
        table = _code_table(_build_huffman(_candidates(model, ctx)))
        if token_id not in table:
            raise RuntimeError(
                f"desync: token {token_id} not in codebook. The text was altered "
                "(e.g. scrubbed) or the model/context/tokenization differs"
            )
        bits += table[token_id]
        ctx = torch.cat([ctx, torch.tensor([[token_id]])], dim=1)
        if header_len is None and len(bits) >= 32:
            header_len = int(bits[:32], 2)
        if header_len is not None and len(bits) >= 32 + header_len:
            break
    return _from_bits(bits)


def main() -> int:
    ap = argparse.ArgumentParser(description="Token-level steganography demo (GPT-2).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pe = sub.add_parser("embed", help="secret -> cover text")
    pe.add_argument("--secret", help="Secret string (else read stdin).")
    px = sub.add_parser("extract", help="cover text -> secret")
    px.add_argument("--text", help="Cover text (else read stdin).")
    args = ap.parse_args()

    if args.cmd == "embed":
        secret = args.secret if args.secret is not None else sys.stdin.read()
        print(embed(secret.encode("utf-8")))
    else:
        text = args.text if args.text is not None else sys.stdin.read()
        try:
            print(extract(text).decode("utf-8", "replace"))
        except RuntimeError as exc:
            print(f"[no recoverable message] {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
