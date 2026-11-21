# Iteration 2: Risk Guard (settings/position-size/status/EA lock), macro calendar + yields, rule engine macro_context
import os
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
DEFAULTS = {"enabled": True, "account_balance": 10000.0, "risk_pct": 1.0, "max_daily_losses": 1, "max_daily_loss_pct": 2.0}


def _mongo():
    env = {}
    with open("/app/backend/.env") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                env[k] = v.strip('"')
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    db = _mongo()
    had_doc = db.risk_settings.find_one({"_id": "default"})
    yield
    db.ea_events.delete_many({"signal_id": {"$regex": "^qa-"}})
    if had_doc:
        db.risk_settings.replace_one({"_id": "default"}, had_doc)
    else:
        db.risk_settings.delete_one({"_id": "default"})


# --- Macro calendar + yields
class TestMacro:
    def test_macro_shape(self, s):
        r = s.get(f"{BASE_URL}/api/calendar/macro", timeout=60)
        assert r.status_code == 200
        d = r.json()
        for k in ("events", "gold_bias", "event_risk", "surprises", "actuals", "yields", "fred_enabled"):
            assert k in d, f"missing {k}: {list(d.keys())}"
        assert isinstance(d["events"], list)
        assert isinstance(d["surprises"], list)
        assert d["actuals"] in ({}, None) or isinstance(d["actuals"], dict)
        assert not d["actuals"]
        assert d["fred_enabled"] is False
        y = d["yields"]
        assert y, "yields null (Yahoo ^TNX failed)"
        for k in ("nominal_10y", "nominal_10y_change_bp", "nominal_10y_5d_change_bp", "gold_bias"):
            assert k in y
        assert 0 < y["nominal_10y"] < 15
        assert y["gold_bias"] in ("BULLISH", "BEARISH", "NEUTRAL")
        assert "real_10y" not in y

    def test_rule_engine_macro_context(self, s):
        r = s.get(f"{BASE_URL}/api/analysis/ai", params={"engine": "rule"}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        mc = d.get("macro_context")
        assert mc, f"no macro_context; keys={list(d.keys())}"
        assert mc.get("yields") and "nominal_10y" in mc["yields"]
        print("ACTION", d.get("action"), "REASONING", d.get("reasoning"))


# --- Risk settings CRUD + validation
class TestRiskSettings:
    def test_defaults(self, s):
        _mongo().risk_settings.delete_one({"_id": "default"})
        d = s.get(f"{BASE_URL}/api/risk/settings").json()
        assert d == DEFAULTS

    def test_put_and_persist(self, s):
        body = {**DEFAULTS, "account_balance": 20000, "risk_pct": 0.5}
        r = s.put(f"{BASE_URL}/api/risk/settings", json=body)
        assert r.status_code == 200
        assert r.json()["account_balance"] == 20000
        g = s.get(f"{BASE_URL}/api/risk/settings").json()
        assert g["account_balance"] == 20000 and g["risk_pct"] == 0.5
        s.put(f"{BASE_URL}/api/risk/settings", json=DEFAULTS)

    @pytest.mark.parametrize("bad", [{"risk_pct": 11}, {"account_balance": 0}, {"account_balance": -5},
                                     {"max_daily_losses": 0}, {"max_daily_loss_pct": 0}, {"risk_pct": 0}])
    def test_validation(self, s, bad):
        r = s.put(f"{BASE_URL}/api/risk/settings", json={**DEFAULTS, **bad})
        assert r.status_code == 422

    def test_position_size(self, s):
        s.put(f"{BASE_URL}/api/risk/settings", json=DEFAULTS)
        d = s.get(f"{BASE_URL}/api/risk/position-size", params={"entry": 3530, "stop_loss": 3520}).json()
        assert d["lot"] == 0.1 and d["risk_usd"] == 100 and d["sl_distance"] == 10

    def test_position_size_invalid(self, s):
        assert s.get(f"{BASE_URL}/api/risk/position-size", params={"entry": 0, "stop_loss": 3520}).status_code == 422
        d = s.get(f"{BASE_URL}/api/risk/position-size", params={"entry": 3530, "stop_loss": 3530}).json()
        assert d["lot"] == 0.0


# --- Risk status + EA lock
class TestRiskLock:
    def test_unlocked_initially(self, s):
        d = s.get(f"{BASE_URL}/api/risk/status").json()
        print("INITIAL STATUS", d)
        for k in ("locked", "reason", "source", "trades_today", "losses_today", "pnl_today", "pnl_pct_today", "settings"):
            assert k in d

    def test_count_lock(self, s):
        s.put(f"{BASE_URL}/api/risk/settings", json=DEFAULTS)
        r = s.post(f"{BASE_URL}/api/ea/event", json={"event": "CLOSED", "signal_id": "qa-lock", "action": "BUY", "profit": -150})
        assert r.status_code == 200
        d = s.get(f"{BASE_URL}/api/risk/status").json()
        assert d["locked"] is True and d["source"] == "ea" and d["reason"]
        assert d["losses_today"] == 1 and d["pnl_today"] == -150
        e = s.get(f"{BASE_URL}/api/ea/signal").json()
        assert e == {"has_signal": False, "locked": True, "reason": d["reason"]}

    def test_disabled_unlocks(self, s):
        s.put(f"{BASE_URL}/api/risk/settings", json={**DEFAULTS, "enabled": False})
        d = s.get(f"{BASE_URL}/api/risk/status").json()
        assert d["locked"] is False and d["reason"] is None
        assert s.get(f"{BASE_URL}/api/ea/signal").json().get("locked") is not True

    def test_pct_lock(self, s):
        _mongo().ea_events.delete_many({"signal_id": {"$regex": "^qa-"}})
        s.put(f"{BASE_URL}/api/risk/settings", json={**DEFAULTS, "max_daily_losses": 5})
        s.post(f"{BASE_URL}/api/ea/event", json={"event": "CLOSED", "signal_id": "qa-pct", "action": "SELL", "profit": -250})
        d = s.get(f"{BASE_URL}/api/risk/status").json()
        assert d["locked"] is True, d
        assert "-2.50" in d["reason"] or "2.50%" in d["reason"], d["reason"]
        assert d["pnl_pct_today"] == -2.5
