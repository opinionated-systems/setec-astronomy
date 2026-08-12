#!/usr/bin/env python3
"""Deterministic Unicode sanitization: the second, orthogonal channel.

Paraphrasing (warden.py) destroys the token-CHOICE channel. It does NOT reliably
touch steganography encoded in the CHARACTERS themselves, which is a separate
attack surface:

  * invisible / zero-width chars (U+200B..U+200D, U+2060, U+FEFF, soft hyphen…)
  * variation selectors (U+FE00..U+FE0F, U+E0100..U+E01EF), the emoji-smuggling
    vector for hiding arbitrary bytes on a visible character
  * Unicode tag characters (U+E0000..U+E007F), invisible ASCII smuggling
  * bidi controls (U+202A..U+202E, U+2066..U+2069), Trojan-Source reordering
  * homoglyphs / confusables: "dual meaning" chars that look Latin but aren't
    (Cyrillic а/е/о/р/с/х, Greek Ο/Α…), used to hide data or evade filters
  * exotic whitespace variants used as a substitution channel

This pass is stdlib-only, deterministic, and reports exactly what it changed.

Cross-script folding is applied ONLY to mixed-script words (Latin + a stray
confusable), which is the attack signature. Pure Cyrillic/Greek/etc. text is
left intact so legitimate non-Latin writing is not mangled.

Known side effects: stripping ZWJ/variation selectors can alter emoji sequences
(family/flag emoji, presentation selectors), and stripping bidi controls can
affect legitimately mixed RTL/LTR text. Those characters are the covert-channel
carriers, so a scrubber has to remove them anyway.
"""

import re
import unicodedata

# Characters removed entirely (invisible or format controls with no legitimate
# textual payload in this context).
_ZERO_WIDTH = {
    0x00AD,  # soft hyphen
    0x034F,  # combining grapheme joiner
    0x061C,  # arabic letter mark
    # hangul choseong/jungseong fillers
    0x115F,
    0x1160,
    # khmer inherent vowels
    0x17B4,
    0x17B5,
    0x180E,  # mongolian vowel separator (deprecated)
    # ZWSP, ZWNJ, ZWJ
    0x200B,
    0x200C,
    0x200D,
    # word joiner + invisible math ops
    0x2060,
    0x2061,
    0x2062,
    0x2063,
    0x2064,
    0x2800,  # braille blank (renders empty)
    # hangul fillers
    0x3164,
    0xFFA0,
    0xFEFF,  # BOM / zero-width no-break space
}
# LRM/RLM plus the embedding, override, and isolate controls (Trojan Source).
_BIDI = {
    0x200E,
    0x200F,
    0x202A,
    0x202B,
    0x202C,
    0x202D,
    0x202E,
    0x2066,
    0x2067,
    0x2068,
    0x2069,
}
# Exotic spaces folded to a normal ASCII space.
_ODD_SPACE = {
    0x00A0,
    0x1680,
    0x202F,
    0x205F,
    0x3000,
    *range(0x2000, 0x200B),  # en/em/thin/hair spaces etc.
}

# Curated cross-script confusables → Latin skeleton (applied only in mixed-script
# words). Not exhaustive (the full Unicode confusables table has thousands), but
# covers the practical Cyrillic/Greek Latin-lookalike attacks.
_CONFUSABLES = {
    # Cyrillic → Latin
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "У": "Y",
    "Х": "X",
    "І": "I",
    "Ј": "J",
    "Ѕ": "S",
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "у": "y",
    "х": "x",
    "і": "i",
    "ј": "j",
    "ѕ": "s",
    "ԁ": "d",
    "ԛ": "q",
    "ԝ": "w",
    # Greek → Latin
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Ζ": "Z",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Υ": "Y",
    "Χ": "X",
    "α": "a",
    "ο": "o",
    "ρ": "p",
    "ν": "v",
    "κ": "k",
    "ι": "i",
    "τ": "t",
}

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)  # maximal runs of letters


def _script(ch: str) -> str:
    try:
        return unicodedata.name(ch).split(" ")[0]  # LATIN / CYRILLIC / GREEK / …
    except ValueError:
        return ""


