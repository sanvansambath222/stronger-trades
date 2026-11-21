import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Releases where a HIGHER print is USD-bullish (gold-bearish)
USD_UP_KEYWORDS = [
    "cpi", "ppi", "pce", "inflation", "non-farm", "nonfarm", "payroll", "average hourly earnings",
    "retail sales", "gdp", "ism", "pmi", "adp", "jolts", "consumer confidence", "durable goods",
    "federal funds rate", "interest rate", "consumer sentiment", "industrial production",
]
# Releases where a HIGHER print is USD-bearish (gold-bullish)
USD_DOWN_KEYWORDS = ["unemployment rate", "unemployment claims", "jobless claims", "continuing claims"]

_NUM_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*([kmbt%]?)", re.IGNORECASE)
_SCALE = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


def _num(text: str) -> Optional[float]:
    m = _NUM_RE.search(text or "")
    if not m:
        return None
    return float(m.group(1)) * _SCALE.get(m.group(2).lower(), 1)


def _polarity(title: str) -> int:
    t = (title or "").lower()
    if any(k in t for k in USD_DOWN_KEYWORDS):
        return -1
    if any(k in t for k in USD_UP_KEYWORDS):
        return 1
    return 0


def analyze_macro(events: List[dict], now: datetime, is_sensitive) -> Dict:
    """Score gold-sensitive USD releases (CPI, NFP, FOMC…) in the -24h..+48h window by forecast vs previous."""
    window = []
    for e in events:
        if not e.get("scheduled") or not is_sensitive(e):
            continue
        try:
            when = datetime.fromisoformat(e["when_utc"])
        except (TypeError, ValueError):
            continue
        if not (now - timedelta(hours=24) <= when <= now + timedelta(hours=48)):
            continue
        fc, pv = _num(e.get("forecast", "")), _num(e.get("previous", ""))
        pol = _polarity(e.get("title", ""))
        weight = 1.0 if e.get("impact") == "High" else 0.5
        gold_bias = "NEUTRAL"
        score = 0.0
        if pol and fc is not None and pv is not None and fc != pv:
            usd_dir = (1 if fc > pv else -1) * pol
            score = -usd_dir * weight
            gold_bias = "BULLISH" if score > 0 else "BEARISH"
        mins = round((when - now).total_seconds() / 60.0, 1)
        window.append({
            "title": e.get("title"), "impact": e.get("impact"), "country": e.get("country"),
            "forecast": e.get("forecast") or "", "previous": e.get("previous") or "",
            "when_utc": e["when_utc"], "minutes_until": mins, "released": mins < 0,
            "gold_bias": gold_bias, "score": score,
        })
    window.sort(key=lambda x: x["when_utc"])

    total = sum(x["score"] for x in window)
    upcoming = [x for x in window if not x["released"] and x["impact"] == "High"]
    nearest = upcoming[0]["minutes_until"] if upcoming else None
    event_risk = "HIGH" if nearest is not None and nearest <= 240 else "ELEVATED" if nearest is not None and nearest <= 1440 else "LOW"
    bias = "BULLISH" if total >= 0.75 else "BEARISH" if total <= -0.75 else "NEUTRAL"
    return {
        "events": window[:10],
        "bias_score": round(total, 2),
        "gold_bias": bias,
        "event_risk": event_risk,
        "next_high_impact": upcoming[0] if upcoming else None,
    }


def macro_prompt_block(macro: Optional[Dict]) -> str:
    if not macro or not macro.get("events"):
        return "No high-impact USD releases (CPI, NFP, FOMC, PCE…) in the last 24h / next 48h."
    lines = []
    for x in macro["events"]:
        when = f"released {abs(x['minutes_until']) / 60:.1f}h ago" if x["released"] else f"in {x['minutes_until'] / 60:.1f}h"
        lines.append(
            f"  - [{x['impact']}] {x['country']} {x['title']} · {when} · forecast {x['forecast'] or 'n/a'} vs previous {x['previous'] or 'n/a'}"
            f" → expectation implies gold {x['gold_bias']}"
        )
    return (
        "\n".join(lines)
        + f"\nAggregate expectation bias for gold: {macro['gold_bias']} (score {macro['bias_score']:+.2f}). Event risk: {macro['event_risk']}."
        + "\nRules of thumb: hotter CPI/PCE/PPI, strong NFP/wages, hawkish Fed → USD up, real yields up → gold DOWN."
        + " Softer inflation, weak jobs, rising unemployment/claims, dovish Fed → gold UP."
        + " If a HIGH-impact release is < 4h away, cut confidence and prefer tighter validity or HOLD — the print can invalidate any technical setup."
    )
