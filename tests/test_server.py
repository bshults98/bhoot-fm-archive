"""Tests for the security-critical bits of server.py.

These functions all sit between user input and our SQL / filesystem layer, so
a regression here is a vulnerability, not just a UX bug. Keep this file
focused: don't grow it into a general server test suite — for that, put
network-level tests in tests/test_routes.py with FastAPI's TestClient.
"""

import re
import sys
from pathlib import Path

# Make `server` importable when pytest runs from the repo root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


# ─── fts_query: FTS5 query builder ──────────────────────────────────
# fts_query takes raw user input and produces an FTS5 MATCH string. The
# danger is that FTS5 has its own query language (AND/OR/NOT, NEAR(), quoted
# phrases, column filters) — if we pass user input through unescaped, an
# attacker can change query semantics or trigger a parse error that 500s us.

class TestFtsQuery:
    def test_basic_bangla_word(self):
        out = server.fts_query("হাসপাতাল")
        assert out == '"হাসপাতাল"*'

    def test_basic_english_word(self):
        # ASCII input still gets quoted + prefix-matched. Real callers will
        # transliterate first, but the function should not crash on it.
        out = server.fts_query("hospital")
        assert out == '"hospital"*'

    def test_multi_token_is_AND(self):
        # FTS5 default operator between bare terms is AND. We rely on that:
        # multi-word queries should narrow, not broaden.
        out = server.fts_query("রাত গাড়ি")
        assert out == '"রাত"* "গাড়ি"*'

    def test_empty_returns_empty(self):
        assert server.fts_query("") == ""
        assert server.fts_query("   ") == ""
        assert server.fts_query(None) == ""  # type: ignore[arg-type]

    def test_strips_fts5_operators(self):
        # The classic injection: an attacker tries to inject AND/OR/NEAR/NOT
        # or column filters. The allowlist regex should reduce all of them
        # to whitespace so they fall out at tokenization.
        for hostile in [
            "foo AND bar",
            "foo OR bar",
            "foo NOT bar",
            "NEAR(foo bar)",
            "column:foo",
            "foo* bar*",
            "foo^2 bar",
        ]:
            out = server.fts_query(hostile)
            # The safety property: no raw FTS5 operator forms leak through.
            # Bare words like AND/OR/NEAR are fine — they end up as quoted
            # search literals ("AND"*) which FTS5 treats as ordinary terms.
            # The dangerous forms are the operator *syntax*: `NEAR(` for the
            # proximity operator, `:` for column filters, `^` for column
            # filtering with `*` for prefix operators.
            assert "NEAR(" not in out
            assert ":" not in out
            assert "^" not in out
            # And the output is well-formed: a sequence of "word"* atoms.
            # If this matches, no operator can escape the quoted-prefix form.
            assert re.fullmatch(r'("\S+"\*)( "\S+"\*)*', out), out

    def test_strips_quotes(self):
        # Double quotes would break the wrapping we do; the regex maps them
        # to spaces, so output is just well-formed prefix tokens.
        out = server.fts_query('foo "bar baz"')
        assert '""' not in out
        assert re.fullmatch(r'("\S+"\*)( "\S+"\*)*', out)

    def test_respects_max_search_len(self):
        # Cap at MAX_SEARCH_LEN. We don't want a 1 MB query to even reach
        # the regex engine.
        huge = "a" * (server.MAX_SEARCH_LEN + 500)
        out = server.fts_query(huge)
        # The unique token in the output must be capped to MAX_SEARCH_LEN
        # (it'll be a single quoted prefix-matched token).
        m = re.fullmatch(r'"(a+)"\*', out)
        assert m and len(m.group(1)) == server.MAX_SEARCH_LEN

    def test_bangla_and_ascii_mixed(self):
        # Mixed scripts should preserve both — Banglish transliteration may
        # legitimately produce mixed input during the transition period.
        out = server.fts_query("হাসপাতাল hospital")
        assert '"হাসপাতাল"*' in out
        assert '"hospital"*' in out


