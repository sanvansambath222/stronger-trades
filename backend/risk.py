from datetime import datetime, timezone
from typing import Dict, List
from pydantic import BaseModel, Field

XAU_CONTRACT_OZ = 100  # 1 standard lot = 100 oz → $1 move = $100 per lot


class RiskSettings(BaseModel):
    enabled: bool = True
    account_balance: float = Field(10000.0, gt=0)
    risk_pct: float = Field(1.0, gt=0, le=10)
    max_daily_losses: int = Field(1, ge=1, le=20)
    max_daily_loss_pct: float = Field(2.0, gt=0, le=50)


def today_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def position_size(settings: RiskSettings, entry: float, stop_loss: float) -> Dict:
    risk_usd = settings.account_balance * settings.risk_pct / 100
    dist = abs(entry - stop_loss)
    lot = round(risk_usd / (dist * XAU_CONTRACT_OZ), 2) if dist > 0 else 0.0
    return {"risk_usd": round(risk_usd, 2), "sl_distance": round(dist, 2), "lot": lot, "risk_pct": settings.risk_pct}


def compute_status(settings: RiskSettings, ea_closed: List[dict], graded_today: List[dict]) -> Dict:
    """Real EA closes take priority; otherwise use auto-graded signals (R-multiple × risk %)."""
    if ea_closed:
        source = "ea"
        trades = len(ea_closed)
        losses = sum(1 for e in ea_closed if (e.get("profit") or 0) < 0)
        pnl = round(sum(e.get("profit") or 0 for e in ea_closed), 2)
        pnl_pct = round(pnl / settings.account_balance * 100, 2)
    else:
        source = "signals"
        trades = len(graded_today)
        losses = sum(1 for s in graded_today if (s.get("r_multiple") or 0) < 0)
        pnl_pct = round(sum(s.get("r_multiple") or 0 for s in graded_today) * settings.risk_pct, 2)
        pnl = round(pnl_pct * settings.account_balance / 100, 2)

    reason = None
    if losses >= settings.max_daily_losses:
        reason = f"{losses} loss{'es' if losses != 1 else ''} today (limit {settings.max_daily_losses})"
    elif pnl_pct <= -settings.max_daily_loss_pct:
        reason = f"Down {pnl_pct:.2f}% today (limit −{settings.max_daily_loss_pct}%)"
    locked = bool(settings.enabled and reason)
    return {
        "locked": locked,
        "reason": reason if locked else None,
        "source": source,
        "trades_today": trades,
        "losses_today": losses,
        "pnl_today": pnl,
        "pnl_pct_today": pnl_pct,
        "resets_at": (today_start_utc().timestamp() + 86400),
        "settings": settings.model_dump(),
    }
