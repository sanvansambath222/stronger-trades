"""Backend tests for ATR-based SL/TP, Auto-upgrade to Deep AI, and Strong-only filter.

Covers the new features added to /api/analysis/ai:
- sl_method field formatted as "ATR(<num>) × <mult>" or "<x.x>% of price"
- auto_upgraded flag
- engine=rule | engine=ai branches
- Auto-upgrade to Dual-AI (Claude + Gemini) on STRONG/VERY_STRONG signals
- Cache key includes auto_upgrade flag (au0 vs au1)
- Negative path: WEAK/HOLD does NOT trigger upgrade
- /api/signals/stats schema
- Smoke checks: /api/market/quote, /api/market/candles, /api/news, /api/ea/download, /api/ea/signal
"""
import os
import re
import time
import pytest
import requests

_BACKEND_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not _BACKEND_URL:
    # Fallback to reading frontend/.env so tests can run without exported env
    try:
        with open("/app/frontend/.env") as _f:
            for _line in _f:
                if _line.startswith("REACT_APP_BACKEND_URL="):
                    _BACKEND_URL = _line.split("=", 1)[1].strip().strip('"')
                    break
    except OSError:
        pass
if not _BACKEND_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL not configured")
BASE_URL = _BACKEND_URL.rstrip("/")
API = f"{BASE_URL}/api"

# Generous timeout — Dual-LLM ensemble can take 20-50s
AI_TIMEOUT = 90
HTTP_TIMEOUT = 30


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _safe_get(session, url, params=None, timeout=HTTP_TIMEOUT, retries=2):
    """Resilient GET that retries on 5xx (typically TwelveData 429 leaking as 500)."""
    last = None
    for attempt in range(retries + 1):
        r = session.get(url, params=params, timeout=timeout)
        last = r
        if r.status_code < 500:
            return r
        if attempt < retries:
            time.sleep(40)  # wait for TwelveData free-tier quota refresh
    return last


# ===========================================================================
# AISignal Pydantic serialization — sl_method (Optional[str]) + auto_upgraded
# ===========================================================================
class TestAISignalSerialization:
    """Verify the new AISignal fields serialize correctly."""

    def test_rule_signal_has_new_fields(self, session):
        r = _safe_get(session, f"{API}/analysis/ai",
                      params={"interval": "1h", "engine": "rule", "auto_upgrade": "false"},
                      timeout=AI_TIMEOUT)
        assert r.status_code == 200, f"body={r.text[:500]}"
        d = r.json()
        assert "sl_method" in d, "sl_method field missing from response"
        assert "auto_upgraded" in d, "auto_upgraded field missing"
        assert isinstance(d["auto_upgraded"], bool)
        # sl_method may be a string or None (fallback)
        assert d["sl_method"] is None or isinstance(d["sl_method"], str)


# ===========================================================================
# Rule engine + ATR-based sl_method
# ===========================================================================
class TestRuleEngineATR:
    """sl_method should be formatted like 'ATR(<num>) × <mult>' or 'x.x% of price'."""

    def test_rule_engine_returns_sl_method_string(self, session):
        r = _safe_get(session, f"{API}/analysis/ai",
                      params={"interval": "1h", "engine": "rule", "auto_upgrade": "false"},
                      timeout=AI_TIMEOUT)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert d["auto_upgraded"] is False, "auto_upgraded must be false on bare rule call"
        # With 120 candles fetched, ATR should typically be computable
        sl_method = d.get("sl_method")
        assert sl_method is not None, "sl_method should be populated by rule engine"
        # Accept both ATR and percent fallback formats
        atr_pattern = re.compile(r"ATR\(\d+(\.\d+)?\)\s*[×x]\s*\d+(\.\d+)?", re.IGNORECASE)
        pct_pattern = re.compile(r"\d+(\.\d+)?%\s*of\s*price", re.IGNORECASE)
        assert atr_pattern.search(sl_method) or pct_pattern.search(sl_method), \
            f"sl_method format unexpected: {sl_method!r}"

    def test_rule_engine_daily_atr_multiplier_2(self, session):
        """Daily TF should use ATR multiplier 2.0 → sl_method contains '× 2' or '× 2.0'."""
        r = _safe_get(session, f"{API}/analysis/ai",
                      params={"interval": "1day", "engine": "rule", "auto_upgrade": "false"},
                      timeout=AI_TIMEOUT)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        sl_method = d.get("sl_method") or ""
        # If ATR worked, multiplier should be 2.0 for 1day
        if "ATR" in sl_method:
            assert ("× 2" in sl_method) or ("x 2" in sl_method.lower()), \
                f"Expected ATR multiplier 2 for 1day, got: {sl_method!r}"


