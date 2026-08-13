# LLM Token-Level Steganography

The research behind this skill: how hidden messages are embedded in the *token
choices* a language model makes, why the strongest schemes cannot be detected,
and why paraphrasing destroys them anyway.

## 1. The mechanism

A language model defines a probability distribution over the next token given the
context. That distribution is a **shared resource**: a sender and receiver holding
the same model and feeding it the same context deterministically reconstruct the
*identical* distribution at every step. Hidden information rides in **which token
is selected** from among the plausible ones, so the cover text reads as ordinary
model output. Two requirements underpin decoding in every such scheme:

1. **Determinism.** Both sides must compute bit-identical logits (reference
   implementations pin CPU + float32 + fixed seed; hosted GPU inference [is usually nondeterministic, even when the temperature is set to 0](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)).
2. **Tokenization agreement.** The receiver must re-tokenize the cover text to
   the same token ids the sender emitted.

Both requirements bind the sender and receiver of two-party steganography.
Watermarking escapes them: a watermark detector re-hashes the observed tokens
with a key and needs no bit-identical model pass. Determinism is also a
constraint the encoder controls: a provider embedding a channel owns its
inference stack and can make it deterministic, so hardware nondeterminism will
not break the channel for you. Removing it is the job of the rewrite.

Capacity is entropy-bound: bits per token ≈ the entropy of the distribution at
that step.

## 2. Method families

- **Bins / Huffman (detectable).** Groups of the vocabulary encode bits; the true
  probabilities are overridden, so the distribution is perturbed and a classifier
  can flag it. Fang et al., 2017 ([arXiv:1705.10742](https://arxiv.org/abs/1705.10742)).
  `scripts/stego.py` is deliberately in this family (bit-exactly reversible, so it
  *proves* the determinism + tokenization plumbing).
- **Arithmetic / range coding (near-secure).** Token selection follows the true
  CDF, so the output is statistically close to ordinary model output. Ziegler,
  Deng, Rush, EMNLP 2019
  ([arXiv:1909.01496](https://arxiv.org/abs/1909.01496)).
- **Provably secure / distribution-preserving.** Output is drawn from the *same*
  distribution as ordinary sampling:
  - de Witt et al., "Perfectly Secure Steganography Using Minimum Entropy
    Coupling", ICLR 2023 ([arXiv:2210.14889](https://arxiv.org/abs/2210.14889)).
  - Sokota et al., ARIMEC, UAI 2024 ([arXiv:2405.19540](https://arxiv.org/abs/2405.19540)).
  - Zhang, Yang, Yang, Huang, ADG, ACL Findings 2021 ([arXiv:2106.02011](https://arxiv.org/abs/2106.02011)).
  - Ding et al., "Discop", IEEE S&P 2023 ([code](https://github.com/comydream/Discop)).
  - Wang et al., "SparSamp", USENIX Security 2025 ([arXiv:2503.19499](https://arxiv.org/abs/2503.19499)).
  - Kaptchuk et al., "Meteor", ACM CCS 2021 ([IACR ePrint 2021/686](https://eprint.iacr.org/2021/686)).
- **Steganalysis / safety framing.** Tang et al., 2024
  ([arXiv:2406.04218](https://arxiv.org/abs/2406.04218)); Anwar et al., LLM
  monitoring, 2026 ([arXiv:2602.23163](https://arxiv.org/abs/2602.23163)).

## 3. Neutralization instead of detection

A scheme is **perfectly secure** (Cachin 1998) iff the stego text is
statistically indistinguishable from the model's own output to a warden who may
even know the model. de Witt et al. proved that a procedure is perfectly secure
exactly when it is induced by a *coupling* of the cover and secret-message
distributions, and that the minimum-entropy coupling is the throughput-optimal one.
Consequence: the strong schemes above are
**undetectable by construction**: no statistical test separates them from a
normal completion.

The escape is the **active warden** (from Simmons' prisoners' problem), which
rewrites all traffic rather than inspecting it. Pass every piece of text through
a paraphraser that re-samples the surface form while preserving meaning. A sequential coder (arithmetic / Huffman /
minimum-entropy coupling) desyncs at the **first** altered token and loses
everything downstream. The same rewrite defeats LLM watermarks, which ride on the
same token choices.

Paraphrasing cannot *prove* zero residual capacity. A resync- or
error-correction-hardened scheme, or very low-entropy text that can't be reworded
without changing meaning, can retain some. This is why the tool reports a
*measured* token divergence instead of claiming certainty.

## 4. The character-layer channel (orthogonal)

Everything above hides data in *which token* is chosen. A separate, deterministic
family hides it in *which characters* are used, and paraphrase does not reliably
touch it: invisible/zero-width characters (U+200B–200D, U+FEFF, soft hyphen),
variation selectors (U+FE00–FE0F and U+E0100–E01EF, the emoji-smuggling vector),
Unicode tag characters (U+E0000–E007F), bidi controls (U+202A–202E and
U+2066–2069, Trojan Source), and homoglyphs/confusables (Cyrillic а, Greek Ο
looking Latin).
These are also a prompt-injection vector: hidden instructions can ride into the
paraphraser itself. `scripts/unicode_scrub.py` neutralizes this layer
deterministically (stdlib only), on both input and output. Homoglyph folding is
applied only to mixed-script words (the attack signature), so legitimate
non-Latin text is left intact.

## 5. This repo

- `scripts/warden.py`, the active warden: paraphrase via any OpenAI-compatible
  endpoint plus a token-divergence metric.
- `scripts/stego.py`, the reference channel (GPT-2 Huffman-per-token) the warden
  defends against. Verified end-to-end (2026-08-12): bit-exact roundtrip, and a
  desync after a real `warden.py` paraphrase (Ollama `llama3.2:3b`, ~62% token
  divergence, meaning preserved). See the "End-to-end run" block in the README.
