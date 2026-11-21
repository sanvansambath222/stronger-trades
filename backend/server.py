from fastapi import FastAPI, APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import json
import asyncio
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import httpx
import feedparser
import xml.etree.ElementTree as ET
from emergentintegrations.llm.chat import LlmChat, UserMessage
from macro_events import analyze_macro, macro_prompt_block
from ai_models import (
    MODEL_ROSTER, ROLES, PRESETS, MODEL_TIMEOUT_SECONDS, AISettings,
    default_settings, model_label, progress_push, progress_get,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Env
MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']
TWELVEDATA_API_KEY = os.environ.get('TWELVEDATA_API_KEY', '')
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="XAUUSD Trading Analytics API")
api_router = APIRouter(prefix="/api")

# In-memory caches (short TTL) to respect TwelveData rate limits
_cache: Dict[str, Dict[str, Any]] = {}

def _cache_get(key: str, ttl_seconds: int) -> Optional[Any]:
    entry = _cache.get(key)
    if not entry:
        return None
    if (datetime.now(timezone.utc) - entry['ts']).total_seconds() > ttl_seconds:
        return None
    return entry['data']

def _cache_get_stale(key: str) -> Optional[Any]:
    entry = _cache.get(key)
    return entry['data'] if entry else None

def _cache_set(key: str, data: Any) -> None:
    _cache[key] = {'ts': datetime.now(timezone.utc), 'data': data}

TD_BASE = "https://api.twelvedata.com"
SYMBOL = "XAU/USD"

YAHOO_GOLD_SYMBOL = "GC=F"  # COMEX Gold Futures — closest to XAU/USD spot
YAHOO_INTERVAL_MAP = {
    "1min":  ("1m",  "1d"),
    "5min":  ("5m",  "5d"),
    "15min": ("15m", "5d"),
    "1h":    ("60m", "30d"),
    "4h":    ("60m", "60d"),   # 4h not supported on Yahoo — use 60m candles
    "1day":  ("1d",  "300d"),
}