# ===========================================================================
# Auto-upgrade flow → Dual-AI ensemble
# ===========================================================================
class TestAutoUpgrade:
    """When engine=rule + STRONG signal + auto_upgrade=true, we escalate to Claude+Gemini."""

    def test_auto_upgrade_1h(self, session):
        # Clear cache by trying with auto_upgrade=true; whether it actually upgrades
        # depends on the rule engine emitting STRONG/VERY_STRONG.
        r = _safe_get(session, f"{API}/analysis/ai",
                      params={"interval": "1h", "engine": "rule", "auto_upgrade": "true"},
                      timeout=AI_TIMEOUT)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert "auto_upgraded" in d
        assert "consensus" in d
        assert isinstance(d.get("votes"), list)

        strength = (d.get("signal_strength") or "").upper()
        action = (d.get("action") or "").upper()

        if d["auto_upgraded"]:
            # When auto-upgraded:
            # - rule action should have been BUY/SELL with STRONG/VERY_STRONG
            assert d["consensus"] in ("DOUBLE_CONFIRMED", "MAJORITY", "CONFLICTED"), \
                f"Unexpected consensus on upgrade: {d['consensus']}"
            model_ids = {v.get("model_id") for v in d["votes"]}
            assert "claude" in model_ids, f"claude vote missing: {model_ids}"
            assert "gemini" in model_ids, f"gemini vote missing: {model_ids}"
            # sl_method should be preserved from rule pass
            assert d.get("sl_method") is not None, "sl_method should be preserved post-upgrade"
        else:
            # Not upgraded because rule didn't emit STRONG (allowed: WEAK/MODERATE/HOLD)
            assert strength in ("WEAK", "MODERATE", "") or action == "HOLD", \
                f"auto_upgraded=false but strength={strength}, action={action}"
            # Only rule vote when not upgraded
            model_ids = {v.get("model_id") for v in d["votes"]}
            assert model_ids == {"rule"}, f"Expected only rule vote, got {model_ids}"

    def test_auto_upgrade_1day(self, session):
        r = _safe_get(session, f"{API}/analysis/ai",
                      params={"interval": "1day", "engine": "rule", "auto_upgrade": "true"},
                      timeout=AI_TIMEOUT)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert "auto_upgraded" in d
        # daily TF — ATR multiplier 2.0 verification on sl_method
        sl_method = d.get("sl_method") or ""
        if "ATR" in sl_method:
            assert ("× 2" in sl_method) or ("x 2" in sl_method.lower()), \
                f"Expected mult 2 for 1day, got: {sl_method!r}"

    def test_negative_path_weak_or_hold_no_upgrade(self, session):
        """If rule emits WEAK/HOLD, auto_upgraded must remain false and only rule vote present."""
        # Use a very fast TF that is often choppy → typically WEAK/HOLD
        r = _safe_get(session, f"{API}/analysis/ai",
                      params={"interval": "5min", "engine": "rule", "auto_upgrade": "true"},
                      timeout=AI_TIMEOUT)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        strength = (d.get("signal_strength") or "").upper()
        action = (d.get("action") or "").upper()
        if strength in ("WEAK", "MODERATE") or action == "HOLD":
            assert d["auto_upgraded"] is False, \
                f"auto_upgraded should be false for {strength}/{action}"
            model_ids = {v.get("model_id") for v in (d.get("votes") or [])}
            assert model_ids == {"rule"}, \
                f"Only rule vote expected on no-upgrade, got: {model_ids}"
        else:
            # The market happened to emit STRONG — skip negative assertion
            pytest.skip(f"5min emitted {strength}/{action}, cannot test negative path now")


