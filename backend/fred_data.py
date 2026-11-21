import asyncio
import logging
import os
import time
from typing import Dict, List, Optional

import httpx

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
_CACHE: Dict[str, tuple] = {}


def _cached(key: str, ttl: int):
    hit = _CACHE.get(key)
    return hit[1] if hit and time.time() - hit[0] < ttl else None


def _store(key: str, val):
    _CACHE[key] = (time.time(), val)
    return val


def fred_enabled() -> bool:
    return bool(os.environ.get("FRED_API_KEY"))


async def _fred_series(http: httpx.AsyncClient, series_id: str, limit: int = 15) -> List[float]:
    """Latest observations, newest first. Missing values ('.') dropped."""
    r = await http.get(FRED_URL, params={
        "series_id": series_id, "api_key": os.environ["FRED_API_KEY"], "file_type": "json",
        "sort_order": "desc", "limit": limit,
    })
    r.raise_for_status()
    out = []
    for o in r.json().get("observations", []):
        try:
            out.append((o["date"], float(o["value"])))
        except (ValueError, KeyError):
            continue
    return out


def _pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 1)


async def get_us_actuals() -> Optional[Dict]:
    """Official latest prints from FRED: CPI m/m & y/y, core CPI, NFP change, unemployment, core PCE."""
    if not fred_enabled():
        return None
    hit = _cached("fred_actuals", 1800)
    if hit is not None:
        return hit
    try:
        async with httpx.AsyncClient(timeout=12.0) as http:
            cpi, core, nfp, unrate, pce = await asyncio.gather(
                _fred_series(http, "CPIAUCSL"), _fred_series(http, "CPILFESL"),
                _fred_series(http, "PAYEMS", 3), _fred_series(http, "UNRATE", 2),
                _fred_series(http, "PCEPILFE", 14),
            )
    except Exception as e:
        logging.warning(f"FRED actuals fetch failed: {e}")
        return None
    actuals = {}
    if len(cpi) >= 13:
        actuals["cpi_mm"] = {"value": _pct(cpi[0][1], cpi[1][1]), "unit": "%", "period": cpi[0][0]}
        actuals["cpi_yy"] = {"value": _pct(cpi[0][1], cpi[12][1]), "unit": "%", "period": cpi[0][0]}
    if len(core) >= 13:
        actuals["core_cpi_mm"] = {"value": _pct(core[0][1], core[1][1]), "unit": "%", "period": core[0][0]}
        actuals["core_cpi_yy"] = {"value": _pct(core[0][1], core[12][1]), "unit": "%", "period": core[0][0]}
    if len(nfp) >= 2:
        actuals["nfp"] = {"value": round(nfp[0][1] - nfp[1][1]), "unit": "K", "period": nfp[0][0]}
    if unrate:
        actuals["unemployment"] = {"value": unrate[0][1], "unit": "%", "period": unrate[0][0]}
    if len(pce) >= 13:
        actuals["core_pce_mm"] = {"value": _pct(pce[0][1], pce[1][1]), "unit": "%", "period": pce[0][0]}
        actuals["core_pce_yy"] = {"value": _pct(pce[0][1], pce[12][1]), "unit": "%", "period": pce[0][0]}
    return _store("fred_actuals", actuals)


# Calendar title → FRED actual key (checked in order; first match wins)
TITLE_TO_ACTUAL = [
    ("core pce price index m/m", "core_pce_mm"), ("core pce price index y/y", "core_pce_yy"),
    ("core cpi m/m", "core_cpi_mm"), ("core cpi y/y", "core_cpi_yy"),
    ("cpi m/m", "cpi_mm"), ("cpi y/y", "cpi_yy"),
    ("non-farm employment change", "nfp"), ("unemployment rate", "unemployment"),
]


def actual_for_title(title: str, actuals: Optional[Dict]) -> Optional[Dict]:
    if not actuals:
        return None
    t = (title or "").lower()
    for needle, key in TITLE_TO_ACTUAL:
        if needle in t:
            return actuals.get(key)
    return None


async def _yahoo_last_two(http: httpx.AsyncClient, sym: str) -> Optional[tuple]:
    r = await http.get(YAHOO_URL.format(sym=sym), params={"interval": "1d", "range": "10d"})
    r.raise_for_status()
    closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]
    return (closes[-1], closes[-2], closes[0]) if len(closes) >= 2 else None


async def get_yields() -> Optional[Dict]:
    """US 10Y nominal yield (Yahoo ^TNX, intraday) + 10Y real yield & breakeven (FRED, daily)."""
    hit = _cached("yields", 600)
    if hit is not None:
        return hit
    out: Dict = {}
    try:
        async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "Mozilla/5.0"}) as http:
            tnx = await _yahoo_last_two(http, "%5ETNX")
            if tnx:
                last, prev, first = tnx
                out["nominal_10y"] = round(last, 3)
                out["nominal_10y_change_bp"] = round((last - prev) * 100, 1)
                out["nominal_10y_5d_change_bp"] = round((last - first) * 100, 1)
            if fred_enabled():
                real, be = await asyncio.gather(_fred_series(http, "DFII10", 8), _fred_series(http, "T10YIE", 2))
                if len(real) >= 2:
                    out["real_10y"] = real[0][1]
                    out["real_10y_change_bp"] = round((real[0][1] - real[1][1]) * 100, 1)
                    out["real_10y_5d_change_bp"] = round((real[0][1] - real[min(5, len(real) - 1)][1]) * 100, 1)
                    out["real_10y_date"] = real[0][0]
                if be:
                    out["breakeven_10y"] = be[0][1]
    except Exception as e:
        logging.warning(f"Yields fetch failed: {e}")
    if not out:
        return None
    move = out.get("real_10y_5d_change_bp", out.get("nominal_10y_5d_change_bp", 0)) or 0
    out["gold_bias"] = "BEARISH" if move >= 8 else "BULLISH" if move <= -8 else "NEUTRAL"
    return _store("yields", out)


def yields_prompt_block(y: Optional[Dict]) -> str:
    if not y:
        return "US yields: unavailable."
    parts = []
    if "nominal_10y" in y:
        parts.append(f"US 10Y nominal {y['nominal_10y']:.2f}% ({y['nominal_10y_change_bp']:+.1f}bp today, {y['nominal_10y_5d_change_bp']:+.1f}bp ~1w)")
    if "real_10y" in y:
        parts.append(f"10Y REAL yield (TIPS) {y['real_10y']:.2f}% ({y['real_10y_change_bp']:+.1f}bp d/d, {y['real_10y_5d_change_bp']:+.1f}bp 5d)")
    if "breakeven_10y" in y:
        parts.append(f"10Y breakeven inflation {y['breakeven_10y']:.2f}%")
    return (
        " | ".join(parts)
        + f"\nYield-implied gold bias: {y['gold_bias']}. Real yields are gold's opportunity cost — rising real yields are bearish gold, falling real yields bullish."
    )