# ------------------- Yahoo Finance fallback -------------------
async def _yahoo_fetch_chart(symbol: str, interval: str, range_: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    async with httpx.AsyncClient(
        timeout=15.0,
        headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'},
    ) as http:
        r = await http.get(url, params={'interval': interval, 'range': range_})
        r.raise_for_status()
        data = r.json()
        if data.get('chart', {}).get('error'):
            raise HTTPException(status_code=502, detail=str(data['chart']['error']))
        results = data.get('chart', {}).get('result')
        if not results:
            raise HTTPException(status_code=502, detail="Yahoo: no data")
        return results[0]


async def _yahoo_get_quote() -> dict:
    """Get XAU/USD-equivalent quote via Yahoo Finance (Gold futures GC=F).
    Returns a dict; caller wraps it in Quote()."""
    result = await _yahoo_fetch_chart(YAHOO_GOLD_SYMBOL, "1d", "5d")
    meta = result['meta']
    price = float(meta['regularMarketPrice'])
    prev = float(meta.get('chartPreviousClose') or meta.get('previousClose') or price)
    change = price - prev
    pct = (change / prev * 100) if prev else 0
    quotes = (result.get('indicators', {}).get('quote') or [{}])[0]
    highs = [h for h in (quotes.get('high') or []) if h is not None]
    lows = [lo for lo in (quotes.get('low') or []) if lo is not None]
    opens = [o for o in (quotes.get('open') or []) if o is not None]
    return {
        "symbol": SYMBOL,
        "price": price,
        "change": change,
        "percent_change": pct,
        "high": max(highs[-2:]) if highs else price,
        "low": min(lows[-2:]) if lows else price,
        "open": opens[-1] if opens else price,
        "previous_close": prev,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _yahoo_get_candles(interval: str, size: int) -> List[dict]:
    yi, yr = YAHOO_INTERVAL_MAP.get(interval, ("60m", "30d"))
    result = await _yahoo_fetch_chart(YAHOO_GOLD_SYMBOL, yi, yr)
    ts = result.get('timestamp', []) or []
    q = (result.get('indicators', {}).get('quote') or [{}])[0]
    opens = q.get('open') or []
    highs = q.get('high') or []
    lows  = q.get('low')  or []
    closes = q.get('close') or []
    vols  = q.get('volume') or []
    candles: List[dict] = []
    for i, t in enumerate(ts):
        c = closes[i] if i < len(closes) else None
        if c is None:
            continue
        candles.append({
            'time': int(t),
            'open': float(opens[i]) if i < len(opens) and opens[i] is not None else float(c),
            'high': float(highs[i]) if i < len(highs) and highs[i] is not None else float(c),
            'low':  float(lows[i])  if i < len(lows)  and lows[i]  is not None else float(c),
            'close': float(c),
            'volume': float(vols[i]) if i < len(vols) and vols[i] is not None else 0,
        })
    return candles[-size:]


# ------------------- TwelveData helpers -------------------
async def td_get(path: str, params: dict) -> dict:
    params = {**params, 'apikey': TWELVEDATA_API_KEY}
    async with httpx.AsyncClient(timeout=15.0) as http:
        try:
            r = await http.get(f"{TD_BASE}/{path}", params=params)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 429:
                raise HTTPException(status_code=429, detail="Market data rate-limited. Try again in a moment.")
            raise HTTPException(status_code=502, detail=f"Market data HTTP {status}")
        except httpx.HTTPError as e:
            raise HTTPException(status_code=503, detail=f"Market data unavailable: {str(e)[:120]}")
        data = r.json()
        if isinstance(data, dict) and data.get('status') == 'error':
            code = data.get('code', 502)
            if code == 429:
                raise HTTPException(status_code=429, detail="Market data rate-limited. Try again in a moment.")
            raise HTTPException(status_code=502, detail=f"Market data error: {data.get('message', 'unknown')}")
        return data

# ------------------- Technical Indicators -------------------
def sma(values: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    s = sum(values[:period])
    out[period - 1] = s / period
    for i in range(period, len(values)):
        s += values[i] - values[i - period]
        out[i] = s / period
    return out

def ema(values: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out

def rsi(values: List[float], period: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if len(values) <= period:
        return out
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        ch = values[i] - values[i - 1]
        gains += max(ch, 0)
        losses += max(-ch, 0)
    avg_g = gains / period
    avg_l = losses / period
    rs = (avg_g / avg_l) if avg_l else 100
    out[period] = 100 - 100 / (1 + rs) if avg_l else 100
    for i in range(period + 1, len(values)):
        ch = values[i] - values[i - 1]
        g = max(ch, 0)
        ls = max(-ch, 0)
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + ls) / period
        rs = (avg_g / avg_l) if avg_l else 100
        out[i] = 100 - 100 / (1 + rs) if avg_l else 100
    return out

def macd(values: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    macd_line = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(ema_fast, ema_slow)
    ]
    # signal EMA over non-None macd
    valid = [m for m in macd_line if m is not None]
    signal_vals = ema(valid, signal) if len(valid) >= signal else []
    # align signal back to original length
    signal_line: List[Optional[float]] = [None] * len(values)
    offset = next((i for i, v in enumerate(macd_line) if v is not None), 0)
    for i, v in enumerate(signal_vals):
        signal_line[offset + i] = v
    hist = [
        (m - s) if (m is not None and s is not None) else None
        for m, s in zip(macd_line, signal_line)
    ]
    return macd_line, signal_line, hist

def bollinger(values: List[float], period: int = 20, mult: float = 2.0):
    mid = sma(values, period)
    upper: List[Optional[float]] = [None] * len(values)
    lower: List[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1: i + 1]
        mean = sum(window) / period
        var = sum((x - mean) ** 2 for x in window) / period
        sd = var ** 0.5
        upper[i] = mean + mult * sd
        lower[i] = mean - mult * sd
    return mid, upper, lower

# ------------------- Models -------------------
class Quote(BaseModel):
    symbol: str
    price: float
    change: float
    percent_change: float
    high: float
    low: float
    open: float
    previous_close: float
    timestamp: str

class Candle(BaseModel):
    time: int  # unix seconds
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None

class IndicatorSnapshot(BaseModel):
    rsi: Optional[float]
    macd: Optional[float]
    macd_signal: Optional[float]
    macd_hist: Optional[float]
    ema20: Optional[float]
    ema50: Optional[float]
    ema200: Optional[float]
    bb_upper: Optional[float]
    bb_mid: Optional[float]
    bb_lower: Optional[float]
    price: float

class AIVote(BaseModel):
    model: str  # human label e.g. "Claude Opus 5.5"
    model_id: str  # short id e.g. "opus" / "bull"
    engine_model: Optional[str] = None  # roster id of the model that produced this vote
    action: str  # BUY / SELL / HOLD
    confidence: int
    summary: str
    available: bool = True


class AISignal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action: str  # BUY / SELL / HOLD
    confidence: int  # 0-100
    entry: float
    stop_loss: float
    take_profit: float
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    timeframe: str
    reasoning: str
    summary: str
    sentiment: str  # BULLISH / BEARISH / NEUTRAL
    indicators: Dict[str, Optional[float]]
    created_at: str
    # Strong-analysis extensions
    signal_strength: Optional[str] = None  # WEAK / MODERATE / STRONG / VERY_STRONG
    valid_for_minutes: Optional[int] = None
    expires_at: Optional[str] = None
    risk_reward: Optional[float] = None
    higher_tf_trend: Optional[str] = None
    lower_tf_momentum: Optional[str] = None
    news_sentiment: Optional[str] = None
    dxy_price: Optional[float] = None
    dxy_change_pct: Optional[float] = None
    analysis_steps: Optional[Dict[str, str]] = None
    # Ensemble fields
    consensus: Optional[str] = None  # DOUBLE_CONFIRMED / MAJORITY / CONFLICTED / SINGLE_SOURCE
    votes: Optional[List[AIVote]] = None
    news_sources: Optional[List[Dict[str, str]]] = None  # headlines used in analysis
    # Volatility-aware SL/TP origin (e.g. "ATR(2.40) × 1.6" or "1.8% of price")
    sl_method: Optional[str] = None
    # True when rule engine produced STRONG and we auto-escalated to Dual-AI
    auto_upgraded: bool = False
    # Economic-calendar blackout context (None when filter disabled)
    news_blackout: Optional[Dict[str, Any]] = None
    # Bull-vs-Bear debate transcript (None unless engine="council")
    council_debate: Optional[Dict[str, Any]] = None
    # Roster ids of the AI models that produced this signal (["rule"] for rule engine)
    models_used: Optional[List[str]] = None
    # Economic-calendar macro read (CPI, NFP, FOMC… forecast vs previous → gold bias)
    macro_context: Optional[Dict[str, Any]] = None

# ------------------- Routes -------------------
@api_router.get("/")
async def root():
    return {"service": "XAUUSD Trading Analytics API", "status": "ok"}

@api_router.get("/market/quote", response_model=Quote)
async def get_quote():
    cache = _cache_get('quote', ttl_seconds=15)
    if cache:
        return cache
    try:
        data = await td_get("quote", {"symbol": SYMBOL})
        q = Quote(
            symbol=data.get('symbol', SYMBOL),
            price=float(data['close']),
            change=float(data.get('change', 0)),
            percent_change=float(data.get('percent_change', 0)),
            high=float(data.get('high', data['close'])),
            low=float(data.get('low', data['close'])),
            open=float(data.get('open', data['close'])),
            previous_close=float(data.get('previous_close', data['close'])),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        _cache_set('quote', q.model_dump())
        return q
    except HTTPException as e:
        if e.status_code in (429, 502, 503):
            try:
                yq_dict = await _yahoo_get_quote()
                _cache_set('quote', yq_dict)
                return Quote(**yq_dict)
            except Exception as ye:
                logging.warning(f"Yahoo quote fallback failed: {ye}")
            stale = _cache_get_stale('quote')
            if stale:
                return stale
        raise

@api_router.get("/market/candles")
async def get_candles(interval: str = Query("1h"), size: int = Query(120, ge=20, le=500)):
    key = f"candles:{interval}:{size}"
    cache = _cache_get(key, ttl_seconds=30)
    if cache:
        return cache
    # Try TwelveData first
    try:
        data = await td_get("time_series", {"symbol": SYMBOL, "interval": interval, "outputsize": size})
        values = data.get('values', [])
        candles = []
        for v in reversed(values):
            try:
                t = datetime.fromisoformat(v['datetime'].replace(' ', 'T'))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                candles.append({
                    'time': int(t.timestamp()),
                    'open': float(v['open']),
                    'high': float(v['high']),
                    'low': float(v['low']),
                    'close': float(v['close']),
                    'volume': float(v.get('volume') or 0),
                })
            except (KeyError, ValueError):
                continue
        result = {'symbol': SYMBOL, 'interval': interval, 'candles': candles}
        _cache_set(key, result)
        return result
    except HTTPException as e:
        # Yahoo Finance fallback
        if e.status_code in (429, 502, 503):
            try:
                ycandles = await _yahoo_get_candles(interval, size)
                if ycandles:
                    result = {'symbol': SYMBOL, 'interval': interval, 'candles': ycandles}
                    _cache_set(key, result)
                    return result
            except Exception as ye:
                logging.warning(f"Yahoo candles fallback failed: {ye}")
            stale = _cache_get_stale(key)
            if stale:
                return stale
        raise

@api_router.get("/analysis/indicators", response_model=IndicatorSnapshot)
async def get_indicators(interval: str = Query("1h")):
    candles_resp = await get_candles(interval=interval, size=250)
    closes = [c['close'] for c in candles_resp['candles']]
    if len(closes) < 30:
        raise HTTPException(status_code=400, detail="Not enough data for indicators")
    rsi_v = rsi(closes, 14)
    macd_line, sig_line, hist = macd(closes)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    mid, upper, lower = bollinger(closes, 20, 2.0)
    return IndicatorSnapshot(
        rsi=rsi_v[-1],
        macd=macd_line[-1],
        macd_signal=sig_line[-1],
        macd_hist=hist[-1],
        ema20=ema20[-1],
        ema50=ema50[-1],
        ema200=ema200[-1],
        bb_upper=upper[-1],
        bb_mid=mid[-1],
        bb_lower=lower[-1],
        price=closes[-1],
    )

TIMEFRAME_HIERARCHY = {
    "1min": ("5min", "15min"),
    "5min": ("15min", "1h"),
    "15min": ("1h", "4h"),
    "1h": ("4h", "1day"),
    "4h": ("1day", "1week"),
    "1day": ("1week", "1month"),
}

TIMEFRAME_EXPIRY_MIN = {
    "1min": 30,
    "5min": 120,
    "15min": 360,
    "1h": 720,
    "4h": 2880,
    "1day": 10080,
}

async def _safe_indicators(interval: str) -> Optional[IndicatorSnapshot]:
    try:
        return await get_indicators(interval=interval)
    except Exception:
        return None

async def _safe_dxy() -> Optional[Dict[str, float]]:
    cached = _cache_get('dxy', ttl_seconds=300)
    if cached:
        return cached
    # Primary: Yahoo Finance (free, no key needed)
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB"
        async with httpx.AsyncClient(
            timeout=10.0,
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        ) as http:
            r = await http.get(url, params={'interval': '1d', 'range': '5d'})
            r.raise_for_status()
            data = r.json()
            result = data['chart']['result'][0]
            meta = result['meta']
            price = float(meta['regularMarketPrice'])
            prev = float(
                meta.get('chartPreviousClose')
                or meta.get('previousClose')
                or price
            )
            pct = ((price - prev) / prev * 100) if prev else 0.0
            dxy = {'price': price, 'percent_change': pct}
            _cache_set('dxy', dxy)
            return dxy
    except Exception as e:
        logging.warning(f"Yahoo DXY fetch failed: {e}")
    # Fallback: TwelveData (often restricted on free tier)
    try:
        data = await td_get("quote", {"symbol": "DXY"})
        dxy = {
            'price': float(data['close']),
            'percent_change': float(data.get('percent_change', 0)),
        }
        _cache_set('dxy', dxy)
        return dxy
    except Exception:
        return None

async def _safe_news_titles(limit: int = 8) -> List[str]:
    items = await _fetch_all_news()
    return [item.get('title', '') for item in items[:limit] if item.get('title')]

async def _safe_news_items(limit: int = 12) -> List[dict]:
    items = await _fetch_all_news()
    return items[:limit]

def _trend_label(snap: Optional[IndicatorSnapshot]) -> str:
    if not snap or snap.ema20 is None or snap.ema50 is None:
        return "UNKNOWN"
    if snap.price > snap.ema20 > snap.ema50:
        return "BULLISH"
    if snap.price < snap.ema20 < snap.ema50:
        return "BEARISH"
    return "MIXED"

def _build_strong_prompt(
    snapshot: IndicatorSnapshot,
    interval: str,
    recent_candles: List[dict],
    higher_snap: Optional[IndicatorSnapshot],
    lower_snap: Optional[IndicatorSnapshot],
    higher_tf: str,
    lower_tf: str,
    dxy: Optional[Dict[str, float]],
    news_titles: List[str],
    macro: Optional[Dict[str, Any]] = None,
) -> str:
    def f(v):
        return f"{v:.4f}" if isinstance(v, (int, float)) else "n/a"

    last10 = recent_candles[-10:]
    candle_str = "\n".join(
        f"  {c['open']:.2f} O / {c['high']:.2f} H / {c['low']:.2f} L / {c['close']:.2f} C"
        for c in last10
    )

    def tf_block(label, snap):
        if not snap:
            return f"  [{label}]: unavailable"
        return (
            f"  [{label}] price {snap.price:.2f} | EMA20 {f(snap.ema20)} | "
            f"EMA50 {f(snap.ema50)} | EMA200 {f(snap.ema200)} | RSI {f(snap.rsi)} | "
            f"MACD {f(snap.macd)} (sig {f(snap.macd_signal)}) | trend {_trend_label(snap)}"
        )

    mtf_section = "\n".join([
        tf_block(f"LOWER · {lower_tf}", lower_snap),
        tf_block(f"PRIMARY · {interval}", snapshot),
        tf_block(f"HIGHER · {higher_tf}", higher_snap),
    ])

    dxy_section = (
        f"DXY (US Dollar Index): {dxy['price']:.2f} ({dxy['percent_change']:+.2f}% today). "
        f"Remember: gold is INVERSELY correlated with DXY — strong USD usually weighs on gold."
        if dxy else "DXY: unavailable — use neutral assumption."
    )

    news_section = (
        "\n".join(f"  - {t}" for t in news_titles[:8])
        if news_titles else "  (no recent gold news fetched)"
    )

    expiry_floor = TIMEFRAME_EXPIRY_MIN.get(interval, 720)

    return f"""You are a senior FX & commodities analyst running a deep multi-factor analysis on XAU/USD (Gold).
Synthesize ALL the inputs below — do NOT just look at primary indicators. Cross-check with higher timeframe trend, lower timeframe momentum, DXY context, and recent news catalysts.

═══ MULTI-TIMEFRAME SNAPSHOT ═══
{mtf_section}

═══ PRIMARY ({interval}) — LAST 10 CANDLES ═══
{candle_str}

═══ BOLLINGER BANDS (primary {interval}) ═══
upper {f(snapshot.bb_upper)} | mid {f(snapshot.bb_mid)} | lower {f(snapshot.bb_lower)}

═══ MACRO CONTEXT ═══
{dxy_section}

═══ ECONOMIC CALENDAR · HIGH-IMPACT USD RELEASES (CPI, NFP, FOMC, PCE…) ═══
{macro_prompt_block(macro)}

═══ RECENT GOLD MARKET NEWS HEADLINES ═══
{news_section}

═══ YOUR TASK ═══
Decide BUY / SELL / HOLD. A signal is STRONGER when multiple factors align (e.g., primary trend up + higher TF up + lower TF momentum up + DXY weakening + bullish news + supportive CPI/NFP/Fed expectations). Be conservative: when factors conflict, lower the confidence and signal_strength, or output HOLD.

Confidence calibration (be honest):
  - 80-100: very strong confluence across factors → signal_strength VERY_STRONG
  - 65-80: solid alignment with minor noise → STRONG
  - 50-65: mixed but leans one way → MODERATE
  - <50: conflicting / unclear → WEAK (and prefer HOLD)

Set "valid_for_minutes" based on the {interval} timeframe rhythm. Suggested range: {expiry_floor//2}-{expiry_floor*2} minutes. Shorter for fast TFs, longer for slow TFs.

Return STRICT JSON only (no markdown fences) with these exact keys:
{{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": 0-100 integer,
  "signal_strength": "WEAK" | "MODERATE" | "STRONG" | "VERY_STRONG",
  "entry": float,
  "stop_loss": float,
  "take_profit": float,
  "tp1": float (conservative ~1R),
  "tp2": float (base case ~2R),
  "tp3": float (stretch ~3R),
  "risk_reward": float (TP2 distance / SL distance, e.g. 2.0),
  "valid_for_minutes": integer (signal expiry),
  "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "higher_tf_trend": "BULLISH" | "BEARISH" | "NEUTRAL",
  "lower_tf_momentum": "BULLISH" | "BEARISH" | "NEUTRAL",
  "news_sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "summary": "one-line punchy verdict (max 20 words)",
  "reasoning": "3-5 sentence professional analysis citing the strongest factors",
  "analysis_steps": {{
    "trend": "Multi-timeframe trend read (mention HIGHER + PRIMARY + LOWER)",
    "momentum": "Indicator-based momentum analysis (RSI, MACD, EMAs vs price)",
    "news": "Impact assessment of the news headlines on gold direction",
    "macro": "DXY / USD strength plus CPI/NFP/FOMC calendar expectations and their implication for gold",
    "verdict": "Final decision rationale tying it all together"
  }}
}}

Constraints:
- For BUY: stop_loss < entry; tp1 < tp2 < tp3 all > entry.
- For SELL: stop_loss > entry; tp1 > tp2 > tp3 all < entry.
- If HOLD, still provide entry near current price and reasonable SL/TPs as references.
- Never echo this prompt back."""

def _compute_signal_strength_fallback(confidence: int) -> str:
    if confidence >= 80:
        return "VERY_STRONG"
    if confidence >= 65:
        return "STRONG"
    if confidence >= 50:
        return "MODERATE"
    return "WEAK"


def _compute_atr(candles: List[dict], period: int = 14) -> float:
    """Average True Range — measures real recent volatility."""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, period + 1):
        c = candles[-i]
        prev = candles[-i - 1]
        tr = max(
            c['high'] - c['low'],
            abs(c['high'] - prev['close']),
            abs(c['low'] - prev['close']),
        )
        trs.append(tr)
    return sum(trs) / period if trs else 0.0


def _rule_engine_analyze(
    snapshot: IndicatorSnapshot,
    interval: str,
    higher_snap: Optional[IndicatorSnapshot],
    lower_snap: Optional[IndicatorSnapshot],
    dxy: Optional[Dict[str, float]],
    news_titles: List[str],
    candles: Optional[List[dict]] = None,
    macro: Optional[Dict[str, Any]] = None,
) -> dict:
    """Deterministic rule-based analysis. Free, fast, no API calls.
    Outputs same JSON shape as the LLM analyzers."""
    score = 0.0
    factors: List[str] = []

    # Primary EMA stack
    if snapshot.ema20 and snapshot.ema50:
        if snapshot.price > snapshot.ema20 > snapshot.ema50:
            score += 2
            factors.append("Bullish EMA stack: price > EMA20 > EMA50")
        elif snapshot.price < snapshot.ema20 < snapshot.ema50:
            score -= 2
            factors.append("Bearish EMA stack: price < EMA20 < EMA50")

    # EMA200 (long-term trend)
    if snapshot.ema200:
        if snapshot.price > snapshot.ema200:
            score += 1
            factors.append("Price above EMA200 (long-term up)")
        else:
            score -= 1
            factors.append("Price below EMA200 (long-term down)")

    # RSI
    if snapshot.rsi is not None:
        if snapshot.rsi > 70:
            score -= 1
            factors.append(f"RSI {snapshot.rsi:.1f} overbought")
        elif snapshot.rsi < 30:
            score += 1
            factors.append(f"RSI {snapshot.rsi:.1f} oversold")
        elif snapshot.rsi > 55:
            score += 0.5
            factors.append(f"RSI {snapshot.rsi:.1f} bullish bias")
        elif snapshot.rsi < 45:
            score -= 0.5
            factors.append(f"RSI {snapshot.rsi:.1f} bearish bias")

    # MACD
    if snapshot.macd is not None and snapshot.macd_signal is not None:
        if snapshot.macd > snapshot.macd_signal:
            score += 1
            factors.append("MACD bullish cross")
        else:
            score -= 1
            factors.append("MACD bearish cross")

    # Higher TF
    higher_trend = _trend_label(higher_snap)
    if higher_trend == "BULLISH":
        score += 1
    elif higher_trend == "BEARISH":
        score -= 1

    # Lower TF momentum
    lower_trend = _trend_label(lower_snap)
    if lower_trend == "BULLISH":
        score += 0.5
    elif lower_trend == "BEARISH":
        score -= 0.5

    # DXY (inverse correlation)
    if dxy and dxy.get('percent_change') is not None:
        chg = dxy['percent_change']
        if chg > 0.3:
            score -= 1
            factors.append(f"DXY +{chg:.2f}% strong dollar — bearish gold")
        elif chg < -0.3:
            score += 1
            factors.append(f"DXY {chg:.2f}% weak dollar — bullish gold")

    # Bollinger bands
    if snapshot.bb_upper and snapshot.bb_lower and snapshot.bb_upper > snapshot.bb_lower:
        bb_pos = (snapshot.price - snapshot.bb_lower) / (snapshot.bb_upper - snapshot.bb_lower)
        if bb_pos > 0.9:
            score -= 0.5
            factors.append("Near upper Bollinger band — overextended")
        elif bb_pos < 0.1:
            score += 0.5
            factors.append("Near lower Bollinger band — oversold")

    # Economic calendar (CPI, NFP, FOMC…): forecast vs previous expectation bias
    if macro and macro.get("bias_score"):
        m_score = max(-1.5, min(1.5, macro["bias_score"] * 0.5))
        score += m_score
        factors.append(f"Macro calendar bias {macro['gold_bias']} ({m_score:+.1f}) from {len(macro.get('events') or [])} USD releases")

    # Decide action
    if score >= 3:
        action = "BUY"
        confidence = min(95, 50 + int(score * 6))
    elif score <= -3:
        action = "SELL"
        confidence = min(95, 50 + int(-score * 6))
    else:
        action = "HOLD"
        confidence = max(30, 50 - int(abs(score) * 4))
    if macro and macro.get("event_risk") == "HIGH" and action != "HOLD":
        nxt = macro.get("next_high_impact") or {}
        confidence = max(30, confidence - 10)
        factors.append(f"Event risk: {nxt.get('title', 'high-impact release')} within 4h — confidence cut")

    # Strength
    abs_s = abs(score)
    if abs_s >= 5:
        strength = "VERY_STRONG"
    elif abs_s >= 3.5:
        strength = "STRONG"
    elif abs_s >= 2:
        strength = "MODERATE"
    else:
        strength = "WEAK"

    # SL/TP based on REAL volatility (ATR) — falls back to % if not enough candles
    atr_val = _compute_atr(candles or [], period=14)
    if atr_val > 0:
        # ATR multipliers tuned per timeframe (tighter for fast TFs, wider for slow)
        atr_mult = {
            "1min": 1.0, "5min": 1.2, "15min": 1.4,
            "1h": 1.6, "4h": 1.8, "1day": 2.0,
        }.get(interval, 1.5)
        sl_dist = atr_val * atr_mult
        sl_method = f"ATR({atr_val:.2f}) × {atr_mult}"
    else:
        sl_pct = {
            "1min": 0.005, "5min": 0.008, "15min": 0.012,
            "1h": 0.018, "4h": 0.028, "1day": 0.045,
        }.get(interval, 0.018)
        sl_dist = snapshot.price * sl_pct
        sl_method = f"{sl_pct*100:.1f}% of price"

    if action == "BUY":
        entry = snapshot.price
        sl = round(entry - sl_dist, 2)
        tp1 = round(entry + sl_dist, 2)
        tp2 = round(entry + sl_dist * 2, 2)
        tp3 = round(entry + sl_dist * 3, 2)
    elif action == "SELL":
        entry = snapshot.price
        sl = round(entry + sl_dist, 2)
        tp1 = round(entry - sl_dist, 2)
        tp2 = round(entry - sl_dist * 2, 2)
        tp3 = round(entry - sl_dist * 3, 2)
    else:
        entry = snapshot.price
        sl = round(entry - sl_dist, 2)
        tp1 = round(entry + sl_dist, 2)
        tp2 = round(entry + sl_dist * 2, 2)
        tp3 = round(entry + sl_dist * 3, 2)

    sentiment = "BULLISH" if score > 1 else "BEARISH" if score < -1 else "NEUTRAL"

    summary = (
        f"{action} {strength.replace('_', ' ').title()} setup. "
        f"Score {score:+.1f} from {len(factors)} factors."
    )
    reasoning = " ".join(factors[:6]) if factors else "Insufficient confluence — staying neutral."

    rsi_str = f"{snapshot.rsi:.1f}" if snapshot.rsi is not None else "n/a"
    macd_bull = (
        snapshot.macd is not None and snapshot.macd_signal is not None
        and snapshot.macd > snapshot.macd_signal
    )
    macd_str = "bullish" if macd_bull else "bearish"

    return {
        "action": action,
        "confidence": confidence,
        "signal_strength": strength,
        "entry": round(entry, 2),
        "stop_loss": sl,
        "take_profit": tp1,
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "risk_reward": 2.0,
        "valid_for_minutes": TIMEFRAME_EXPIRY_MIN.get(interval, 720),
        "sentiment": sentiment,
        "higher_tf_trend": higher_trend,
        "lower_tf_momentum": lower_trend,
        "news_sentiment": "NEUTRAL",
        "summary": summary,
        "reasoning": reasoning,
        "sl_method": sl_method,
        "analysis_steps": {
            "trend": f"Higher TF: {higher_trend} · Primary: {_trend_label(snapshot)} · Lower TF: {lower_trend}",
            "momentum": f"RSI {rsi_str} · MACD {macd_str} cross",
            "news": f"Aggregated {len(news_titles)} headlines (rule engine doesn't read text — click Deep AI for that)",
            "macro": (
                f"DXY {dxy['price']:.2f} ({dxy['percent_change']:+.2f}%)"
                if dxy else "DXY unavailable"
            ),
            "verdict": (
                f"Combined factor score {score:+.1f} → {action} with {strength.replace('_', ' ')} strength. "
                f"SL distance derived from {sl_method}."
            ),
        },
    }


async def _run_model(model_id: str, prompt: str, label: str) -> Optional[dict]:
    """Call one roster model with a timeout, parse its JSON reply. Returns None on failure/timeout."""
    meta = MODEL_ROSTER.get(model_id)
    if not meta:
        return None
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"xauusd-{label}-{uuid.uuid4()}",
            system_message="You are a precise FX/commodities analyst. Respond with strict JSON only.",
        ).with_model(meta["provider"], meta["model"])
        text = await asyncio.wait_for(chat.send_message(UserMessage(text=prompt)), timeout=MODEL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logging.warning(f"AI {label} ({model_id}) timed out after {MODEL_TIMEOUT_SECONDS}s")
        return None
    except Exception as e:
        logging.warning(f"AI {label} ({model_id}) call failed: {e}")
        return None
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None

def _build_bull_prompt(base_prompt: str, baseline: dict) -> str:
    return f"""You are the BULL RESEARCHER on a XAU/USD trading desk.
Argue the strongest BUY case from the data — even if market leans bearish. Be honest, concise.

═══ MARKET INPUTS ═══
{base_prompt}

═══ RULE-ENGINE BASELINE ═══
Action: {baseline.get('action')}, Confidence: {baseline.get('confidence')}, Strength: {baseline.get('signal_strength')}

Output STRICT JSON only (be concise — response must complete in <20s):
{{
  "stance": "BULLISH" | "NEUTRAL_BULL",
  "thesis": "2-3 sentence case for LONG / not shorting",
  "key_points": ["b1", "b2", "b3"],
  "strongest_factor": "the single most compelling bullish piece (1 line)",
  "weakness_in_my_case": "biggest hole in bull argument (1 line)",
  "confidence_in_buy": 0-100
}}
No markdown, no preamble.""".strip()


def _build_bear_prompt(base_prompt: str, baseline: dict, bull_thesis: dict) -> str:
    has_bull = bool(bull_thesis and bull_thesis.get("thesis"))
    if has_bull:
        bull_points = "\n".join(f"  - {p}" for p in (bull_thesis.get("key_points") or [])[:3])
        bull_block = f"""═══ BULL'S THESIS (rebut briefly) ═══
{bull_thesis.get('thesis', '')[:240]}
{bull_points or ''}"""
    else:
        bull_block = "═══ TASK CONTEXT ═══\nBuild the strongest BEARISH case from market data. Address typical bullish counterpoints (oversold RSI, mean-reversion, safe-haven)."

    return f"""You are the BEAR RESEARCHER on a XAU/USD trading desk.
Argue the strongest SHORT case (or HOLD if unclear). Be honest, concise.

═══ MARKET INPUTS ═══
{base_prompt}

═══ RULE-ENGINE BASELINE ═══
Action: {baseline.get('action')}, Strength: {baseline.get('signal_strength')}

{bull_block}

Output STRICT JSON only (be concise — response must complete in <20s):
{{
  "stance": "BEARISH" | "NEUTRAL_BEAR",
  "rebuttals": ["r1", "r2", "r3"],
  "thesis": "2-3 sentence case for SHORT or HOLD",
  "key_points": ["b1", "b2", "b3"],
  "strongest_factor": "single most compelling bearish piece (1 line)",
  "weakness_in_my_case": "biggest hole (1 line)",
  "confidence_in_sell": 0-100
}}
No markdown, no preamble.""".strip()


def _build_trader_judge_prompt(base_prompt: str, baseline: dict, bull: dict, bear: dict) -> str:
    return f"""You are the HEAD TRADER. You just watched Bull vs Bear debate XAU/USD.
Your job: pick a side (or HOLD), commit to actual numbers, and explain the call. Use ATR-aware SL/TP — wider on slower timeframes, tighter on faster ones.

═══ MARKET INPUTS ═══
{base_prompt}

═══ RULE-ENGINE BASELINE ═══
Action: {baseline.get('action')}, Confidence: {baseline.get('confidence')}, Strength: {baseline.get('signal_strength')}
Suggested Entry: {baseline.get('entry')}, SL: {baseline.get('stop_loss')}, TP1/2/3: {baseline.get('tp1')}/{baseline.get('tp2')}/{baseline.get('tp3')}
SL distance source: {baseline.get('sl_method')}

═══ BULL CASE ═══
Conf BUY: {bull.get('confidence_in_buy')}
{bull.get('thesis')}
Strongest factor: {bull.get('strongest_factor')}

═══ BEAR CASE ═══
Conf SELL: {bear.get('confidence_in_sell')}
{bear.get('thesis')}
Strongest factor: {bear.get('strongest_factor')}
Rebuttals: {' | '.join(bear.get('rebuttals') or [])}

═══ YOUR TASK ═══
Be decisive. If one side clearly wins the debate, take it. If both have merit but conflict, output HOLD with HONEST low-MODERATE confidence.

Confidence calibration:
  - 80-100: bull (or bear) demolished the other side → VERY_STRONG
  - 65-80: clearly winning argument despite valid counter → STRONG
  - 50-65: leans one way but both sides have merit → MODERATE
  - <50: stalemate / unclear → WEAK → prefer HOLD

Keep entry close to current price. Honor the SL distance from the baseline (it's volatility-aware).

Return STRICT JSON only (no markdown fences):
{{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": 0-100 integer,
  "signal_strength": "WEAK" | "MODERATE" | "STRONG" | "VERY_STRONG",
  "winner": "BULL" | "BEAR" | "TIE",
  "entry": float,
  "stop_loss": float,
  "take_profit": float,
  "tp1": float, "tp2": float, "tp3": float,
  "risk_reward": float,
  "valid_for_minutes": integer,
  "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "higher_tf_trend": "BULLISH" | "BEARISH" | "NEUTRAL",
  "lower_tf_momentum": "BULLISH" | "BEARISH" | "NEUTRAL",
  "news_sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "summary": "one-line punchy verdict referencing the debate (max 22 words)",
  "reasoning": "3-5 sentence pro analysis citing why one side won (or both lost)",
  "analysis_steps": {{
    "trend": "MTF read",
    "momentum": "indicator-based momentum",
    "news": "news impact",
    "macro": "DXY context",
    "verdict": "why bull or bear won — be specific"
  }}
}}
No markdown, no preamble.""".strip()


async def _run_role(role: str, prompt: str, settings: AISettings, run_id: Optional[str]) -> Optional[dict]:
    mid = settings.roles[role]
    parsed = await _run_model(mid, prompt, role)
    progress_push(run_id, {"kind": "role", "role": role, "engine_model": mid,
                           "model": model_label(mid), "available": parsed is not None})
    return parsed


async def _run_council_debate(
    base_prompt: str,
    baseline: dict,
    settings: AISettings,
    run_id: Optional[str] = None,
) -> tuple[Optional[dict], dict, dict]:
    """Bull ∥ Bear in parallel, then the Head Trader synthesizes both. Returns (trader_verdict, bull, bear)."""
    bull_prompt = _build_bull_prompt(base_prompt, baseline)
    bear_prompt = _build_bear_prompt(base_prompt, baseline, {})
    bull, bear = await asyncio.gather(
        _run_role("bull", bull_prompt, settings, run_id),
        _run_role("bear", bear_prompt, settings, run_id),
    )
    if not bull or not bear:
        return None, bull or {}, bear or {}
    trader_prompt = _build_trader_judge_prompt(base_prompt, baseline, bull, bear)
    trader = await _run_role("trader", trader_prompt, settings, run_id)
    return trader, bull, bear


# ───────── Risk Team Layer (3 risk perspectives + Manager, each played by its chosen model) ─────────
RISK_PERSONAS = {
    "aggressive": ("AGGRESSIVE", "You favour growth and larger size on STRONG signals.", "0.0-3.0"),
    "neutral": ("NEUTRAL", "You apply textbook 1-2% risk that scales with confidence.", "0.0-2.0"),
    "conservative": ("CONSERVATIVE", "Capital preservation first. Default to REJECT when unclear.", "0.0-1.0"),
}


def _trader_block(trader: dict) -> str:
    return (
        f"Action: {trader.get('action')}, Confidence: {trader.get('confidence')}, Strength: {trader.get('signal_strength')}\n"
        f"Entry: {trader.get('entry')}, SL: {trader.get('stop_loss')}, TP1/2/3: {trader.get('tp1')}/{trader.get('tp2')}/{trader.get('tp3')}\n"
        f"R:R: {trader.get('risk_reward')}\nSummary: {trader.get('summary')}"
    )


def _build_risk_role_prompt(role: str, base_prompt: str, trader: dict) -> str:
    name, persona, size_range = RISK_PERSONAS[role]
    return f"""You are the {name} RISK MANAGER on a XAU/USD trading desk. {persona}
Review the Head Trader's proposal honestly. Do not agree to be polite.

═══ MARKET INPUTS ═══
{base_prompt}

═══ HEAD TRADER PROPOSAL ═══
{_trader_block(trader)}

Return STRICT JSON only (concise, no markdown):
{{
  "role": "{name}",
  "vote": "APPROVE" | "APPROVE_REDUCED" | "REJECT",
  "recommended_size_pct": {size_range},
  "stance": "1-2 sentences",
  "key_concerns": ["c1", "c2"],
  "size_rationale": "1 sentence"
}}""".strip()


def _build_manager_prompt(trader: dict, risk: Dict[str, dict]) -> str:
    def r(k):
        d = risk[k]
        return f"{k.upper()}: {d.get('vote')} · size {d.get('recommended_size_pct')}% — {d.get('stance')}"
    return f"""You are the PORTFOLIO MANAGER of a XAU/USD desk — final authority on the trade.

═══ HEAD TRADER PROPOSAL ═══
{_trader_block(trader)}

═══ RISK TEAM VOTES ═══
{r('aggressive')}
{r('neutral')}
{r('conservative')}

═══ DECISION RULES ═══
- 2+ REJECTs → final = REJECT (action=HOLD, size=0)
- 1 REJECT + others APPROVE → size between Neutral's and Conservative's
- All APPROVE → use Neutral's size
- Position size MUST stay 0% ≤ size ≤ 2%
- May tighten SL but NEVER widen beyond the trader's SL

Return STRICT JSON only (concise, no markdown):
{{
  "decision": "AUTHORIZE" | "AUTHORIZE_MODIFIED" | "REJECT",
  "final_action": "BUY" | "SELL" | "HOLD",
  "position_size_pct": 0.0-2.0,
  "final_entry": float, "final_sl": float,
  "final_tp1": float, "final_tp2": float, "final_tp3": float,
  "rationale": "2-3 sentences citing risk votes by name",
  "modifications": ["<=1 item, optional"],
  "tilt": "AGGRESSIVE" | "NEUTRAL" | "CONSERVATIVE"
}}""".strip()


async def _run_risk_team(
    base_prompt: str,
    trader: dict,
    settings: AISettings,
    run_id: Optional[str] = None,
) -> Optional[dict]:
    """Aggressive ∥ Neutral ∥ Conservative, then Portfolio Manager. Returns risk_team dict or None."""
    roles = ["aggressive", "neutral", "conservative"]
    results = await asyncio.gather(*(
        _run_role(r, _build_risk_role_prompt(r, base_prompt, trader), settings, run_id) for r in roles
    ))
    risk = dict(zip(roles, results))
    if not all(risk.values()):
        return None
    manager = await _run_role("manager", _build_manager_prompt(trader, risk), settings, run_id)
    if not manager:
        return None
    return {**risk, "manager": manager}


def _vote_from(model_id: str, parsed: Optional[dict]) -> AIVote:
    if not parsed:
        return AIVote(model=model_label(model_id), model_id=model_id, engine_model=model_id,
                      action="N/A", confidence=0, summary="(failed or timed out)", available=False)
    action = str(parsed.get('action', 'HOLD')).upper()
    if action not in ("BUY", "SELL", "HOLD"):
        action = "HOLD"
    try:
        conf = int(parsed.get('confidence', 50))
    except (TypeError, ValueError):
        conf = 50
    return AIVote(model=model_label(model_id), model_id=model_id, engine_model=model_id,
                  action=action, confidence=conf, summary=str(parsed.get('summary', ''))[:240], available=True)


async def _run_ensemble(prompt: str, settings: AISettings, run_id: Optional[str] = None) -> List[tuple]:
    async def one(mid: str):
        parsed = await _run_model(mid, prompt, f"ens-{mid}")
        vote = _vote_from(mid, parsed)
        progress_push(run_id, {"kind": "vote", **vote.model_dump()})
        return mid, parsed, vote
    return await asyncio.gather(*(one(m) for m in settings.ensemble))


def _compute_consensus(results: List[tuple]) -> tuple[str, dict, List[AIVote]]:
    """Majority vote across any number of models. Returns (consensus_label, chosen_signal_dict, votes)."""
    votes = [v for _, _, v in results]
    ok = [(mid, p, v) for mid, p, v in results if v.available]
    if not ok:
        return "FAILED", {}, votes
    if len(ok) == 1:
        return "SINGLE_SOURCE", dict(ok[0][1]), votes

    counts: Dict[str, int] = {}
    for _, _, v in ok:
        counts[v.action] = counts.get(v.action, 0) + 1
    top = max(counts.values())
    leaders = [a for a, c in counts.items() if c == top]
    best_of = lambda rows: max(rows, key=lambda r: r[2].confidence)  # noqa: E731

    if len(leaders) > 1:
        chosen = dict(best_of(ok)[1])
        chosen['confidence'] = max(20, int(int(chosen.get('confidence', 50)) * 0.6))
        chosen['action'] = "HOLD"
        return "CONFLICTED", chosen, votes

    winner = leaders[0]
    winners = [r for r in ok if r[2].action == winner]
    chosen = dict(best_of(winners)[1])
    chosen['action'] = winner
    avg_conf = sum(r[2].confidence for r in winners) / len(winners)
    if len(winners) == len(ok):
        chosen['confidence'] = min(95, int(avg_conf) + 8)
        return "UNANIMOUS", chosen, votes
    chosen['confidence'] = max(20, int(avg_conf * (0.6 + 0.4 * len(winners) / len(ok))))
    return "MAJORITY", chosen, votes


@api_router.get("/analysis/ai")
async def get_ai_signal(
    interval: str = Query("1h"),
    engine: str = Query("rule"),  # "rule" (free, default) or "ai" (dual-LLM)
    auto_upgrade: bool = Query(False),  # When engine=rule and signal is STRONG, auto-escalate to dual-LLM
    news_blackout: bool = Query(False),  # If True, override BUY/SELL to HOLD when inside a high-impact USD news window
    blackout_window: int = Query(15, ge=0, le=480),  # ± minutes around event (up to 8h for FOMC-day avoidance)
    with_risk_team: bool = Query(False),  # Only meaningful when engine="council" — adds Aggressive/Neutral/Conservative + Manager layer
    run_id: Optional[str] = Query(None),  # client id for live per-model progress polling
):
    # Multi-model runs can exceed Cloudflare's edge timeout — wrap in a whitespace heartbeat stream (valid JSON prefix).
    needs_streaming = engine in ("ai", "council") or auto_upgrade
    settings = await _load_ai_settings()

    cache_key = f"ai:{engine}:au{int(auto_upgrade)}:nb{int(news_blackout)}:bw{blackout_window}:rt{int(with_risk_team)}:{interval}:{settings.cache_tag()}"
    cached = _cache_get(cache_key, ttl_seconds=180 if engine in ("ai", "council") else 60)
    if cached:
        if needs_streaming:
            return StreamingResponse(
                iter([json.dumps(cached.model_dump() if hasattr(cached, "model_dump") else cached)]),
                media_type="application/json",
            )
        return cached

    if needs_streaming:
        async def heartbeat_stream():
            task = asyncio.create_task(_compute_ai_signal(
                interval=interval, engine=engine, auto_upgrade=auto_upgrade,
                news_blackout=news_blackout, blackout_window=blackout_window,
                with_risk_team=with_risk_team, cache_key=cache_key,
                settings=settings, run_id=run_id,
            ))
            try:
                while True:
                    try:
                        result = await asyncio.wait_for(asyncio.shield(task), timeout=8.0)
                        break
                    except asyncio.TimeoutError:
                        yield b" "  # heartbeat = leading whitespace; JSON tolerates it
            except Exception as e:
                logging.exception(f"Council+risk stream failed: {e}")
                err = {"detail": getattr(e, "detail", None) or str(e) or "AI computation failed"}
                yield json.dumps(err).encode()
                return
            try:
                payload = result.model_dump() if hasattr(result, "model_dump") else result
                yield json.dumps(payload).encode()
            except Exception as e:
                yield json.dumps({"detail": f"serialization failed: {e}"}).encode()

        return StreamingResponse(heartbeat_stream(), media_type="application/json")

    return await _compute_ai_signal(
        interval=interval, engine=engine, auto_upgrade=auto_upgrade,
        news_blackout=news_blackout, blackout_window=blackout_window,
        with_risk_team=with_risk_team, cache_key=cache_key,
        settings=settings, run_id=run_id,
    )


async def _compute_ai_signal(
    interval: str,
    engine: str,
    auto_upgrade: bool,
    news_blackout: bool,
    blackout_window: int,
    with_risk_team: bool,
    cache_key: str,
    settings: AISettings,
    run_id: Optional[str] = None,
) -> AISignal:
    models_used: List[str] = ["rule"]

    # Primary timeframe inputs
    snapshot = await get_indicators(interval=interval)
    candles_resp = await get_candles(interval=interval, size=120)

    # Multi-TF context
    higher_tf = TIMEFRAME_HIERARCHY.get(interval, ("4h", "1day"))[0]
    lower_tf_map = {
        "1min": "1min", "5min": "1min", "15min": "5min",
        "1h": "15min", "4h": "1h", "1day": "4h",
    }
    lower_tf = lower_tf_map.get(interval, "15min")
    higher_snap = await _safe_indicators(higher_tf) if higher_tf != interval else None
    lower_snap = await _safe_indicators(lower_tf) if lower_tf != interval else None

    # Macro & news context
    dxy = await _safe_dxy()
    news_titles = await _safe_news_titles(limit=10)
    news_items = await _safe_news_items(limit=8)
    macro = await _safe_macro()

    auto_upgraded = False
    council_debate: Optional[Dict[str, Any]] = None

    # ===== Branch on engine =====
    if engine == "rule":
        parsed = _rule_engine_analyze(
            snapshot, interval, higher_snap, lower_snap, dxy, news_titles,
            candles=candles_resp.get('candles'), macro=macro,
        )
        # Auto-upgrade: if user opted in and rule engine emitted a STRONG/VERY_STRONG signal,
        # escalate to the Dual-AI ensemble for cross-checked, higher-quality reasoning.
        rule_strength = str(parsed.get("signal_strength", "")).upper()
        rule_action = str(parsed.get("action", "HOLD")).upper()
        should_upgrade = (
            auto_upgrade
            and EMERGENT_LLM_KEY
            and rule_action in ("BUY", "SELL")
            and rule_strength in ("STRONG", "VERY_STRONG")
        )
        if should_upgrade:
            try:
                prompt = _build_strong_prompt(
                    snapshot=snapshot, interval=interval,
                    recent_candles=candles_resp['candles'],
                    higher_snap=higher_snap, lower_snap=lower_snap,
                    higher_tf=higher_tf, lower_tf=lower_tf,
                    dxy=dxy, news_titles=news_titles, macro=macro,
                )
                results = await _run_ensemble(prompt, settings, run_id)
                consensus_up, parsed_up, votes_up = _compute_consensus(results)
                if consensus_up != "FAILED" and parsed_up:
                    models_used = [v.engine_model for v in votes_up if v.available]
                    # Keep ATR-derived sl_method from rule pass for transparency
                    parsed_up.setdefault("sl_method", parsed.get("sl_method"))
                    parsed = parsed_up
                    votes = votes_up
                    consensus = consensus_up
                    auto_upgraded = True
                else:
                    votes = [AIVote(
                        model="AURUM Rule Engine",
                        model_id="rule",
                        action=parsed["action"],
                        confidence=parsed["confidence"],
                        summary=parsed["summary"],
                        available=True,
                    )]
                    consensus = "SINGLE_SOURCE"
            except Exception as up_err:
                logging.warning(f"Auto-upgrade to Deep AI failed, falling back to rule: {up_err}")
                votes = [AIVote(
                    model="AURUM Rule Engine",
                    model_id="rule",
                    action=parsed["action"],
                    confidence=parsed["confidence"],
                    summary=parsed["summary"],
                    available=True,
                )]
                consensus = "SINGLE_SOURCE"
        else:
            votes = [AIVote(
                model="AURUM Rule Engine",
                model_id="rule",
                action=parsed["action"],
                confidence=parsed["confidence"],
                summary=parsed["summary"],
                available=True,
            )]
            consensus = "SINGLE_SOURCE"
    elif engine == "council":
        if not EMERGENT_LLM_KEY:
            raise HTTPException(status_code=500, detail="LLM key not configured")
        # Always run the rule engine first to get an ATR-based baseline (entry/SL/TPs)
        baseline = _rule_engine_analyze(
            snapshot, interval, higher_snap, lower_snap, dxy, news_titles,
            candles=candles_resp.get('candles'), macro=macro,
        )
        base_prompt = _build_strong_prompt(
            snapshot=snapshot, interval=interval,
            recent_candles=candles_resp['candles'],
            higher_snap=higher_snap, lower_snap=lower_snap,
            higher_tf=higher_tf, lower_tf=lower_tf,
            dxy=dxy, news_titles=news_titles, macro=macro,
        )

        trader_verdict, bull, bear = await _run_council_debate(base_prompt, baseline, settings, run_id)
        if trader_verdict is None:
            raise HTTPException(status_code=502, detail="Council debate failed (one or more agents unavailable)")
        risk_outcome = await _run_risk_team(base_prompt, trader_verdict, settings, run_id) if with_risk_team else None
        role_ids = ["bull", "bear", "trader"] + (["aggressive", "neutral", "conservative", "manager"] if risk_outcome else [])
        models_used = list(dict.fromkeys(settings.roles[r] for r in role_ids))
        rl = lambda r: model_label(settings.roles[r])  # noqa: E731
        council_roles = {r: settings.roles[r] for r in role_ids}

        # Preserve ATR sl_method from baseline for transparency
        trader_verdict.setdefault("sl_method", baseline.get("sl_method"))
        parsed = trader_verdict

        votes = [
            AIVote(
                model=f"Bull Researcher · {rl('bull')}",
                model_id="bull", engine_model=settings.roles["bull"],
                action="BUY",
                confidence=int(bull.get("confidence_in_buy") or 50),
                summary=str(bull.get("thesis", ""))[:240],
                available=bool(bull),
            ),
            AIVote(
                model=f"Bear Researcher · {rl('bear')}",
                model_id="bear", engine_model=settings.roles["bear"],
                action="SELL",
                confidence=int(bear.get("confidence_in_sell") or 50),
                summary=str(bear.get("thesis", ""))[:240],
                available=bool(bear),
            ),
            AIVote(
                model=f"Head Trader · {rl('trader')}",
                model_id="trader", engine_model=settings.roles["trader"],
                action=str(trader_verdict.get("action", "HOLD")).upper(),
                confidence=int(trader_verdict.get("confidence") or 50),
                summary=str(trader_verdict.get("summary", ""))[:240],
                available=True,
            ),
        ]
        consensus = "COUNCIL_VERDICT"
        council_debate = {
            "roles": council_roles,
            "winner": str(trader_verdict.get("winner") or "TIE").upper(),
            "bull": {
                "stance": bull.get("stance"),
                "thesis": bull.get("thesis"),
                "key_points": bull.get("key_points") or [],
                "strongest_factor": bull.get("strongest_factor"),
                "weakness": bull.get("weakness_in_my_case"),
                "confidence_in_buy": bull.get("confidence_in_buy"),
            },
            "bear": {
                "stance": bear.get("stance"),
                "thesis": bear.get("thesis"),
                "rebuttals": bear.get("rebuttals") or [],
                "key_points": bear.get("key_points") or [],
                "strongest_factor": bear.get("strongest_factor"),
                "weakness": bear.get("weakness_in_my_case"),
                "confidence_in_sell": bear.get("confidence_in_sell"),
            },
        }

        # Optional Risk Team layer (TradingAgents-style) — `risk_outcome` already computed above
        if with_risk_team:
            if risk_outcome:
                mgr = risk_outcome["manager"]
                council_debate["risk_team"] = {
                    "aggressive": risk_outcome["aggressive"],
                    "neutral": risk_outcome["neutral"],
                    "conservative": risk_outcome["conservative"],
                    "manager": mgr,
                }

                # Manager has final authority. Adjust the signal accordingly.
                final_action = str(mgr.get("final_action") or trader_verdict.get("action") or "HOLD").upper()
                decision = str(mgr.get("decision") or "AUTHORIZE").upper()

                # Capture original (trader) values for transparency before overriding
                pre_action = str(parsed.get("action", "HOLD")).upper()

                # Apply manager overrides on prices when provided
                for k_src, k_dst in [
                    ("final_entry", "entry"),
                    ("final_sl", "stop_loss"),
                    ("final_tp1", "tp1"),
                    ("final_tp2", "tp2"),
                    ("final_tp3", "tp3"),
                ]:
                    v = mgr.get(k_src)
                    if isinstance(v, (int, float)) and v > 0:
                        parsed[k_dst] = float(v)

                # If manager rejected → override to HOLD with explanation; if modified → keep but flag
                if decision == "REJECT" or final_action == "HOLD":
                    parsed["action"] = "HOLD"
                    parsed["confidence"] = min(int(parsed.get("confidence", 50)), 40)
                    parsed["signal_strength"] = "WEAK"
                    parsed["summary"] = (
                        f"MANAGER REJECTED — Trader proposed {pre_action}. "
                        f"{(mgr.get('rationale') or '')[:200]}"
                    )
                else:
                    # Authorized (possibly modified). Surface the position size in reasoning + tilt info.
                    parsed["action"] = final_action
                    parsed["summary"] = (
                        f"AUTHORIZED · {final_action} · size {float(mgr.get('position_size_pct') or 0):.2f}% · "
                        f"tilt {str(mgr.get('tilt') or 'NEUTRAL').title()} — {(mgr.get('rationale') or '')[:160]}"
                    )

                # Add manager + risk roles to the votes list
                votes.extend([
                    AIVote(
                        model=f"Aggressive Risk · {rl('aggressive')}",
                        model_id="risk_aggressive", engine_model=settings.roles["aggressive"],
                        action=("BUY" if str(risk_outcome["aggressive"].get("vote")) == "APPROVE" and final_action == "BUY"
                                else "SELL" if str(risk_outcome["aggressive"].get("vote")) == "APPROVE" and final_action == "SELL"
                                else "HOLD"),
                        confidence=int(float(risk_outcome["aggressive"].get("recommended_size_pct") or 0) * 33),
                        summary=str(risk_outcome["aggressive"].get("stance", ""))[:240],
                        available=True,
                    ),
                    AIVote(
                        model=f"Neutral Risk · {rl('neutral')}",
                        model_id="risk_neutral", engine_model=settings.roles["neutral"],
                        action=("BUY" if str(risk_outcome["neutral"].get("vote")) == "APPROVE" and final_action == "BUY"
                                else "SELL" if str(risk_outcome["neutral"].get("vote")) == "APPROVE" and final_action == "SELL"
                                else "HOLD"),
                        confidence=int(float(risk_outcome["neutral"].get("recommended_size_pct") or 0) * 33),
                        summary=str(risk_outcome["neutral"].get("stance", ""))[:240],
                        available=True,
                    ),
                    AIVote(
                        model=f"Conservative Risk · {rl('conservative')}",
                        model_id="risk_conservative", engine_model=settings.roles["conservative"],
                        action=("BUY" if str(risk_outcome["conservative"].get("vote")) == "APPROVE" and final_action == "BUY"
                                else "SELL" if str(risk_outcome["conservative"].get("vote")) == "APPROVE" and final_action == "SELL"
                                else "HOLD"),
                        confidence=int(float(risk_outcome["conservative"].get("recommended_size_pct") or 0) * 33),
                        summary=str(risk_outcome["conservative"].get("stance", ""))[:240],
                        available=True,
                    ),
                    AIVote(
                        model=f"Portfolio Manager · {rl('manager')}",
                        model_id="manager", engine_model=settings.roles["manager"],
                        action=final_action,
                        confidence=int(parsed.get("confidence", 50)),
                        summary=str(mgr.get("rationale", ""))[:240],
                        available=True,
                    ),
                ])
                consensus = "MANAGER_AUTHORIZED" if decision != "REJECT" else "MANAGER_REJECTED"
    else:
        if not EMERGENT_LLM_KEY:
            raise HTTPException(status_code=500, detail="LLM key not configured")
        prompt = _build_strong_prompt(
            snapshot=snapshot, interval=interval,
            recent_candles=candles_resp['candles'],
            higher_snap=higher_snap, lower_snap=lower_snap,
            higher_tf=higher_tf, lower_tf=lower_tf,
            dxy=dxy, news_titles=news_titles, macro=macro,
        )
        results = await _run_ensemble(prompt, settings, run_id)
        consensus, parsed, votes = _compute_consensus(results)
        if consensus == "FAILED" or not parsed:
            raise HTTPException(status_code=502, detail="All selected AI models failed to respond")
        models_used = [v.engine_model for v in votes if v.available]

    def _opt_float(key):
        v = parsed.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _opt_int(key, default=None):
        v = parsed.get(key)
        try:
            return int(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    confidence = int(parsed.get('confidence', 50))
    signal_strength = str(parsed.get('signal_strength') or _compute_signal_strength_fallback(confidence)).upper()
    valid_for_minutes = _opt_int('valid_for_minutes', TIMEFRAME_EXPIRY_MIN.get(interval, 720))
    created_at = datetime.now(timezone.utc)
    expires_at = (created_at + timedelta(minutes=valid_for_minutes)).isoformat()

    tp1 = _opt_float('tp1')
    tp_legacy = _opt_float('take_profit')

    analysis_steps_raw = parsed.get('analysis_steps')
    analysis_steps = None
    if isinstance(analysis_steps_raw, dict):
        analysis_steps = {str(k): str(v) for k, v in analysis_steps_raw.items()}

    # ----- News-blackout override -----
    blackout_payload: Optional[Dict[str, Any]] = None
    final_action = str(parsed.get('action', 'HOLD')).upper()
    final_summary = str(parsed.get('summary', ''))
    final_reasoning = str(parsed.get('reasoning', ''))
    final_confidence = confidence

    if news_blackout:
        try:
            status = await _get_blackout_status(window_minutes=blackout_window)
        except Exception as bb_err:
            logging.warning(f"Blackout check failed: {bb_err}")
            status = {"in_blackout": False, "current_event": None, "next_event": None,
                      "window_minutes": blackout_window}
        blackout_payload = {**status, "filter_enabled": True}

        if status.get("in_blackout") and final_action in ("BUY", "SELL"):
            ev = status.get("current_event") or {}
            ev_title = ev.get("title") or "high-impact USD event"
            mins = ev.get("minutes_until")
            mins_txt = (
                f"in {abs(mins):.0f} min" if mins is not None and mins > 0
                else f"{abs(mins):.0f} min ago" if mins is not None else "now"
            )
            blackout_payload["overridden_from"] = final_action
            final_action = "HOLD"
            final_confidence = max(20, int(final_confidence * 0.5))
            final_summary = f"BLACKOUT — {ev_title} {mins_txt}. Original setup: {parsed.get('action')}."
            final_reasoning = (
                f"News-blackout filter active (±{blackout_window} min). "
                f"{ev_title} scheduled {mins_txt}; gold typically whipsaws. "
                f"Original analysis: {final_reasoning}"
            )
    else:
        blackout_payload = {"filter_enabled": False, "in_blackout": False}

    signal = AISignal(
        action=final_action,
        confidence=final_confidence,
        entry=float(parsed.get('entry', snapshot.price)),
        stop_loss=float(parsed.get('stop_loss', snapshot.price)),
        take_profit=float(tp_legacy if tp_legacy is not None else (tp1 if tp1 is not None else snapshot.price)),
        tp1=tp1 if tp1 is not None else tp_legacy,
        tp2=_opt_float('tp2'),
        tp3=_opt_float('tp3'),
        timeframe=interval,
        reasoning=final_reasoning,
        summary=final_summary,
        sentiment=str(parsed.get('sentiment', 'NEUTRAL')).upper(),
        indicators={
            'rsi': snapshot.rsi,
            'macd': snapshot.macd,
            'macd_signal': snapshot.macd_signal,
            'ema20': snapshot.ema20,
            'ema50': snapshot.ema50,
            'ema200': snapshot.ema200,
            'bb_upper': snapshot.bb_upper,
            'bb_mid': snapshot.bb_mid,
            'bb_lower': snapshot.bb_lower,
            'price': snapshot.price,
        },
        created_at=created_at.isoformat(),
        signal_strength=signal_strength,
        valid_for_minutes=valid_for_minutes,
        expires_at=expires_at,
        risk_reward=_opt_float('risk_reward'),
        higher_tf_trend=str(parsed.get('higher_tf_trend') or _trend_label(higher_snap)).upper(),
        lower_tf_momentum=str(parsed.get('lower_tf_momentum') or _trend_label(lower_snap)).upper(),
        news_sentiment=str(parsed.get('news_sentiment') or 'NEUTRAL').upper(),
        dxy_price=dxy['price'] if dxy else None,
        dxy_change_pct=dxy['percent_change'] if dxy else None,
        analysis_steps=analysis_steps,
        consensus=consensus,
        votes=votes,
        news_sources=[{'title': i.get('title', ''), 'source': i.get('source', ''), 'link': i.get('link', '')} for i in news_items],
        sl_method=parsed.get('sl_method'),
        auto_upgraded=auto_upgraded,
        news_blackout=blackout_payload,
        council_debate=council_debate,
        models_used=models_used,
        macro_context=macro,
    )

    await db.ai_signals.insert_one(signal.model_dump())
    payload = signal.model_dump()
    _cache_set(cache_key, payload)
    asyncio.create_task(_maybe_send_signal_alert(signal))
    return payload

# ------------------- AI model settings -------------------
async def _load_ai_settings() -> AISettings:
    doc = await db.ai_settings.find_one({"_id": "default"}, {"_id": 0})
    if not doc:
        return default_settings()
    try:
        return AISettings(**doc)
    except ValueError:
        return default_settings()


@api_router.get("/ai/models")
async def ai_models_catalog():
    return {
        "models": [{"id": k, **v} for k, v in MODEL_ROSTER.items()],
        "roles": [{"id": r, "label": label} for r, label in ROLES],
        "presets": PRESETS,
        "timeout_seconds": MODEL_TIMEOUT_SECONDS,
    }


@api_router.get("/ai/settings", response_model=AISettings)
async def get_ai_settings():
    return await _load_ai_settings()


@api_router.put("/ai/settings", response_model=AISettings)
async def update_ai_settings(payload: AISettings):
    await db.ai_settings.update_one({"_id": "default"}, {"$set": payload.model_dump()}, upsert=True)
    return payload


@api_router.get("/ai/progress/{run_id}")
async def ai_progress(run_id: str):
    return {"items": progress_get(run_id)}


@api_router.get("/signals/history")
async def signal_history(limit: int = Query(20, le=100)):
    docs = await db.ai_signals.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"signals": docs}


# ------------------- MT5 EA endpoints -------------------
class EAEvent(BaseModel):
    event: str  # OPENED / SCALED_OUT / MOVED_BE / CLOSED / ERROR
    signal_id: Optional[str] = ""
    ticket: Optional[int] = 0
    symbol: Optional[str] = "XAUUSD"
    action: Optional[str] = ""  # BUY / SELL
    lot: Optional[float] = 0
    price: Optional[float] = 0
    sl: Optional[float] = 0
    tp: Optional[float] = 0
    profit: Optional[float] = 0
    note: Optional[str] = ""


def _format_ea_event_message(e: EAEvent) -> str:
    sym = e.symbol or "XAUUSD"
    if e.event == "OPENED":
        action_emoji = "🟢" if e.action == "BUY" else "🔴"
        return (
            f"🤖 <b>EA · Trade OPENED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{action_emoji} <b>{e.action} {sym}</b>\n"
            f"📦 Lot: <b>{e.lot:.2f}</b>\n"
            f"💰 Entry: <code>{e.price:.2f}</code>\n"
            f"🛑 SL: <code>{e.sl:.2f}</code>\n"
            f"🎯 TP: <code>{e.tp:.2f}</code>\n"
            f"🎟 Ticket: #{e.ticket}"
        )
    if e.event == "SCALED_OUT":
        return (
            f"💰 <b>EA · TP1 Hit — Scaled Out 50%</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💎 Closed {e.lot:.2f} lots at <code>{e.price:.2f}</code>\n"
            f"💵 Locked profit: <b>${e.profit:+.2f}</b>\n"
            f"🎟 Ticket: #{e.ticket}"
        )
    if e.event == "MOVED_BE":
        return (
            f"🛡️ <b>EA · SL → Breakeven</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Position is now <b>risk-free</b>. Runner letting ride to TP3 🎯\n"
            f"🎟 Ticket: #{e.ticket}"
        )
    if e.event == "CLOSED":
        win = (e.profit or 0) >= 0
        emoji = "✅" if win else "❌"
        sign = "+" if win else ""
        return (
            f"{emoji} <b>EA · Position CLOSED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🎟 Ticket: #{e.ticket}\n"
            f"💱 Close price: <code>{e.price:.2f}</code>\n"
            f"💵 P/L: <b>{sign}${e.profit:.2f}</b>"
        )
    if e.event == "ERROR":
        return (
            f"⚠️ <b>EA · Error</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{e.note or 'Unknown error'}"
        )
    return f"📢 EA event: {e.event}"


@api_router.post("/ea/event")
async def ea_event(event: EAEvent):
    """Receive trade events from the EA. If signal_id matches a known thread,
    edit the original Telegram message to include the lifecycle event.
    Otherwise send a standalone message."""
    await db.ea_events.insert_one({
        **event.model_dump(),
        "received_at": datetime.now(timezone.utc).isoformat(),
    })

    cfg = await _get_telegram_config()
    if not (cfg.enabled and cfg.bot_token and cfg.chat_id):
        return {"ok": True}

    # Try to find an existing trade thread for this signal
    thread = None
    if event.signal_id:
        thread = await db.trade_threads.find_one({"signal_id": event.signal_id})

    field_map = {
        "OPENED": "opened",
        "SCALED_OUT": "scaled_out",
        "MOVED_BE": "moved_be",
        "CLOSED": "closed",
    }
    field = field_map.get(event.event)

    if thread and field:
        await db.trade_threads.update_one(
            {"signal_id": event.signal_id},
            {"$set": {field: event.model_dump()}},
        )
        thread = await db.trade_threads.find_one({"signal_id": event.signal_id})
        new_text = _render_combined_message(thread)
        await _edit_telegram_message(thread["message_id"], new_text)
    else:
        # No thread or unknown event type — fall back to standalone message
        text = _format_ea_event_message(event)
        await _send_telegram(text)

    return {"ok": True}


@api_router.get("/ea/signal")
async def ea_latest_signal(
    last_id: Optional[str] = Query(None),
    strength: str = Query("STRONG"),
    interval: Optional[str] = Query(None),
):
    """Latest fresh (non-expired, non-HOLD) signal for MT5 EA polling.
    Returns has_signal=false if no new signal since last_id."""
    query: Dict[str, Any] = {"action": {"$ne": "HOLD"}}
    if interval:
        query["timeframe"] = interval
    now_iso = datetime.now(timezone.utc).isoformat()
    query["expires_at"] = {"$gte": now_iso}

    if strength.upper() == "STRONG":
        query["consensus"] = {"$in": ["DOUBLE_CONFIRMED", "UNANIMOUS"]}
        query["signal_strength"] = {"$in": ["STRONG", "VERY_STRONG"]}

    signal = await db.ai_signals.find_one(query, {"_id": 0}, sort=[("created_at", -1)])
    if not signal:
        return {"has_signal": False}

    if last_id and signal.get("id") == last_id:
        return {"has_signal": False, "current_id": signal.get("id")}

    tp1 = signal.get("tp1") or signal.get("take_profit")
    return {
        "has_signal": True,
        "id": signal["id"],
        "action": signal["action"],
        "symbol": "XAUUSD",
        "timeframe": signal["timeframe"],
        "entry": signal["entry"],
        "stop_loss": signal["stop_loss"],
        "tp1": tp1,
        "tp2": signal.get("tp2"),
        "tp3": signal.get("tp3"),
        "confidence": signal["confidence"],
        "strength": signal.get("signal_strength"),
        "consensus": signal.get("consensus"),
        "created_at": signal["created_at"],
        "expires_at": signal["expires_at"],
    }


@api_router.get("/ea/download")
async def ea_download():
    """Serve the MT5 EA .mq5 file"""
    path = Path(__file__).parent / "static" / "AurumXAUUSD.mq5"
    if not path.exists():
        raise HTTPException(status_code=404, detail="EA file not found")
    return FileResponse(
        path=str(path),
        media_type="application/octet-stream",
        filename="AurumXAUUSD.mq5",
    )


# ------------------- Signal grading & stats -------------------
async def _grade_signal(signal_doc: dict) -> Optional[dict]:
    """Determine outcome of a past signal by walking historical candles.
    Returns dict of fields to persist, or None if signal cannot/should not be graded."""
    action = (signal_doc.get('action') or 'HOLD').upper()
    if action == 'HOLD':
        return None
    if signal_doc.get('outcome') in ('TP1', 'TP2', 'TP3', 'SL', 'EXPIRED', 'NO_DATA'):
        return None  # already graded

    created_str = signal_doc.get('created_at')
    expires_str = signal_doc.get('expires_at')
    if not created_str or not expires_str:
        return None
    try:
        created = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
        expires = datetime.fromisoformat(expires_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None

    now = datetime.now(timezone.utc)
    # Still active and within validity window
    if now < expires:
        return None

    interval = signal_doc.get('timeframe', '1h')
    try:
        candles_resp = await get_candles(interval=interval, size=500)
        all_candles = candles_resp.get('candles', [])
    except Exception:
        return None

    start_ts = int(created.timestamp())
    end_ts = int(expires.timestamp())
    window = [c for c in all_candles if start_ts <= c['time'] <= end_ts]
    if not window:
        # Outside cached range — mark NO_DATA so we don't re-try
        return {'outcome': 'NO_DATA', 'graded_at': now.isoformat()}

    try:
        entry = float(signal_doc['entry'])
        sl = float(signal_doc['stop_loss'])
    except (KeyError, ValueError, TypeError):
        return None

    tp1 = signal_doc.get('tp1') or signal_doc.get('take_profit')
    tp2 = signal_doc.get('tp2')
    tp3 = signal_doc.get('tp3')
    sl_dist = abs(entry - sl)
    if sl_dist <= 0:
        return None

    def _result(outcome: str, exit_price: float, exit_time: int, candle: dict):
        if action == 'BUY':
            r = (exit_price - entry) / sl_dist
        else:
            r = (entry - exit_price) / sl_dist
        return {
            'outcome': outcome,
            'r_multiple': round(r, 3),
            'exit_price': exit_price,
            'exit_time': exit_time,
            'graded_at': now.isoformat(),
        }

    for c in window:
        high, low = c['high'], c['low']
        if action == 'BUY':
            # Conservative: if both SL and TP touched in same candle, assume SL hit first
            if low <= sl:
                return _result('SL', sl, c['time'], c)
            if tp3 is not None and high >= float(tp3):
                return _result('TP3', float(tp3), c['time'], c)
            if tp2 is not None and high >= float(tp2):
                return _result('TP2', float(tp2), c['time'], c)
            if tp1 is not None and high >= float(tp1):
                return _result('TP1', float(tp1), c['time'], c)
        elif action == 'SELL':
            if high >= sl:
                return _result('SL', sl, c['time'], c)
            if tp3 is not None and low <= float(tp3):
                return _result('TP3', float(tp3), c['time'], c)
            if tp2 is not None and low <= float(tp2):
                return _result('TP2', float(tp2), c['time'], c)
            if tp1 is not None and low <= float(tp1):
                return _result('TP1', float(tp1), c['time'], c)

    # Expired without hitting TP or SL — use last close as exit
    last = window[-1]
    return _result('EXPIRED', last['close'], last['time'], last)


@api_router.get("/signals/stats")
async def signal_stats(model: Optional[str] = Query(None)):
    # Load all non-HOLD signals
    signals = await db.ai_signals.find(
        {"action": {"$ne": "HOLD"}}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)

    # Lazy-grade ungraded ones
    for s in signals:
        if not s.get('outcome'):
            updates = await _grade_signal(s)
            if updates:
                await db.ai_signals.update_one({'id': s['id']}, {'$set': updates})
                s.update(updates)

    graded = [s for s in signals if s.get('outcome') in ('TP1', 'TP2', 'TP3', 'SL', 'EXPIRED')]
    by_model_rows: Dict[str, List[dict]] = {}
    for s in graded:
        for m in (s.get('models_used') or []):
            by_model_rows.setdefault(m, []).append(s)
    if model:
        graded = by_model_rows.get(model, [])

    def _tally(rows: List[dict]) -> dict:
        wins = [r for r in rows if r.get('outcome', '').startswith('TP')]
        losses = [r for r in rows if r.get('outcome') == 'SL']
        expired = [r for r in rows if r.get('outcome') == 'EXPIRED']
        wl = len(wins) + len(losses)
        win_rate = (len(wins) / wl * 100) if wl else 0.0
        avg_r = (sum(r.get('r_multiple', 0) or 0 for r in rows) / len(rows)) if rows else 0.0
        return {
            'total': len(rows),
            'wins': len(wins),
            'losses': len(losses),
            'expired': len(expired),
            'win_rate': round(win_rate, 1),
            'avg_r': round(avg_r, 2),
        }

    overall = _tally(graded)

    by_tf: Dict[str, List[dict]] = {}
    for s in graded:
        by_tf.setdefault(s.get('timeframe', '?'), []).append(s)
    by_timeframe = [
        {'timeframe': tf, **_tally(rows)} for tf, rows in by_tf.items()
    ]
    by_timeframe.sort(key=lambda x: x['total'], reverse=True)

    now = datetime.now(timezone.utc)
    def _window(days: int):
        cutoff = now - timedelta(days=days)
        recent = [
            s for s in graded
            if datetime.fromisoformat(s['created_at'].replace('Z', '+00:00')) >= cutoff
        ]
        return {'period_days': days, **_tally(recent)}

    return {
        'overall': overall,
        'by_timeframe': by_timeframe,
        'period_7d': _window(7),
        'period_30d': _window(30),
        'best_streak': _best_streak(graded),
        'by_model': [{'model': m, **_tally(rows)} for m, rows in by_model_rows.items()],
        'model_filter': model,
    }


def _best_streak(rows: List[dict]) -> int:
    """Longest consecutive wins, looking at chronological order (oldest→newest)."""
    rows_sorted = sorted(rows, key=lambda r: r.get('created_at', ''))
    best, cur = 0, 0
    for r in rows_sorted:
        if (r.get('outcome') or '').startswith('TP'):
            cur += 1
            best = max(best, cur)
        elif r.get('outcome') == 'SL':
            cur = 0
    return best

@api_router.get("/news")
async def get_news(limit: int = Query(12, le=30)):
    items = await _fetch_all_news()
    return {"items": items[:limit]}

# ------------------- Economic Calendar / News Blackout -------------------
# ForexFactory weekly XML mirror — free, no auth. Times are Eastern Time (ET).
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
ET_TZ = ZoneInfo("America/New_York")

# Pairs that move XAU/USD most aggressively
GOLD_SENSITIVE_COUNTRIES = {"USD"}
# Even if marked "Medium", a few events historically whipsaw gold violently
HIGH_PRIORITY_TITLES = {
    "NFP", "Non-Farm", "FOMC", "CPI", "PPI", "Unemployment Rate",
    "Federal Funds Rate", "Fed Chair", "Powell",
}

def _parse_ff_event_time(date_str: str, time_str: str) -> Optional[datetime]:
    """ForexFactory format: date='MM-DD-YYYY', time='1:30am' / 'All Day' / 'Tentative'.
    Returns UTC datetime or None if non-scheduled."""
    if not date_str or not time_str:
        return None
    t = time_str.strip().lower()
    if t in ("all day", "tentative", "", "n/a"):
        return None
    try:
        # ForexFactory times are Eastern Time
        dt_naive = datetime.strptime(f"{date_str} {time_str}", "%m-%d-%Y %I:%M%p")
        return dt_naive.replace(tzinfo=ET_TZ).astimezone(timezone.utc)
    except ValueError:
        return None

async def _fetch_economic_calendar() -> List[dict]:
    """Fetch & parse ForexFactory weekly XML. Cached 30 min."""
    cached = _cache_get("ff_calendar", ttl_seconds=1800)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AurumTerminal/1.0)"},
        ) as http:
            r = await http.get(FF_CALENDAR_URL)
            r.raise_for_status()
            raw = r.content
    except Exception as e:
        logging.warning(f"ForexFactory fetch failed: {e}")
        stale = _cache_get_stale("ff_calendar") or []
        return stale

    events: List[dict] = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        logging.warning(f"ForexFactory XML parse failed: {e}")
        return []

    for node in root.findall("event"):
        def _t(tag):
            el = node.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""

        date_str = _t("date")
        time_str = _t("time")
        impact = _t("impact") or "Low"
        country = _t("country").upper()
        title = _t("title")
        when_utc = _parse_ff_event_time(date_str, time_str)

        events.append({
            "title": title,
            "country": country,
            "impact": impact,
            "forecast": _t("forecast"),
            "previous": _t("previous"),
            "url": _t("url"),
            "time_et": time_str,           # original ET label
            "date_et": date_str,
            "when_utc": when_utc.isoformat() if when_utc else None,
            "scheduled": when_utc is not None,
        })

    # Sort by time (None last)
    events.sort(key=lambda e: (e["when_utc"] is None, e["when_utc"] or ""))
    _cache_set("ff_calendar", events)
    return events

async def _safe_macro() -> Optional[Dict[str, Any]]:
    try:
        events = await _fetch_economic_calendar()
        return analyze_macro(events, datetime.now(timezone.utc), _is_gold_sensitive)
    except Exception as e:
        logging.warning(f"Macro calendar analysis failed: {e}")
        return None


@api_router.get("/calendar/macro")
async def get_macro_context():
    return await _safe_macro() or {"events": [], "gold_bias": "NEUTRAL", "event_risk": "LOW", "bias_score": 0}


def _is_gold_sensitive(ev: dict) -> bool:
    """High-impact USD events, OR any event whose title matches our priority list."""
    if ev.get("country") in GOLD_SENSITIVE_COUNTRIES and ev.get("impact") == "High":
        return True
    title = (ev.get("title") or "").lower()
    return any(kw.lower() in title for kw in HIGH_PRIORITY_TITLES) and ev.get("country") in GOLD_SENSITIVE_COUNTRIES

async def _get_blackout_status(window_minutes: int = 15) -> dict:
    """Returns blackout status for the current moment.
    in_blackout=True when a gold-sensitive event is within ±window_minutes."""
    events = await _fetch_economic_calendar()
    now = datetime.now(timezone.utc)
    relevant = [e for e in events if e.get("scheduled") and _is_gold_sensitive(e)]

    in_blackout = False
    current_event = None
    next_event = None
    min_until = None

    for e in relevant:
        try:
            when = datetime.fromisoformat(e["when_utc"])
        except (ValueError, TypeError):
            continue
        delta_min = (when - now).total_seconds() / 60.0

        # Inside blackout window (within ±window_minutes)
        if -window_minutes <= delta_min <= window_minutes:
            in_blackout = True
            current_event = {**e, "minutes_until": round(delta_min, 1)}

        # Next upcoming
        if delta_min > 0 and (min_until is None or delta_min < min_until):
            min_until = delta_min
            next_event = {**e, "minutes_until": round(delta_min, 1)}

    return {
        "in_blackout": in_blackout,
        "window_minutes": window_minutes,
        "current_event": current_event,
        "next_event": next_event,
        "now_utc": now.isoformat(),
    }

@api_router.get("/calendar/events")
async def get_calendar_events(
    country: Optional[str] = Query(None, description="Filter by country code, e.g. USD"),
    impact: Optional[str] = Query(None, description="Low | Medium | High"),
    only_scheduled: bool = Query(True),
    limit: int = Query(40, le=100),
):
    events = await _fetch_economic_calendar()
    if country:
        events = [e for e in events if e.get("country") == country.upper()]
    if impact:
        events = [e for e in events if e.get("impact", "").lower() == impact.lower()]
    if only_scheduled:
        events = [e for e in events if e.get("scheduled")]
    return {"items": events[:limit], "source": "ForexFactory"}

@api_router.get("/calendar/blackout")
async def get_blackout_status(window_minutes: int = Query(15, ge=0, le=480)):
    return await _get_blackout_status(window_minutes=window_minutes)

# ------------------- Telegram Alerts -------------------
class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    strong_only: bool = True  # legacy
    alert_mode: str = "strong"  # "strong" | "actionable" | "all"


async def _get_telegram_config() -> TelegramConfig:
    doc = await db.settings.find_one({"_id": "telegram"})
    if not doc:
        return TelegramConfig()
    # Back-compat: derive alert_mode from old strong_only if missing
    mode = doc.get('alert_mode')
    if not mode:
        mode = "strong" if doc.get('strong_only', True) else "actionable"
    return TelegramConfig(
        enabled=bool(doc.get('enabled', False)),
        bot_token=str(doc.get('bot_token', '')),
        chat_id=str(doc.get('chat_id', '')),
        strong_only=bool(doc.get('strong_only', True)),
        alert_mode=mode,
    )


async def _send_telegram(text: str, parse_mode: str = "HTML") -> dict:
    cfg = await _get_telegram_config()
    if not cfg.bot_token or not cfg.chat_id:
        return {"ok": False, "error": "Telegram not configured"}
    url = f"https://api.telegram.org/bot{cfg.bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.post(url, json={
                "chat_id": cfg.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            })
            data = r.json()
            if not data.get('ok'):
                return {"ok": False, "error": data.get('description', 'Unknown error')}
            return {"ok": True, "message_id": data['result']['message_id']}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


async def _edit_telegram_message(message_id: int, text: str, parse_mode: str = "HTML") -> dict:
    cfg = await _get_telegram_config()
    if not cfg.bot_token or not cfg.chat_id or not message_id:
        return {"ok": False, "error": "Missing config or message_id"}
    url = f"https://api.telegram.org/bot{cfg.bot_token}/editMessageText"
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.post(url, json={
                "chat_id": cfg.chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            })
            data = r.json()
            if not data.get('ok'):
                return {"ok": False, "error": data.get('description', 'Unknown')}
            return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _format_signal_message(signal: AISignal) -> str:
    action = signal.action.upper()
    emoji = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"
    consensus_emoji = {
        "DOUBLE_CONFIRMED": "✅ DOUBLE CONFIRMED",
        "UNANIMOUS": "✅ UNANIMOUS",
        "MAJORITY": "☑️ MAJORITY",
        "SINGLE_SOURCE": "⚠️ SINGLE SOURCE",
        "CONFLICTED": "⚡ CONFLICTED",
    }.get(signal.consensus or "", signal.consensus or "")

    def f(n, d=2):
        return f"{n:,.{d}f}" if n is not None else "—"

    tp_lines = []
    if signal.tp1 is not None:
        tp_lines.append(f"  TP1: <code>{f(signal.tp1)}</code>")
    if signal.tp2 is not None:
        tp_lines.append(f"  TP2: <code>{f(signal.tp2)}</code>")
    if signal.tp3 is not None:
        tp_lines.append(f"  TP3: <code>{f(signal.tp3)}</code>")
    tp_block = "\n".join(tp_lines) if tp_lines else f"  TP: <code>{f(signal.take_profit)}</code>"

    valid_str = f"{signal.valid_for_minutes}m" if signal.valid_for_minutes else "—"
    rr_str = f"{signal.risk_reward:.1f}" if signal.risk_reward else "—"

    return (
        f"{emoji} <b>{action} XAU/USD · {signal.signal_strength or ''}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Timeframe: <b>{signal.timeframe}</b>\n"
        f"🎯 Confidence: <b>{signal.confidence}%</b>\n"
        f"🤖 {consensus_emoji}\n\n"
        f"💰 Entry: <code>{f(signal.entry)}</code>\n"
        f"🛑 Stop Loss: <code>{f(signal.stop_loss)}</code>\n"
        f"{tp_block}\n\n"
        f"⚖️ R:R: <b>{rr_str}</b>\n"
        f"⏳ Valid: <b>{valid_str}</b>\n"
        f"💵 DXY: <code>{f(signal.dxy_price)} ({signal.dxy_change_pct:+.2f}%)</code>\n\n"
        f"<i>{signal.summary}</i>\n\n"
        f"<b>— AURUM Terminal</b>"
        if signal.dxy_price is not None else
        f"{emoji} <b>{action} XAU/USD · {signal.signal_strength or ''}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Timeframe: <b>{signal.timeframe}</b>\n"
        f"🎯 Confidence: <b>{signal.confidence}%</b>\n"
        f"🤖 {consensus_emoji}\n\n"
        f"💰 Entry: <code>{f(signal.entry)}</code>\n"
        f"🛑 Stop Loss: <code>{f(signal.stop_loss)}</code>\n"
        f"{tp_block}\n\n"
        f"⚖️ R:R: <b>{rr_str}</b>\n"
        f"⏳ Valid: <b>{valid_str}</b>\n\n"
        f"<i>{signal.summary}</i>\n\n"
        f"<b>— AURUM Terminal</b>"
    )


def _render_combined_message(thread: dict) -> str:
    """Render the full lifecycle message from accumulated state."""
    sig = thread.get("signal") or {}
    opened = thread.get("opened")
    scaled = thread.get("scaled_out")
    be = thread.get("moved_be")
    closed = thread.get("closed")

    action = sig.get("action", "")
    emoji = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"
    sym = "XAU/USD"

    def f(n, d=2):
        if n is None:
            return "—"
        return f"{n:,.{d}f}"

    lines = [
        f"{emoji} <b>{action} {sym} · {sig.get('signal_strength', '')}</b>",
        "━━━━━━━━━━━━━━━━━━━",
        f"📊 TF: <b>{sig.get('timeframe', '?')}</b>  ·  🎯 Confidence: <b>{sig.get('confidence', '?')}%</b>",
        f"🤖 Consensus: <b>{sig.get('consensus', '?')}</b>",
        "",
        f"💰 Entry: <code>{f(sig.get('entry'))}</code>",
        f"🛑 Stop Loss: <code>{f(sig.get('stop_loss'))}</code>",
    ]
    if sig.get("tp1") is not None:
        lines.append(f"   ├ TP1: <code>{f(sig['tp1'])}</code>")
    if sig.get("tp2") is not None:
        lines.append(f"   ├ TP2: <code>{f(sig['tp2'])}</code>")
    if sig.get("tp3") is not None:
        lines.append(f"   └ TP3: <code>{f(sig['tp3'])}</code>")

    rr = sig.get("risk_reward")
    valid = sig.get("valid_for_minutes")
    rr_str = f"{rr:.1f}" if rr else "—"
    extra_bits = [f"⚖️ R:R: <b>{rr_str}</b>"]
    if valid:
        extra_bits.append(f"⏳ Valid: <b>{valid}m</b>")
    if sig.get("dxy_price") is not None:
        extra_bits.append(f"💵 DXY: <code>{f(sig['dxy_price'])} ({sig.get('dxy_change_pct', 0):+.2f}%)</code>")
    lines.append(" · ".join(extra_bits))

    if sig.get("summary"):
        lines.extend(["", f"<i>{sig['summary']}</i>"])

    # EA trade lifecycle (only if any event happened)
    if opened or scaled or be or closed:
        lines.extend(["", "━ <b>EA TRADE LIFECYCLE</b> ━"])
        if opened:
            lines.append(
                f"🤖 <b>OPENED</b> · {f(opened.get('lot'))} lots @ <code>{f(opened.get('price'))}</code>"
                f" · 🎟 #{opened.get('ticket')}"
            )
        if scaled:
            lines.append(
                f"💰 <b>TP1 HIT</b> · closed {f(scaled.get('lot'))} lots @ <code>{f(scaled.get('price'))}</code>"
                f" · locked <b>${scaled.get('profit', 0):+.2f}</b>"
            )
        if be:
            lines.append("🛡️ <b>SL → Breakeven</b> · runner is risk-free")
        if closed:
            profit = closed.get('profit', 0) or 0
            win = profit >= 0
            emoji_c = "✅" if win else "❌"
            sign = "+" if win else ""
            lines.append(
                f"{emoji_c} <b>CLOSED</b> @ <code>{f(closed.get('price'))}</code> · "
                f"P/L: <b>{sign}${profit:.2f}</b>"
            )

    lines.extend(["", "<b>— AURUM Terminal</b>"])
    return "\n".join(lines)


async def _maybe_send_signal_alert(signal: AISignal) -> None:
    """Send Telegram alert if conditions are met, store as a trade thread for live updates."""
    try:
        cfg = await _get_telegram_config()
        if not cfg.enabled or not cfg.bot_token or not cfg.chat_id:
            return

        mode = cfg.alert_mode
        if mode == "strong":
            if signal.action == "HOLD":
                return
            if signal.consensus not in ("DOUBLE_CONFIRMED", "UNANIMOUS"):
                return
            if signal.signal_strength not in ("STRONG", "VERY_STRONG"):
                return
        elif mode == "actionable":
            if signal.action == "HOLD":
                return

        existing = await db.telegram_alerts.find_one({"signal_id": signal.id})
        if existing:
            return

        # Build initial combined-style message (no EA events yet)
        thread_doc = {"signal_id": signal.id, "signal": signal.model_dump()}
        text = _render_combined_message(thread_doc)
        result = await _send_telegram(text)

        await db.telegram_alerts.insert_one({
            "signal_id": signal.id,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "ok": result.get("ok", False),
            "error": result.get("error"),
            "mode": mode,
            "message_id": result.get("message_id"),
        })

        # Store thread for future EA event updates (only if message went through)
        if result.get("ok") and result.get("message_id"):
            await db.trade_threads.update_one(
                {"signal_id": signal.id},
                {"$set": {
                    "signal_id": signal.id,
                    "chat_id": cfg.chat_id,
                    "message_id": result["message_id"],
                    "signal": signal.model_dump(),
                    "opened": None,
                    "scaled_out": None,
                    "moved_be": None,
                    "closed": None,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True,
            )
    except Exception as e:
        logging.warning(f"Telegram auto-alert failed: {e}")


@api_router.get("/telegram/config")
async def get_telegram_config():
    cfg = await _get_telegram_config()
    masked = ""
    if cfg.bot_token:
        masked = cfg.bot_token[:8] + "…" + cfg.bot_token[-4:] if len(cfg.bot_token) > 14 else "•••"
    return {
        "enabled": cfg.enabled,
        "bot_token_masked": masked,
        "has_token": bool(cfg.bot_token),
        "chat_id": cfg.chat_id,
        "strong_only": cfg.strong_only,
        "alert_mode": cfg.alert_mode,
    }


class TelegramConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    strong_only: Optional[bool] = None
    alert_mode: Optional[str] = None


@api_router.post("/telegram/config")
async def update_telegram_config(payload: TelegramConfigUpdate):
    update = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    await db.settings.update_one(
        {"_id": "telegram"},
        {"$set": update},
        upsert=True,
    )
    return await get_telegram_config()


@api_router.post("/telegram/test")
async def telegram_send_test():
    cfg = await _get_telegram_config()
    if not cfg.bot_token or not cfg.chat_id:
        raise HTTPException(status_code=400, detail="Bot token and chat ID required")
    text = (
        "🟢 <b>AURUM Terminal · Test Message</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "If you see this, Telegram alerts are configured correctly.\n\n"
        "You'll receive a message like this each time a "
        "<b>STRONG + DOUBLE CONFIRMED</b> signal is generated.\n\n"
        "<i>Happy trading! 🚀</i>"
    )
    result = await _send_telegram(text)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error", "Send failed"))
    return result


@api_router.post("/telegram/send-ea")
async def telegram_send_ea():
    """Send the MT5 EA file to the configured Telegram chat."""
    cfg = await _get_telegram_config()
    if not cfg.bot_token or not cfg.chat_id:
        raise HTTPException(status_code=400, detail="Telegram not configured")
    path = Path(__file__).parent / "static" / "AurumXAUUSD.mq5"
    if not path.exists():
        raise HTTPException(status_code=404, detail="EA file not found")

    caption = (
        "🤖 <b>AURUM Terminal · MT5 Expert Advisor</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "<b>How to install:</b>\n"
        "1. Open MT5 on your PC\n"
        "2. <code>File → Open Data Folder → MQL5 → Experts</code>\n"
        "3. Drop this <code>.mq5</code> file there\n"
        "4. In MT5: Navigator → right-click Experts → <b>Refresh</b>\n"
        "5. Double-click <b>AurumXAUUSD</b> → set <code>InpApiUrl</code>\n"
        "6. ✅ Tick <b>Allow Algo Trading</b> → OK\n\n"
        "⚠️ Don't forget to whitelist the API URL in "
        "<code>Tools → Options → Expert Advisors → Allow WebRequest</code>\n\n"
        "<i>Test on demo first!</i>"
    )

    file_bytes = path.read_bytes()
    url = f"https://api.telegram.org/bot{cfg.bot_token}/sendDocument"
    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            files = {
                'document': ('AurumXAUUSD.mq5', file_bytes, 'application/octet-stream'),
            }
            data = {
                'chat_id': cfg.chat_id,
                'caption': caption,
                'parse_mode': 'HTML',
            }
            r = await http.post(url, data=data, files=files)
            result = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Telegram send failed: {str(e)[:200]}")

    if not result.get('ok'):
        raise HTTPException(status_code=502, detail=result.get('description', 'Send failed'))
    return {"ok": True, "message_id": result['result']['message_id']}
NEWS_QUERIES = [
    ("Gold Market", "gold+price+XAUUSD+OR+%22gold+market%22"),
    ("Fed / FOMC", "federal+reserve+OR+FOMC+rate+gold"),
    ("Central Banks", "central+bank+gold+buying+OR+reserves+PBoC+OR+RBI"),
    ("Macro / DXY", "US+dollar+DXY+inflation+OR+CPI+gold+impact"),
    ("Geopolitics", "geopolitical+OR+sanctions+OR+conflict+gold+safe-haven"),
]

async def _fetch_news_url(url: str, source_label: str, timeout: float = 8.0) -> List[dict]:
    try:
        async with httpx.AsyncClient(timeout=timeout, headers={'User-Agent': 'Mozilla/5.0'}) as http:
            r = await http.get(url)
            r.raise_for_status()
            feed = feedparser.parse(r.text)
    except Exception as e:
        logging.warning(f"News fetch failed for {source_label}: {e}")
        return []
    items = []
    for entry in feed.entries[:6]:
        items.append({
            'title': entry.get('title', ''),
            'link': entry.get('link', ''),
            'published': entry.get('published', ''),
            'source': source_label,
        })
    return items

async def _fetch_all_news() -> List[dict]:
    cached = _cache_get('all_news', ttl_seconds=600)
    if cached:
        return cached
    tasks = [
        _fetch_news_url(
            f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en",
            label,
        )
        for label, q in NEWS_QUERIES
    ]
    batches = await asyncio.gather(*tasks, return_exceptions=True)
    all_items: List[dict] = []
    seen = set()
    for b in batches:
        if isinstance(b, Exception) or not b:
            continue
        for item in b:
            t = (item.get('title') or '').strip().lower()
            if t and t not in seen:
                seen.add(t)
                all_items.append(item)
    _cache_set('all_news', all_items)
    return all_items

# Mount router
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
