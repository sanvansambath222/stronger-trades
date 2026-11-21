# Tests for AI model roster/settings, macro calendar, rule signal macro context, stats by model, progress
import os
import json
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
BALANCED = None


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture(scope="module", autouse=True)
def restore_balanced(s):
    yield
    cat = s.get(f"{API}/ai/models").json()
    p = cat["presets"]["balanced"]
    s.put(f"{API}/ai/settings", json={"ensemble": p["ensemble"], "roles": p["roles"], "preset": "balanced"})


# --- AI model catalog ---
class TestCatalog:
    def test_models_catalog(self, s):
        r = s.get(f"{API}/ai/models")
        assert r.status_code == 200
        d = r.json()
        ids = [m["id"] for m in d["models"]]
        assert ids == ["opus", "sonnet", "haiku", "gpt55", "gpt6luna"]
        assert len(d["roles"]) == 7
        assert {x["id"] for x in d["roles"]} == {"bull", "bear", "trader", "aggressive", "neutral", "conservative", "manager"}
        assert set(d["presets"].keys()) == {"max", "balanced", "budget"}
        assert all(v == "opus" for v in d["presets"]["max"]["roles"].values())


# --- AI settings persistence & validation ---
class TestSettings:
    def test_default_or_balanced(self, s):
        # reset to balanced first then GET
        cat = s.get(f"{API}/ai/models").json()
        p = cat["presets"]["balanced"]
        r = s.put(f"{API}/ai/settings", json={"ensemble": p["ensemble"], "roles": p["roles"], "preset": "balanced"})
        assert r.status_code == 200
        g = s.get(f"{API}/ai/settings").json()
        assert g["ensemble"] == ["opus", "sonnet", "gpt55"]
        assert g["roles"]["trader"] == "opus" and g["roles"]["conservative"] == "haiku"

    def test_put_persists(self, s):
        payload = {"ensemble": ["haiku", "gpt6luna"], "roles": {"bull": "haiku", "bear": "gpt6luna", "trader": "sonnet",
                   "aggressive": "gpt6luna", "neutral": "haiku", "conservative": "haiku", "manager": "sonnet"}, "preset": None}
        r = s.put(f"{API}/ai/settings", json=payload)
        assert r.status_code == 200
        g = s.get(f"{API}/ai/settings").json()
        assert g["ensemble"] == ["haiku", "gpt6luna"]
        assert g["roles"]["trader"] == "sonnet"
        assert g["preset"] is None

    def test_invalid_ids_filtered(self, s):
        r = s.put(f"{API}/ai/settings", json={"ensemble": ["bogus", "opus", "opus"], "roles": {"bull": "nope"}})
        assert r.status_code == 200
        d = r.json()
        assert d["ensemble"] == ["opus"]
        assert d["roles"]["bull"] == "sonnet"  # balanced default
        assert len(d["roles"]) == 7

    def test_empty_ensemble_422(self, s):
        r = s.put(f"{API}/ai/settings", json={"ensemble": [], "roles": {}})
        assert r.status_code == 422
        r2 = s.put(f"{API}/ai/settings", json={"ensemble": ["xx"], "roles": {}})
        assert r2.status_code == 422


# --- Macro calendar & rule signal ---
class TestMacroAndRule:
    def test_calendar_macro(self, s):
        r = s.get(f"{API}/calendar/macro")
        assert r.status_code == 200
        d = r.json()
        for k in ("events", "gold_bias", "event_risk", "bias_score"):
            assert k in d
        assert d["gold_bias"] in ("BULLISH", "BEARISH", "NEUTRAL")
        assert d["event_risk"] in ("LOW", "ELEVATED", "HIGH")
        print("macro:", json.dumps(d)[:600])

    def test_rule_signal(self, s):
        r = s.get(f"{API}/analysis/ai", params={"engine": "rule", "interval": "1h"}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["models_used"] == ["rule"]
        mc = d["macro_context"]
        assert mc is not None
        for k in ("events", "gold_bias", "event_risk", "bias_score"):
            assert k in mc
        assert d["action"] in ("BUY", "SELL", "HOLD")


# --- Stats by model & progress ---
class TestStatsProgress:
    def test_stats_model(self, s):
        r = s.get(f"{API}/signals/stats", params={"model": "opus"}, timeout=90)
        assert r.status_code == 200
        d = r.json()
        assert d["model_filter"] == "opus"
        assert isinstance(d["by_model"], list)
        assert "overall" in d

    def test_stats_no_filter(self, s):
        r = s.get(f"{API}/signals/stats", timeout=90)
        assert r.status_code == 200
        assert r.json()["model_filter"] is None

    def test_progress_unknown(self, s):
        r = s.get(f"{API}/ai/progress/{uuid.uuid4()}")
        assert r.status_code == 200
        assert r.json() == {"items": []}

    def test_history_has_models_used(self, s):
        r = s.get(f"{API}/signals/history", params={"limit": 5})
        assert r.status_code == 200
        sig = r.json()["signals"]
        assert len(sig) > 0
        assert "models_used" in sig[0]


# --- Deep AI with inactive LLM key -> graceful error + progress ---
class TestDeepAIFailure:
    def test_engine_ai_fails_gracefully(self, s):
        # use unique settings so cache is not hit
        cat = s.get(f"{API}/ai/models").json()
        p = cat["presets"]["balanced"]
        s.put(f"{API}/ai/settings", json={"ensemble": p["ensemble"], "roles": p["roles"], "preset": "balanced"})
        run_id = f"TEST_{uuid.uuid4().hex[:8]}"
        t0 = time.time()
        r = s.get(f"{API}/analysis/ai", params={"engine": "ai", "interval": "1h", "run_id": run_id}, timeout=200)
        elapsed = time.time() - t0
        assert r.status_code == 200
        body = json.loads(r.text.strip())
        print("elapsed", elapsed, "body", str(body)[:300])
        if "detail" in body:
            assert body["detail"] == "All selected AI models failed to respond"
            prog = s.get(f"{API}/ai/progress/{run_id}").json()["items"]
            print("progress", prog)
            votes = [i for i in prog if i["kind"] == "vote"]
            assert len(votes) == 3
            assert all(v["available"] is False for v in votes)
            assert {v["model_id"] for v in votes} == {"opus", "sonnet", "gpt55"}
        else:
            # LLM came back alive
            assert body.get("models_used")
