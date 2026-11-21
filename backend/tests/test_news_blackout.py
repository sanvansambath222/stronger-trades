"""Backend tests for the News-Blackout filter feature.

Covers:
- /api/calendar/events (structure, filters)
- /api/calendar/blackout (structure, next_event.minutes_until)
- /api/analysis/ai news_blackout payload (off vs on)
- Cache key separation by nb/bw flags
- AISignal serialization with news_blackout field
- Override path (best-effort: depends on a real event being within the window)
- Existing endpoint regression: market/quote, candles, indicators, signals/history,
  signals/stats, news, ea/signal, ea/download
"""
import os
import time
from datetime import datetime, timezone, timedelta

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "https://precious-trade-12.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

# -------------------- session fixture --------------------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _safe_get(session, url, params=None, timeout=60, retries=1):
    """GET with one retry on 429/5xx to absorb TwelveData rate-limit blips."""
    last = None
    for attempt in range(retries + 1):
        last = session.get(url, params=params, timeout=timeout)
        if last.status_code in (429,) or last.status_code >= 500:
            time.sleep(40)
            continue
        return last
    return last


# -------------------- /api/calendar/events --------------------
class TestCalendarEvents:
    def test_events_structure(self, session):
        r = session.get(f"{API}/calendar/events", timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("source") == "ForexFactory"
        assert "items" in d and isinstance(d["items"], list)
        # ForexFactory weekly feed can be sparse on weekends. We don't enforce a count
        # but we DO require that when items exist, each item has the documented shape.
        for it in d["items"][:10]:
            for k in ["title", "country", "impact", "forecast", "previous", "url",
                      "time_et", "date_et", "when_utc", "scheduled"]:
                assert k in it, f"missing field: {k}"
            assert it["impact"] in ("Low", "Medium", "High", "Holiday", "")
            assert isinstance(it["scheduled"], bool)
            if it["scheduled"]:
                assert isinstance(it["when_utc"], str)
                # Must parse as ISO datetime
                dt = datetime.fromisoformat(it["when_utc"])
                assert dt.tzinfo is not None
            else:
                # when_utc should be None for non-scheduled (All Day / Tentative)
                assert it["when_utc"] is None

    def test_events_filters(self, session):
        r = session.get(f"{API}/calendar/events",
                        params={"country": "USD", "impact": "High", "limit": 5},
                        timeout=30)
        assert r.status_code == 200, r.text[:300]
        items = r.json().get("items", [])
        assert len(items) <= 5
        for it in items:
            assert it["country"] == "USD"
            assert it["impact"] == "High"

    def test_events_only_scheduled(self, session):
        r = session.get(f"{API}/calendar/events",
                        params={"only_scheduled": "true", "limit": 25},
                        timeout=30)
        assert r.status_code == 200, r.text[:300]
        items = r.json().get("items", [])
        for it in items:
            assert it["scheduled"] is True
            assert isinstance(it["when_utc"], str)
            # ISO datetime parseable
            datetime.fromisoformat(it["when_utc"])


# -------------------- /api/calendar/blackout --------------------
class TestBlackoutEndpoint:
    def test_blackout_default(self, session):
        r = session.get(f"{API}/calendar/blackout",
                        params={"window_minutes": 15}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        for k in ["in_blackout", "window_minutes", "current_event", "next_event", "now_utc"]:
            assert k in d, f"missing {k}"
        assert isinstance(d["in_blackout"], bool)
        assert d["window_minutes"] == 15
        # now_utc is ISO datetime
        datetime.fromisoformat(d["now_utc"])
        if d["next_event"] is not None:
            assert "minutes_until" in d["next_event"]
            assert isinstance(d["next_event"]["minutes_until"], (int, float))
            assert d["next_event"]["minutes_until"] > 0
            assert d["next_event"]["country"] == "USD"  # gold-sensitive only
            assert d["next_event"]["scheduled"] is True

    def test_blackout_window_validation(self, session):
        # le=120 enforced
        r = session.get(f"{API}/calendar/blackout",
                        params={"window_minutes": 9999}, timeout=10)
        assert r.status_code == 422


# -------------------- /api/analysis/ai news_blackout payload --------------------
class TestAISignalBlackoutPayload:
    def test_filter_off(self, session):
        r = _safe_get(session, f"{API}/analysis/ai",
                      params={"interval": "1h", "engine": "rule",
                              "news_blackout": "false"}, timeout=90)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        nb = d.get("news_blackout")
        assert isinstance(nb, dict), f"news_blackout not dict: {nb}"
        assert nb.get("filter_enabled") is False
        assert nb.get("in_blackout") is False
        # filter off should NOT have overridden_from
        assert "overridden_from" not in nb
        assert d["action"] in ("BUY", "SELL", "HOLD")
        # summary should NOT start with BLACKOUT
        assert not d["summary"].startswith("BLACKOUT")

    def test_filter_on_no_event(self, session):
        # window=15 min — almost never inside blackout on a normal day.
        r = _safe_get(session, f"{API}/analysis/ai",
                      params={"interval": "1h", "engine": "rule",
                              "news_blackout": "true", "blackout_window": 15},
                      timeout=90)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        nb = d.get("news_blackout")
        assert isinstance(nb, dict)
        assert nb.get("filter_enabled") is True
        assert "in_blackout" in nb
        # If we *are* in a blackout, the override should have kicked in — but only when
        # rule originally returned BUY/SELL. We don't force the assertion here because
        # market state is non-deterministic. We DO sanity-check structural fields.
        assert "window_minutes" in nb
        assert nb["window_minutes"] == 15
        if nb.get("in_blackout") and "overridden_from" in nb:
            assert nb["overridden_from"] in ("BUY", "SELL")
            assert d["action"] == "HOLD"
            assert d["summary"].startswith("BLACKOUT")

    def test_filter_on_max_window_override_path(self, session):
        """Use the maximum allowed window (120 min) to try to catch an event.

        NOTE: blackout_window is constrained to le=120 in the backend.
        The override path is therefore only reachable when a USD high-impact
        event is within ±120min of 'now'. We do a best-effort check: query
        the calendar to see what to expect, then assert the contract matches.
        """
        # Probe blackout state at max allowed window first
        bb = session.get(f"{API}/calendar/blackout",
                         params={"window_minutes": 120}, timeout=20).json()
        in_window = bool(bb.get("in_blackout"))

        r = _safe_get(session, f"{API}/analysis/ai",
                      params={"interval": "1h", "engine": "rule",
                              "news_blackout": "true", "blackout_window": 120},
                      timeout=90)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        nb = d["news_blackout"]
        assert nb["filter_enabled"] is True
        assert nb.get("window_minutes") == 120
        if in_window:
            # next_event populated when filter on and event upcoming
            assert nb.get("current_event") is not None
            # If underlying rule was BUY/SELL, override should have applied
            if "overridden_from" in nb:
                assert nb["overridden_from"] in ("BUY", "SELL")
                assert d["action"] == "HOLD"
                assert d["summary"].startswith("BLACKOUT")
                assert nb["current_event"].get("title")
                assert "minutes_until" in nb["current_event"]
        else:
            pytest.skip(f"No USD high-impact event within ±120min "
                        f"(next_event={bb.get('next_event', {}).get('minutes_until')} min away); "
                        f"override path not exercisable through public API.")


# -------------------- Cache separation --------------------
class TestCacheSeparation:
    def test_cache_keys_independent_by_nb_flag(self, session):
        """nb<0|1> in cache key → off and on must return independent payloads."""
        # Warm cache for OFF
        r_off = _safe_get(session, f"{API}/analysis/ai",
                          params={"interval": "1h", "engine": "rule",
                                  "news_blackout": "false"}, timeout=90)
        assert r_off.status_code == 200
        off = r_off.json()
        assert off["news_blackout"]["filter_enabled"] is False

        # Now request ON — should NOT serve the OFF-cached payload
        r_on = _safe_get(session, f"{API}/analysis/ai",
                         params={"interval": "1h", "engine": "rule",
                                 "news_blackout": "true", "blackout_window": 15},
                         timeout=90)
        assert r_on.status_code == 200
        on = r_on.json()
        assert on["news_blackout"]["filter_enabled"] is True
        # Different IDs guarantee they were NOT served from the same cache slot
        assert off["id"] != on["id"], "OFF/ON share cache — bleed-through!"

    def test_cache_keys_independent_by_bw_value(self, session):
        """Same news_blackout=true but different blackout_window must be cached separately."""
        r1 = _safe_get(session, f"{API}/analysis/ai",
                       params={"interval": "1h", "engine": "rule",
                               "news_blackout": "true", "blackout_window": 15},
                       timeout=90)
        r2 = _safe_get(session, f"{API}/analysis/ai",
                       params={"interval": "1h", "engine": "rule",
                               "news_blackout": "true", "blackout_window": 60},
                       timeout=90)
        assert r1.status_code == 200 and r2.status_code == 200
        d1, d2 = r1.json(), r2.json()
        assert d1["news_blackout"]["window_minutes"] == 15
        assert d2["news_blackout"]["window_minutes"] == 60
        assert d1["id"] != d2["id"], "bw=15 and bw=60 share cache!"


# -------------------- AISignal model serialization --------------------
class TestAISignalSerialization:
    def test_news_blackout_field_present_in_model(self, session):
        """AISignal must accept Optional[Dict[str, Any]] for news_blackout without 500."""
        for nb_flag in ("false", "true"):
            r = _safe_get(session, f"{API}/analysis/ai",
                          params={"interval": "1h", "engine": "rule",
                                  "news_blackout": nb_flag}, timeout=90)
            assert r.status_code == 200, f"nb={nb_flag} -> {r.status_code} {r.text[:300]}"
            d = r.json()
            assert "news_blackout" in d
            assert isinstance(d["news_blackout"], dict)


# -------------------- Existing endpoint regression --------------------
class TestRegression:
    def test_market_quote(self, session):
        r = _safe_get(session, f"{API}/market/quote", timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["price"] > 0 and "symbol" in d

    def test_candles(self, session):
        r = _safe_get(session, f"{API}/market/candles",
                      params={"interval": "1h", "size": 50}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["interval"] == "1h"
        assert len(d["candles"]) >= 50

    def test_indicators(self, session):
        r = _safe_get(session, f"{API}/analysis/indicators",
                      params={"interval": "1h"}, timeout=30)
        assert r.status_code == 200, r.text[:300]

    def test_signals_history(self, session):
        r = session.get(f"{API}/signals/history", params={"limit": 5}, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "signals" in d and isinstance(d["signals"], list)
        for s in d["signals"]:
            assert "_id" not in s

    def test_signals_stats(self, session):
        r = session.get(f"{API}/signals/stats", timeout=20)
        assert r.status_code == 200
        d = r.json()
        for k in ["overall", "by_timeframe", "period_7d", "period_30d", "best_streak"]:
            assert k in d

    def test_news(self, session):
        r = session.get(f"{API}/news", params={"limit": 5}, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and isinstance(d["items"], list)

    def test_ea_signal(self, session):
        r = session.get(f"{API}/ea/signal", timeout=30)
        assert r.status_code == 200
        # response can vary — just check it's JSON
        assert isinstance(r.json(), dict)

    def test_ea_download(self, session):
        r = session.get(f"{API}/ea/download", timeout=30, allow_redirects=True)
        # Either streams a file or returns plain text — anything non-5xx is fine
        assert r.status_code in (200, 302, 307), r.text[:200]