def _fold_word(word: str, counter: list[int]) -> str:
    scripts = {_script(ch) for ch in word}
    scripts.discard("")
    if "LATIN" in scripts and scripts - {"LATIN"}:  # mixed-script = suspicious
        folded = []
        for ch in word:
            repl = _CONFUSABLES.get(ch, ch)
            if repl != ch:
                counter[0] += 1
            folded.append(repl)
        return "".join(folded)
    return word


def sanitize_unicode(text: str) -> tuple[str, dict[str, int]]:
    """Return (cleaned_text, report). report counts each category neutralized."""
    report = {
        "zero_width_removed": 0,
        "bidi_controls_removed": 0,
        "variation_selectors_removed": 0,
        "tag_chars_removed": 0,
        "odd_whitespace_normalized": 0,
        "homoglyphs_folded": 0,
        "nfkc_normalized": 0,
    }

    out: list[str] = []
    for ch in text:
        cp = ord(ch)
        if cp in _ZERO_WIDTH:
            report["zero_width_removed"] += 1
        elif cp in _BIDI:
            report["bidi_controls_removed"] += 1
        elif 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF:
            report["variation_selectors_removed"] += 1
        elif 0xE0000 <= cp <= 0xE007F:
            report["tag_chars_removed"] += 1
        elif cp in _ODD_SPACE:
            out.append(" ")
            report["odd_whitespace_normalized"] += 1
        elif cp in (0x2028, 0x2029):  # line / paragraph separators
            out.append("\n")
            report["odd_whitespace_normalized"] += 1
        else:
            out.append(ch)
    s = "".join(out)

    nfkc = unicodedata.normalize("NFKC", s)
    if nfkc != s:
        report["nfkc_normalized"] = 1
    s = nfkc

    counter = [0]
    s = _WORD.sub(lambda m: _fold_word(m.group(0), counter), s)
    report["homoglyphs_folded"] = counter[0]

    return s, report


# Typographic punctuation → ASCII, for the aggressive ascii-only mode. NFKD (run
# first in to_ascii) already folds ligatures, fractions, NBSP, and the ellipsis;
# these are the ones with no compatibility decomposition (smart quotes, dashes…).
_PUNCT_ASCII = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "«": '"',
    "»": '"',
    "‹": "'",
    "›": "'",
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "•": "*",
    "·": ".",
    "‧": ".",
    "・": ".",
    "⁄": "/",
    "∕": "/",
    "×": "x",
    "÷": "/",
}


def to_ascii(text: str) -> tuple[str, dict[str, int]]:
    """Fold to plain 7-bit ASCII: the aggressive, LOSSY character-layer option.

    NFKD-decompose (so accented Latin degrades to its base letter, café → cafe),
    drop the combining marks, map known confusables and typographic punctuation
    to ASCII, and drop anything else non-ASCII. This is the strongest defense
    against the character channel: it also folds SINGLE-script homoglyph spoofs
    (an all-Cyrillic word spelling a Latin one) that mixed-script folding skips.

    It is destructive: legitimate non-Latin text (accented names, Chinese,
    Japanese, Korean, emoji) is transliterated or removed. Opt in only when the
    content is meant to be ASCII.
    """
    report = {"non_ascii_mapped": 0, "accents_stripped": 0, "chars_dropped": 0}
    out: list[str] = []
    for ch in unicodedata.normalize("NFKD", text):
        if ord(ch) < 128:
            out.append(ch)
            continue
        if unicodedata.category(ch) == "Mn":  # combining mark from decomposition
            report["accents_stripped"] += 1
            continue
        repl = _PUNCT_ASCII.get(ch) or _CONFUSABLES.get(ch)
        if repl is not None:
            out.append(repl)
            report["non_ascii_mapped"] += 1
        else:
            report["chars_dropped"] += 1
    return "".join(out), report


if __name__ == "__main__":  # quick self-check
    dirty = "Bl​ock the gаte"  # ZWSP + Cyrillic 'а' in "gate"
    clean, rep = sanitize_unicode(dirty)
    print(f"sanitize in : {dirty!r}")
    print(f"sanitize out: {clean!r}  {rep}")
    spoof = "Pаypаl café — “quote”"  # all-Cyrillic-'а' spoof + accent + smart quotes
    ascii_txt, arep = to_ascii(spoof)
    print(f"ascii in    : {spoof!r}")
    print(f"ascii out   : {ascii_txt!r}  {arep}")
