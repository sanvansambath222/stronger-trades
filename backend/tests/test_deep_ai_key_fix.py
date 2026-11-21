# Regression for "All selected AI models failed to respond" (USER_EMERGENT_LLM_KEY fix) - Deep AI ensemble + live progress
# NOTE: makes real LLM calls (costs credits). Run sparingly.
import os
import json
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
INTERVAL = os.environ.get('DEEP_AI_TEST_INTERVAL', '15min')
RUN_ID = f"TEST_{uuid.uuid4().hex[:10]}"
_state = {}


def _get_signal():
    if "sig" not in _state:
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/analysis/ai",
                         params={"interval": INTERVAL, "engine": "ai", "run_id": RUN_ID}, timeout=200)
        _state["elapsed"] = time.time() - t0
        _state["status"] = r.status_code
        _state["raw"] = r.text
        _state["sig"] = json.loads(r.text)  # leading whitespace heartbeats must be valid JSON prefix
    return _state["sig"]


class TestDeepAIEnsemble:
    def test_ai_settings_default_ensemble(self):
        r = requests.get(f"{BASE_URL}/api/ai/settings", timeout=20)
        assert r.status_code == 200
        assert len(r.json()["ensemble"]) >= 1

    def test_signal_returns_votes(self):
        sig = _get_signal()
        print(f"elapsed={_state['elapsed']:.1f}s status={_state['status']} leading_ws={len(_state['raw']) - len(_state['raw'].lstrip())}")
        assert _state["status"] == 200
        assert "detail" not in sig, sig.get("detail")
        assert sig.get("action") in ("BUY", "SELL", "HOLD")
        votes = sig.get("votes") or []
        assert votes, f"no votes in signal; keys={list(sig.keys())}"
        ok = [v for v in votes if v.get("available")]
        print("votes:", [(v["model_id"], v["action"], v["confidence"], v["available"]) for v in votes])
        print("consensus:", sig.get("consensus"), "models_used:", sig.get("models_used"))
        assert len(ok) >= 2, "fewer than 2 models answered"
        assert sig.get("consensus") in ("UNANIMOUS", "MAJORITY", "CONFLICTED", "SINGLE_SOURCE")
        assert isinstance(sig.get("models_used"), list) and len(sig["models_used"]) > 1

    def test_progress_lists_votes(self):
        _get_signal()
        r = requests.get(f"{BASE_URL}/api/ai/progress/{RUN_ID}", timeout=20)
        assert r.status_code == 200
        items = r.json()["items"]
        print("progress items:", [(i.get("kind"), i.get("model_id"), i.get("available")) for i in items])
        votes = [i for i in items if i.get("kind") == "vote"]
        assert len(votes) == len(_get_signal()["votes"])

    def test_progress_unknown_run_empty(self):
        r = requests.get(f"{BASE_URL}/api/ai/progress/TEST_nonexistent_run", timeout=20)
        assert r.status_code == 200 and r.json()["items"] == []
