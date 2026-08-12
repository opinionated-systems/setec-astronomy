#!/usr/bin/env python3
"""Active-warden text scrubber.

Provably-secure token-level steganography (Meteor, Discop, minimum-entropy
coupling) is statistically indistinguishable from ordinary model output, so it
cannot be DETECTED. The active-warden strategy skips detection and rewrites all
traffic, which DESTROYS any hidden channel. Token-level stego encodes its
payload in the exact sequence of token choices; paraphrasing re-samples that
surface form, so the receiver's re-tokenize-and-replay decode desyncs while the
meaning of the text is preserved. (The same rewrite defeats LLM watermarks.)

This measures token-level divergence against the original as a proxy for channel
destruction. It cannot prove zero residual capacity (a resync/ECC-hardened
scheme, or very low-entropy text, can retain some), so it reports a measured
bound rather than claiming detection.

Usage:
    echo "text" | python scripts/warden.py            # reads stdin
    python scripts/warden.py --text "..." --strength 0.7 --json
Config: SETEC_BASE_URL / _API_KEY / _MODEL  (see .env.example)
"""

import argparse
import json
import re
import sys

from llm import chat
from unicode_scrub import sanitize_unicode, to_ascii

PARAPHRASE_SYSTEM = (
    "You are a faithful paraphraser. Rewrite the user's text so it preserves the "
    "exact meaning, facts, names, numbers, and tone, but uses different wording and "
    "sentence structure. Do not add information, do not omit information, do not "
    "comment or explain. Output ONLY the rewritten text."
)


def _tokenize(text: str) -> list[str]:
    """Yardstick tokenizer for the divergence metric.

    Uses tiktoken (faithful BPE) if installed; otherwise a dependency-free
    word/punctuation split. Either way it serves only to quantify how much the
    token sequence changed, and assumes nothing about the adversary's tokenizer.
    """
    try:
        import tiktoken  # optional; pip install tiktoken for faithful subword counts

        enc = tiktoken.get_encoding("cl100k_base")
        return [str(t) for t in enc.encode(text)]
    except Exception:
        return re.findall(r"\w+|[^\w\s]", text)


def _divergence(original: str, scrubbed: str) -> dict[str, object]:
    import difflib

    a, b = _tokenize(original), _tokenize(scrubbed)
    if not a:
        return {
            "token_divergence": 0.0,
            "first_divergence_index": None,
            "retained_tokens": 0,
            "original_token_count": 0,
        }
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    retained = sum(block.size for block in matcher.get_matching_blocks())
    first_div: int | None = None
    for tag, i1, _i2, _j1, _j2 in matcher.get_opcodes():
        if tag != "equal":
            first_div = i1
            break
    return {
        "token_divergence": round(1.0 - retained / len(a), 4),
        "first_divergence_index": first_div,
        "retained_tokens": retained,
        "original_token_count": len(a),
    }


def scrub(
    text: str, strength: float = 0.7, ascii_only: bool = False
) -> dict[str, object]:
    """Destroy both channels: sanitize the character layer (Unicode), then
    paraphrase to destroy the token-choice layer, then sanitize again.

    Input is sanitized BEFORE it reaches the model. This both cleans the
    character channel and stops hidden instructions (tag chars / bidi) from
    prompt-injecting the paraphraser. Output is sanitized in case the model
    emitted any exotic characters of its own.

    ascii_only: additionally fold everything to plain ASCII (lossy). The
    strongest character-layer defense. It also kills single-script homoglyph
    spoofs, but transliterates/drops legitimate non-Latin text.
    """
    cleaned, unicode_in = sanitize_unicode(text)
    ascii_in = None
    if ascii_only:
        cleaned, ascii_in = to_ascii(cleaned)

    parts: list[str] = []
    for segment in cleaned.split("\n\n"):
        if not segment.strip():
            parts.append(segment)
            continue
        parts.append(
            chat(
                [
                    {"role": "system", "content": PARAPHRASE_SYSTEM},
                    {"role": "user", "content": segment},
                ],
                temperature=strength,
            ).strip()
        )
    scrubbed, unicode_out = sanitize_unicode("\n\n".join(parts))
    ascii_out = None
    if ascii_only:
        scrubbed, ascii_out = to_ascii(scrubbed)

    metrics = _divergence(cleaned, scrubbed)
    fdi = metrics["first_divergence_index"]
    td = metrics["token_divergence"]
    metrics["channel_broken_high_confidence"] = bool(
        isinstance(fdi, int) and fdi <= 2 and isinstance(td, float) and td >= 0.5
    )
    return {
        "scrubbed": scrubbed,
        **metrics,
        "unicode": {"input": unicode_in, "output": unicode_out},
        "ascii": {"input": ascii_in, "output": ascii_out} if ascii_only else None,
    }


def _input_hits(section: object) -> str:
    """Format the nonzero counts from a report section's 'input' dict, or ''."""
    if isinstance(section, dict) and isinstance(section.get("input"), dict):
        hits = {k: v for k, v in section["input"].items() if isinstance(v, int) and v}
        return ", ".join(f"{k}={v}" for k, v in hits.items())
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Active-warden text scrubber.")
    ap.add_argument("--text", help="Text to scrub (else read stdin).")
    ap.add_argument(
        "--strength",
        type=float,
        default=0.7,
        help="0..1.5; higher = more token divergence (stronger scrub), lower fidelity.",
    )
    ap.add_argument(
        "--ascii",
        action="store_true",
        help="Fold output to plain ASCII (lossy; strongest character-layer scrub, "
        "also kills single-script homoglyph spoofs).",
    )
    ap.add_argument("--json", action="store_true", help="Emit JSON (default: human).")
    args = ap.parse_args()

    text = args.text if args.text is not None else sys.stdin.read()
    if not text.strip():
        ap.error("no input text (use --text or pipe via stdin)")

    result = scrub(text, strength=args.strength, ascii_only=args.ascii)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["scrubbed"])
        print("\n--- warden report ---", file=sys.stderr)
        td = result["token_divergence"]
        td_pct = td * 100 if isinstance(td, (int, float)) else 0.0
        print(
            f"first change @ token {result['first_divergence_index']} "
            f"(of {result['original_token_count']}); token divergence {td_pct:.1f}%",
            file=sys.stderr,
        )
        print(
            "channel broken (high confidence): "
            + (
                "YES"
                if result["channel_broken_high_confidence"]
                else "NO (raise --strength)"
            ),
            file=sys.stderr,
        )
        uni = _input_hits(result.get("unicode"))
        if uni:
            print("unicode neutralized in input: " + uni, file=sys.stderr)
        asc = _input_hits(result.get("ascii"))
        if asc:
            print("ascii fold on input: " + asc, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
