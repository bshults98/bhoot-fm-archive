"""Tests for the Banglish -> Bangla transliterator (static/banglish.js).

Pure JS module, but small enough that we test it by stubbing `window` and
exec'ing the source under Python's eval-equivalent — except JS isn't Python,
so we run it under Node. Pytest skips this whole file if Node isn't
installed, so it stays optional.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BANGLISH_JS = ROOT / "static" / "banglish.js"

if not shutil.which("node"):
    pytest.skip("node not on PATH; skipping JS tests", allow_module_level=True)


def _run(*queries: str) -> list[dict]:
    """Invoke the transliterator under Node and return parsed results."""
    src = BANGLISH_JS.read_text(encoding="utf-8")
    queries_json = json.dumps(list(queries))
    program = (
        f"const window = {{}};\n"
        f"{src}\n"
        f"const inputs = {queries_json};\n"
        f"const out = inputs.map(q => window.banglishToBangla(q));\n"
        f"process.stdout.write(JSON.stringify(out));\n"
    )
    result = subprocess.run(
        ["node", "-e", program],
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestDictionary:
    """Curated dictionary hits — the high-confidence path."""

    def test_loanwords(self):
        out = _run("hospital", "ambulance", "doctor", "police", "school")
        assert out[0]["bangla"] == "হাসপাতাল"
        assert out[0]["transformed"] is True
        assert out[1]["bangla"] == "অ্যাম্বুলেন্স"
        assert out[2]["bangla"] == "ডাক্তার"
        assert out[3]["bangla"] == "পুলিশ"
        assert out[4]["bangla"] == "স্কুল"

    def test_horror_vocab(self):
        out = _run("bhoot", "bhuter", "jin", "preto", "atma")
        assert out[0]["bangla"] == "ভূত"
        assert out[1]["bangla"] == "ভূতের"
        assert out[2]["bangla"] == "জিন"
        assert out[3]["bangla"] == "প্রেত"
        assert out[4]["bangla"] == "আত্মা"

    def test_proper_nouns(self):
        out = _run("russell", "foorti", "fm", "rj")
        assert out[0]["bangla"] == "রাসেল"
        assert out[1]["bangla"] == "ফুর্তি"
        assert out[2]["bangla"] == "এফএম"
        assert out[3]["bangla"] == "আরজে"

    def test_case_insensitive(self):
        # Users type "Hospital" or "HOSPITAL" — same Bangla either way.
        out = _run("Hospital", "HOSPITAL", "HoSpItAl")
        for r in out:
            assert r["bangla"] == "হাসপাতাল"


class TestPassthrough:
    """Inputs that should NOT be transliterated."""

    def test_bangla_input_unchanged(self):
        # If the user typed Bangla, leave it alone — they know what they want.
        out = _run("হাসপাতাল", "ভূত", "রাত")
        for r in out:
            assert r["transformed"] is False
            assert r["bangla"] == r["original"]

    def test_mixed_script_keeps_bangla(self):
        # A query containing any Bangla character is treated as already-Bangla
        # so we don't accidentally munge it.
        out = _run("ভূত fm")
        assert out[0]["transformed"] is False

    def test_empty_input(self):
        out = _run("", "   ")
        assert out[0]["bangla"] == ""
        assert out[0]["transformed"] is False

    def test_no_letters(self):
        # A query that is only digits / punctuation has nothing to transliterate.
        out = _run("123", "!!!")
        for r in out:
            assert r["transformed"] is False


class TestAlgorithmicFallback:
    """Words not in the dictionary — algorithmic transliteration must produce
    SOMETHING (not crash, not empty), but we don't pin exact output because
    the algorithm is approximate by design."""

    def test_unknown_word_produces_bangla(self):
        # Pick a word we haven't seeded in the dictionary.
        out = _run("kothin")
        r = out[0]
        assert r["transformed"] is True
        # Output must be non-empty and contain Bangla codepoints.
        assert r["bangla"], "expected non-empty transliteration"
        assert any("ঀ" <= c <= "৿" for c in r["bangla"])

    def test_phrase_preserves_word_boundaries(self):
        # Multi-word input: each word is transliterated independently and
        # whitespace is preserved.
        out = _run("bhoot raat")
        # Both halves are dictionary hits ("ভূত" + "রাত").
        assert out[0]["bangla"] == "ভূত রাত"


class TestStructure:
    """Output shape is part of the contract; renderSearch reads these fields."""

    def test_return_shape(self):
        out = _run("hospital")[0]
        assert set(out.keys()) >= {"bangla", "original", "transformed"}
        assert isinstance(out["transformed"], bool)
