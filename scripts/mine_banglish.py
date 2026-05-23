"""Mine the transcript corpus for common Bangla words and produce candidate
Banglish (Latin-letter phonetic) spellings.

Output is a JSON object { "<banglish_token>": "<bangla>" } sorted by Bangla
frequency. You'll then merge the entries that look right into the DICT table
at the top of static/banglish.js.

Why this matters: our hand-curated dictionary covers ~80 high-priority loan
words (hospital, ambulance, etc.) but the corpus contains thousands of common
Bangla words a listener might type phonetically. Auto-generating candidates
turns a hand-maintained list into one that grows with the archive — every new
transcript you ingest expands what the search bar understands.

Usage (Windows PowerShell):
    python scripts/mine_banglish.py
    # writes scripts/banglish_candidates.json — review then paste into
    # static/banglish.js

The reverse transliteration is deliberately many-to-many. For each Bangla
token we emit *all* plausible Banglish renderings (e.g., হাসপাতাল ->
"haaspaataal", "hashpatal", "haspataal", ...). Listeners will type whichever
feels natural and any of them now resolves to the same Bangla word.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS = ROOT / "transcripts"
OUT = ROOT / "scripts" / "banglish_candidates.json"

# How many of the most-frequent unique Bangla tokens to consider. The top
# slice covers the words a casual searcher is most likely to type.
TOP_N = 1500

# Skip very short tokens (mostly inflectional particles, low SEO value)
MIN_LEN = 3

# ─── Bangla -> Banglish reverse map ──────────────────────────────────
# Order matters: longer multi-codepoint sequences first so we consume
# conjuncts and kar marks before bare consonants.
#
# Each Bangla grapheme maps to a list of plausible Latin renderings; we
# Cartesian-product across a token to enumerate variants.

VOWEL_INDEPENDENT = {
    "অ": ["o", "a"],
    "আ": ["a", "aa"],
    "ই": ["i"],
    "ঈ": ["i", "ee"],
    "উ": ["u"],
    "ঊ": ["u", "oo"],
    "ঋ": ["ri"],
    "এ": ["e"],
    "ঐ": ["oi", "oy"],
    "ও": ["o"],
    "ঔ": ["ou", "ow"],
}

VOWEL_KAR = {
    "া": ["a", "aa"],
    "ি": ["i"],
    "ী": ["i", "ee"],
    "ু": ["u"],
    "ূ": ["u", "oo"],
    "ৃ": ["ri"],
    "ে": ["e"],
    "ৈ": ["oi", "oy"],
    "ো": ["o"],
    "ৌ": ["ou", "ow"],
}

CONSONANTS = {
    "ক": ["k"],
    "খ": ["kh"],
    "গ": ["g"],
    "ঘ": ["gh"],
    "ঙ": ["ng"],
    "চ": ["ch", "c"],
    "ছ": ["chh", "ch"],
    "জ": ["j"],
    "ঝ": ["jh"],
    "ঞ": ["ng"],
    "ট": ["t"],
    "ঠ": ["th"],
    "ড": ["d"],
    "ঢ": ["dh"],
    "ণ": ["n"],
    "ত": ["t"],
    "থ": ["th"],
    "দ": ["d"],
    "ধ": ["dh"],
    "ন": ["n"],
    "প": ["p"],
    "ফ": ["ph", "f"],
    "ব": ["b"],
    "ভ": ["bh", "v"],
    "ম": ["m"],
    "য": ["y", "j"],
    "র": ["r"],
    "ল": ["l"],
    "শ": ["sh", "s"],
    "ষ": ["sh", "s"],
    "স": ["s"],
    "হ": ["h"],
    "ড়": ["r"],
    "ঢ়": ["rh"],
    "য়": ["y"],
    "ৎ": ["t"],
    "ং": ["ng"],
    "ঁ": [""],
    "ঃ": ["h"],
}

HALANT = "্"   # virama — joins consonants into conjuncts
INHERENT_A = "o"   # spoken realization of the inherent vowel in BN dialects


def reverse_transliterate(token: str) -> list[str]:
    """Return up to ~8 plausible Latin renderings of a Bangla token.

    Algorithm: walk codepoints left-to-right, build a list of "slot options"
    (a list of strings the current codepoint could become), then Cartesian-
    product across slots. We cap variants per token to keep the output bounded
    — past ~8 variants the marginal value drops off and the file balloons.
    """
    slots: list[list[str]] = []
    i = 0
    while i < len(token):
        ch = token[i]
        nxt = token[i + 1] if i + 1 < len(token) else ""

        if ch in CONSONANTS:
            opts = list(CONSONANTS[ch])
            # Halant suppresses the inherent vowel; otherwise the consonant
            # is implicitly followed by /o/ (or /a/ in some words). We always
            # try the no-vowel variant first, then add the inherent-vowel
            # form as a sibling option.
            if nxt == HALANT:
                slots.append(opts)
                i += 2
                continue
            if i + 1 < len(token) and token[i + 1] in VOWEL_KAR:
                # An explicit kar follows; consonant alone, then kar fills it
                slots.append(opts)
                i += 1
                continue
            # No following vowel -> inherent /o/ /a/. Both common in typing.
            slots.append([o + INHERENT_A for o in opts] + opts)
            i += 1
            continue

        if ch in VOWEL_KAR:
            slots.append(VOWEL_KAR[ch])
            i += 1
            continue

        if ch in VOWEL_INDEPENDENT:
            slots.append(VOWEL_INDEPENDENT[ch])
            i += 1
            continue

        # Unknown codepoint (rare — diacritics, ZWJ, punctuation). Skip.
        i += 1

    if not slots:
        return []

    # Cartesian product, capped.
    out: list[str] = [""]
    for slot in slots:
        new_out: list[str] = []
        for prefix in out:
            for opt in slot:
                new_out.append(prefix + opt)
        out = new_out
        # Hard cap to prevent combinatorial blow-up on long words.
        if len(out) > 32:
            out = out[:32]
    # Dedupe while preserving order, and drop empties.
    seen = set()
    uniq = []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq[:8]


def main() -> int:
    if not TRANSCRIPTS.exists():
        print(f"No transcripts dir at {TRANSCRIPTS}", file=sys.stderr)
        return 1

    counter: Counter[str] = Counter()
    # Pure-Bangla token: 3+ Bangla codepoints, optional internal halants/kars.
    bn_token_re = re.compile(r"[ঀ-৿]{%d,}" % MIN_LEN)

    files = list(TRANSCRIPTS.rglob("*.json"))
    print(f"Scanning {len(files)} transcript files...")
    for fp in files:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  skip {fp.name}: {e}", file=sys.stderr)
            continue
        for seg in data.get("segments", []):
            text = seg.get("text", "")
            for tok in bn_token_re.findall(text):
                counter[tok] += 1

    print(f"Found {len(counter):,} unique tokens; taking top {TOP_N}.")
    top = counter.most_common(TOP_N)

    # Build the candidate map: { banglish_spelling -> canonical Bangla token }
    # If two Bangla tokens collide on a Banglish spelling, the more frequent
    # token wins (we iterate top->bottom and skip duplicates).
    out: dict[str, str] = {}
    for bn_token, _count in top:
        for latin in reverse_transliterate(bn_token):
            if latin in out:
                continue
            # Drop spellings that turn out to be raw ASCII a user is unlikely
            # to type as a search term (1-2 letters, numbers).
            if len(latin) < 3:
                continue
            out[latin] = bn_token

    # Sort by Banglish spelling for a clean diff.
    out_sorted = dict(sorted(out.items()))
    OUT.write_text(
        json.dumps(out_sorted, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(out_sorted):,} candidates -> {OUT}")
    print("Review the JSON and paste the entries you trust into the DICT")
    print("table at the top of static/banglish.js.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