# ─── _EP_ID_RE: episode-id validator (path-traversal guard) ─────────
# This regex appears in /api/episode/{id}, /api/episode/{id}/audio,
# /episode/{id}, and POST /api/play. A bug here = the audio handler tries
# to open a file at an attacker-controlled path.

class TestEpisodeIdRegex:
    def test_accepts_canonical_date(self):
        assert server._EP_ID_RE.match("2013-05-17")

    def test_accepts_pt_suffix(self):
        # Some episodes were split into parts (-pt1, -pt2).
        assert server._EP_ID_RE.match("2013-05-17-pt1")
        assert server._EP_ID_RE.match("2013-05-17-pt9")

    def test_rejects_path_traversal(self):
        for hostile in [
            "../etc/passwd",
            "2013-05-17/../../../etc/passwd",
            "2013-05-17\x00.mp3",
            "/etc/passwd",
            "..\\..\\windows\\system32",
        ]:
            assert not server._EP_ID_RE.match(hostile), hostile

    def test_rejects_partial_dates(self):
        # Don't let a sloppy regex accept underspecified ids.
        for bad in ["2013", "2013-5-17", "2013-05", "2013-05-1", "13-05-17"]:
            assert not server._EP_ID_RE.match(bad), bad

    def test_rejects_extra_suffix(self):
        # -pt followed by anything other than a single digit must fail.
        assert not server._EP_ID_RE.match("2013-05-17-pt99")
        assert not server._EP_ID_RE.match("2013-05-17-ptx")
        assert not server._EP_ID_RE.match("2013-05-17-extra")

    def test_anchored(self):
        # Without ^ and $ a regex like \d{4}-\d{2}-\d{2} would match a
        # prefix of "../2013-05-17/../etc". Confirm anchoring.
        assert not server._EP_ID_RE.match("xx2013-05-17xx")
        assert not server._EP_ID_RE.match("2013-05-17.mp3")


# ─── _YEAR_RE: year validator for /episodes/{year} ──────────────────

class TestYearRegex:
    def test_accepts_four_digit(self):
        assert server._YEAR_RE.match("2013")
        assert server._YEAR_RE.match("0000")
        assert server._YEAR_RE.match("9999")

    def test_rejects_non_year(self):
        for bad in ["13", "20133", "20a3", "../2013", "2013/", ""]:
            assert not server._YEAR_RE.match(bad), bad


# ─── _bust_html_cache: deploy cache-buster ──────────────────────────
# This rewrites same-origin asset URLs to include ?v=<version>. Bug here =
# either stale assets on mobile (the original problem) or rewriting URLs
# we shouldn't (e.g., the GoatCounter CDN), which would break analytics.

class TestCacheBuster:
    def test_rewrites_local_js(self):
        out = server._bust_html_cache('<script src="app.js"></script>')
        assert f"app.js?v={server.ASSET_VERSION}" in out

    def test_rewrites_local_css(self):
        out = server._bust_html_cache('<link href="style.css" rel="stylesheet" />')
        assert f"style.css?v={server.ASSET_VERSION}" in out

    def test_rewrites_absolute_local_path(self):
        # /favicon.svg should be busted because it lives on our origin.
        out = server._bust_html_cache('<link href="/favicon.svg" />')
        assert f"/favicon.svg?v={server.ASSET_VERSION}" in out

    def test_leaves_cdn_alone(self):
        # External scripts (GoatCounter) must not be rewritten or we'd
        # break the third-party caching strategy and analytics.
        cdn = '<script src="//gc.zgo.at/count.js"></script>'
        assert server._bust_html_cache(cdn) == cdn

        cdn_https = '<script src="https://gc.zgo.at/count.js"></script>'
        assert server._bust_html_cache(cdn_https) == cdn_https

    def test_preserves_existing_query(self):
        # If a URL already has a ?param, the buster appends with & not ?.
        out = server._bust_html_cache('<script src="a.js?x=1"></script>')
        assert f"a.js?x=1&v={server.ASSET_VERSION}" in out

    def test_ignores_non_asset_extensions(self):
        # Random href targets (e.g. a downloadable .txt) shouldn't be touched.
        original = '<a href="/about.html">about</a>'
        assert server._bust_html_cache(original) == original