# ===========================================================================
# Deep AI explicit engine
# ===========================================================================
class TestDeepAIEngine:
    def test_engine_ai_explicit(self, session):
        r = _safe_get(session, f"{API}/analysis/ai",
                      params={"interval": "1h", "engine": "ai"},
                      timeout=AI_TIMEOUT + 30)
        # Allow upstream LLM 502 if both models fail; main path should be 200
        assert r.status_code in (200, 502), r.text[:500]
        if r.status_code != 200:
            pytest.skip(f"Dual-LLM upstream failure: {r.text[:200]}")
        d = r.json()
        # auto_upgraded must be False on explicit Deep AI (only auto-upgrade path sets True)
        assert d.get("auto_upgraded") is False, "auto_upgraded should be False on engine=ai"
        # sl_method may be None or a string from LLM
        assert d.get("sl_method") is None or isinstance(d["sl_method"], str)
        votes = d.get("votes") or []
        model_ids = {v.get("model_id") for v in votes}
        # Must contain claude or gemini (or both)
        assert model_ids & {"claude", "gemini"}, f"Expected AI votes, got {model_ids}"


# ===========================================================================
# Cache key includes auto_upgrade flag
# ===========================================================================
class TestCachingPerAutoUpgradeFlag:
    def test_cache_consistency_and_separation(self, session):
        # First identical call
        r1 = _safe_get(session, f"{API}/analysis/ai",
                       params={"interval": "1h", "engine": "rule", "auto_upgrade": "true"},
                       timeout=AI_TIMEOUT)
        assert r1.status_code == 200, r1.text[:300]
        d1 = r1.json()

        t0 = time.time()
        r2 = session.get(f"{API}/analysis/ai",
                         params={"interval": "1h", "engine": "rule", "auto_upgrade": "true"},
                         timeout=10)
        elapsed = time.time() - t0
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["id"] == d1["id"], "Second identical call should be served from cache (same id)"
        assert elapsed < 3.0, f"Cache hit took {elapsed:.2f}s — too slow"

        # Different auto_upgrade flag — should be a SEPARATE cache key
        r3 = _safe_get(session, f"{API}/analysis/ai",
                       params={"interval": "1h", "engine": "rule", "auto_upgrade": "false"},
                       timeout=AI_TIMEOUT)
        assert r3.status_code == 200
        d3 = r3.json()
        # ids may differ (different code paths). If they happen to collide due to fast
        # consecutive write, we still check the auto_upgraded flag differs OR matches expected.
        assert d3.get("auto_upgraded") is False
        # If d1 was auto_upgraded=true, ids MUST differ
        if d1.get("auto_upgraded") is True:
            assert d3["id"] != d1["id"], \
                "Cache keys should separate auto_upgrade=true vs false"


# ===========================================================================
# Signals stats
# ===========================================================================
class TestSignalStats:
    def test_stats_schema(self, session):
        r = session.get(f"{API}/signals/stats", timeout=60)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        for k in ("overall", "by_timeframe", "period_7d", "period_30d", "best_streak"):
            assert k in d, f"missing top-level field {k}"

        def _check_tally(t, label):
            for k in ("total", "wins", "losses", "expired", "win_rate", "avg_r"):
                assert k in t, f"{label}: missing {k}"
                assert isinstance(t[k], (int, float)), \
                    f"{label}.{k} must be numeric, got {type(t[k])}"

        _check_tally(d["overall"], "overall")
        _check_tally(d["period_7d"], "period_7d")
        _check_tally(d["period_30d"], "period_30d")
        assert isinstance(d["by_timeframe"], list)
        for row in d["by_timeframe"]:
            assert "timeframe" in row
            _check_tally(row, f"by_timeframe[{row.get('timeframe')}]")
        assert isinstance(d["best_streak"], int)


# ===========================================================================
# Smoke checks on other endpoints
# ===========================================================================
class TestSmoke:
    def test_quote(self, session):
        r = _safe_get(session, f"{API}/market/quote")
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["price"] > 0

    def test_candles(self, session):
        r = _safe_get(session, f"{API}/market/candles",
                      params={"interval": "15min", "size": 50})
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["interval"] == "15min"
        assert len(d["candles"]) >= 30

    def test_news(self, session):
        r = _safe_get(session, f"{API}/news", params={"limit": 5})
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert "items" in d
        assert isinstance(d["items"], list)

    def test_ea_download(self, session):
        r = session.get(f"{API}/ea/download", timeout=20)
        assert r.status_code == 200, r.text[:200]
        # Should be a file payload
        assert len(r.content) > 100, "EA file too small"
        ctype = r.headers.get("content-type", "")
        assert "octet-stream" in ctype or "application/" in ctype, f"unexpected ctype: {ctype}"

    def test_ea_signal(self, session):
        r = session.get(f"{API}/ea/signal", params={"interval": "1h"}, timeout=20)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert "has_signal" in d
        assert isinstance(d["has_signal"], bool)
