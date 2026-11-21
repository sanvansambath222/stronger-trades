"""Backend API tests for XAU/USD Trading Analytics."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://precious-trade-12.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# --- Health ---
class TestHealth:
    def test_root(self, session):
        r = session.get(f"{API}/")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "ok"


# --- Market quote ---
class TestMarketQuote:
    def test_quote_fields(self, session):
        r = session.get(f"{API}/market/quote", timeout=20)
        assert r.status_code == 200, f"body={r.text[:300]}"
        d = r.json()
        for k in ["symbol", "price", "change", "percent_change", "high", "low", "open", "previous_close", "timestamp"]:
            assert k in d, f"missing {k}"
        assert isinstance(d["price"], (int, float))
        assert d["price"] > 0
        assert d["high"] >= d["low"]


# --- Candles ---
class TestCandles:
    def test_candles_default(self, session):
        r = session.get(f"{API}/market/candles", params={"interval": "1h", "size": 120}, timeout=20)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["interval"] == "1h"
        assert "candles" in d
        candles = d["candles"]
        assert len(candles) >= 50, f"only {len(candles)} candles returned"
        # chronological - times ascending
        times = [c["time"] for c in candles]
        assert times == sorted(times), "candles not chronological"
        # OHLC sanity
        c = candles[-1]
        for k in ["open", "high", "low", "close", "time"]:
            assert k in c
        assert c["high"] >= c["low"]

    def test_candles_size_validation(self, session):
        r = session.get(f"{API}/market/candles", params={"interval": "1h", "size": 10}, timeout=20)
        assert r.status_code == 422  # below ge=20


# --- Indicators ---
class TestIndicators:
    def test_indicators_fields(self, session):
        r = session.get(f"{API}/analysis/indicators", params={"interval": "1h"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        for k in ["rsi", "macd", "macd_signal", "ema20", "ema50", "ema200", "bb_upper", "bb_mid", "bb_lower", "price"]:
            assert k in d, f"missing {k}"
        assert d["price"] > 0
        if d["rsi"] is not None:
            assert 0 <= d["rsi"] <= 100
        if d["bb_upper"] is not None and d["bb_lower"] is not None:
            assert d["bb_upper"] >= d["bb_lower"]


# --- AI Signal ---
class TestAISignal:
    def test_ai_signal(self, session):
        r = session.get(f"{API}/analysis/ai", params={"interval": "1h"}, timeout=60)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        for k in ["id", "action", "confidence", "entry", "stop_loss", "take_profit", "timeframe",
                  "reasoning", "summary", "sentiment", "indicators", "created_at"]:
            assert k in d, f"missing {k}"
        assert d["action"] in ["BUY", "SELL", "HOLD"]
        assert 0 <= d["confidence"] <= 100
        assert d["sentiment"] in ["BULLISH", "BEARISH", "NEUTRAL"]
        assert d["timeframe"] == "1h"
        assert isinstance(d["reasoning"], str) and len(d["reasoning"]) > 10
        assert isinstance(d["summary"], str) and len(d["summary"]) > 0
        assert d["entry"] > 0 and d["stop_loss"] > 0 and d["take_profit"] > 0

    def test_signal_persisted_in_history(self, session):
        # Ensure at least one signal exists
        session.get(f"{API}/analysis/ai", params={"interval": "1h"}, timeout=60)
        time.sleep(1)
        r = session.get(f"{API}/signals/history", params={"limit": 10}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "signals" in d
        assert isinstance(d["signals"], list)
        assert len(d["signals"]) >= 1, "no signals persisted"
        s0 = d["signals"][0]
        for k in ["action", "confidence", "entry", "created_at"]:
            assert k in s0
        # ensure no mongodb _id leaked
        assert "_id" not in s0
        # sorted desc by created_at
        if len(d["signals"]) >= 2:
            assert d["signals"][0]["created_at"] >= d["signals"][1]["created_at"]


# --- News ---
class TestNews:
    def test_news(self, session):
        r = session.get(f"{API}/news", params={"limit": 8}, timeout=20)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert "items" in d
        assert isinstance(d["items"], list)
        # likely populated (may be empty if google blocks)
        if d["items"]:
            it = d["items"][0]
            for k in ["title", "link", "published"]:
                assert k in it
            assert it["title"] and it["link"]
