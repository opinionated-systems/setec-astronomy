---
name: setec-astronomy
description: >-
  Neutralize hidden token-level LLM steganography (and LLM watermarks) in text by
  paraphrasing it through any OpenAI-compatible model, destroying the hidden
  channel while preserving meaning. Also embeds/extracts token-level steganography
  for demonstration. Use when the user wants to "scrub", "sanitize", "launder", or
  "strip hidden messages/watermarks from" text, defeat covert channels, or
  demonstrate LLM steganography. Bring-your-own endpoint + API key.
---

# Setec Astronomy

An **active-warden** text scrubber. Provably-secure token-level steganography
([Meteor](https://eprint.iacr.org/2021/686),
[Discop](https://dingjinyang.github.io/publication/sp23_discop/),
[minimum-entropy coupling](https://arxiv.org/abs/2210.14889)) is statistically
identical to ordinary model output, so nothing can **detect** it. This skill
**destroys** the channel instead, by paraphrasing, which re-samples the token
sequence the payload rides on and leaves the meaning of the text intact.

A second, unrelated channel gets closed first: invisible and zero-width
characters, homoglyphs, variation selectors, tag characters, bidi controls. A
deterministic Unicode pass (`scripts/unicode_scrub.py`) handles those on both
input and output. Sanitizing the input also stops any hidden instructions in it
from prompt-injecting the paraphraser. All of this happens automatically inside
`warden.py`.

For the strongest character-layer scrub, add `--ascii`. It folds the output to
plain ASCII: accents transliterated, homoglyphs folded (even single-script
spoofs), anything else non-ASCII dropped. Because it is lossy, offer it when the
text was meant to be ASCII anyway, and warn the user that legitimate non-Latin
content will be stripped.

## Setup (bring your own backend + key)

The scrubber talks to any OpenAI-compatible chat endpoint. Three env vars, with
Fireworks / OpenAI / OpenRouter / Ollama values in `.env.example`:

```
SETEC_BASE_URL   e.g. https://api.fireworks.ai/inference/v1
SETEC_API_KEY    your key
SETEC_MODEL      e.g. accounts/fireworks/models/deepseek-v4-flash
```

The key stays in the user's environment and goes only to the endpoint they chose.
Everything in `scripts/` is plain, unminified Python, so read it before use.

## How to use this skill

**Scrub text (the main capability).** Run the scrubber and report what it
measured. Prefer stdin, which keeps text with quotes and newlines safe:

```bash
printf '%s' "<TEXT>" | python scripts/warden.py --json --strength 0.7
```

Then give the user: the `scrubbed` text, `first_divergence_index` (the operative
number, since a sequential decoder desyncs at the first changed token, so an index
of 0 or near it means the channel is gone), and whether
`channel_broken_high_confidence` came back true. `token_divergence` is a coarse
surface-rewrite proxy, fine as backup but not the headline. If confidence is false,
suggest re-running at a higher `--strength`, up to 1.5. Be straight about the
limit: this destroys channels with measured high confidence, but it does not
*prove* zero residual. A scheme hardened with resync or error correction can retain
some capacity, and so can very low-entropy text.

**Token-level steganography demo (optional, heavy deps).** `scripts/stego.py` embeds and
extracts a real token-level channel with a local GPT-2, and needs
`requirements-stego.txt`. Use it to show a working channel, then scrub the cover
text and show the extraction desync:

```bash
COVER=$(python scripts/stego.py embed --secret "meet at dawn")
python scripts/stego.py extract --text "$COVER"        # recovers the secret
printf '%s' "$COVER" | python scripts/warden.py         # scrub it
python scripts/stego.py extract --text "<scrubbed>"     # now fails / desyncs
```

## Never claim detection

Do not tell a user this "detected" steganography. It neutralizes. Provably-secure
steganography passes every detector by construction, so saying otherwise is simply
false.
