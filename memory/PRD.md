# PRD — AURUM TERMINAL (XAUUSD Trading Analytics)

## Original Problem Statement
> how can you help me build trading XAUUSD buy or sell type web but like tradingview but strong Analye ??

## User Choices
- Data source: TwelveData (primary) + Yahoo Finance GC=F (fallback)
- Analysis: Rule Engine (free) + Dual-AI Ensemble (Claude Sonnet 4.5 + Gemini 3.1 Pro)
- Features: Live candlestick chart with timeframes, AI Buy/Sell signal w/ confidence, Technical indicators, News feed, Telegram alerts, MT5 EA auto-trader
- Auth: Public dashboard (no login)
- Visual: Dark professional trader theme (gold accent on near-black)
- AI: Claude Sonnet 4.5 + Gemini 3.1 Pro via Emergent Universal LLM Key

## Architecture
- **Frontend**: React + TailwindCSS + lightweight-charts + shadcn (sonner) on port 3000
- **Backend**: FastAPI on port 8001 with `/api` prefix
- **DB**: MongoDB for AI signal history + telegram config
- **External**: TwelveData (quote, time_series) + Yahoo Finance (fallback) + Claude + Gemini (LLM) + Google News RSS + Telegram Bot API

## Endpoints
- `GET /api/market/quote` — live XAU/USD quote
- `GET /api/market/candles?interval=1h&size=200` — OHLCV candles
- `GET /api/analysis/indicators?interval=1h` — RSI, MACD, EMA(20/50/200), Bollinger
- `GET /api/analysis/ai?interval=1h&engine=rule|ai&auto_upgrade=true|false` — signal + reasoning. Returns `sl_method` (ATR-derived or % fallback) and `auto_upgraded` flag.
- `GET /api/signals/history` — past signals
- `GET /api/signals/stats` — win rate, avg R-multiple, per-timeframe, 7d/30d windows, best streak
- `GET /api/news` — gold market news (Google News RSS)
- `GET /api/ea/signal`, `GET /api/ea/download`, `POST /api/ea/event` — MT5 Expert Advisor endpoints
- `POST /api/telegram/config`, `POST /api/telegram/test`, `POST /api/telegram/send-ea` — Telegram integration

## Implemented (Feb 2026)

### Phase 1 — Core (✅ Complete)
- ✅ Real-time XAU/USD ticker bar with tick-flash animations
- ✅ Candlestick chart (lightweight-charts) with 6 timeframes (1m, 5m, 15m, 1h, 4h, 1d)
- ✅ AI signal card with action (BUY/SELL/HOLD), confidence %, entry/SL/TP, verdict, reasoning
- ✅ Technical indicators panel (RSI gauge, MACD, EMAs vs price, Bollinger Bands)
- ✅ Signal history table (persisted in MongoDB)
- ✅ Gold market news feed (Google News RSS)
- ✅ Institutional dark theme (Chivo + JetBrains Mono fonts, gold accent)
- ✅ Auto-refresh (quote 20s, chart 30s, AI cached 60s/180s)

### Phase 2 — Intelligence (✅ Complete)
- ✅ Dual-AI Ensemble (Claude Sonnet 4.5 + Gemini 3.1 Pro) with consensus voting
- ✅ DOUBLE_CONFIRMED / MAJORITY / CONFLICTED / SINGLE_SOURCE consensus badges
- ✅ Multi-timeframe context (higher-TF trend + lower-TF momentum)
- ✅ DXY inverse-correlation factor + news headlines fed into AI prompt
- ✅ Free deterministic Rule Engine — no LLM cost, sub-second response

### Phase 3 — Performance Tracking (✅ Complete)
- ✅ Win-rate tracker (auto-grades past signals against historical candles)
- ✅ R-multiple, per-timeframe stats, 7d/30d windows, best streak

### Phase 4 — Alerting & Auto-Trading (✅ Complete)
- ✅ Telegram alerts (signal new, TP1/TP2/TP3 hit, SL hit) with bot setup modal
- ✅ MT5 Expert Advisor (AurumXAUUSD.mq5) — downloadable, polls /api/ea/signal, auto-executes BUY/SELL, reports lifecycle back via /api/ea/event
- ✅ Telegram lifecycle messages from EA reports

### Phase 5 — Volatility-Aware Risk (✅ Complete — Feb 22, 2026)
- ✅ ATR-based SL/TP calculation (replaces fixed % SL) — multipliers tuned per TF: 1m=1.0x, 5m=1.2x, 15m=1.4x, 1h=1.6x, 4h=1.8x, 1d=2.0x
- ✅ `sl_method` field surfaced in API + UI (shows "ATR(45.36) × 1.6" or "1.8% of price" fallback)
- ✅ TP ladder uses 1R/2R/3R from ATR-derived SL distance (proper risk-reward)
- ✅ **Auto-upgrade to Deep AI** toggle: free Rule Engine watches continuously, when it flags STRONG/VERY_STRONG → auto-escalates to Dual-AI (Claude + Gemini) for cross-checked verdict. Saves LLM tokens vs. continuous polling.
- ✅ **Strong-only filter** toggle: suppresses chart overlays + adds blocking warning when signal_strength ∉ {STRONG, VERY_STRONG} — prevents low-quality trades.
- ✅ Backend tests: 21 passed, 1 skipped (market-dependent). Test file at `/app/backend/tests/test_auto_upgrade.py`.
- 📈 **Real-world impact: win rate jumped from 0% → 47.1%** (31 graded signals after ATR rollout; 8-trade win streak; avg -0.07R vs. prior -0.83R).

### Phase 6 — News-Blackout Filter (✅ Complete — Feb 23, 2026)
- ✅ Free ForexFactory weekly XML feed (`https://nfs.faireconomy.media/ff_calendar_thisweek.xml`)
- ✅ 30-min cached economic-calendar service (`_fetch_economic_calendar`) with stale-fallback on network errors
- ✅ Eastern Time → UTC conversion via `zoneinfo.ZoneInfo('America/New_York')`
- ✅ Gold-sensitive detection: USD + High impact OR title contains FOMC/NFP/CPI/PPI/Powell/Fed-funds-rate keywords
- ✅ New endpoints: `GET /api/calendar/events?country=USD&impact=High&limit=40`, `GET /api/calendar/blackout?window_minutes=15`
- ✅ `/api/analysis/ai?news_blackout=true&blackout_window=15` overrides BUY/SELL → HOLD when inside ±N min of an event; halves confidence; summary prefixed `BLACKOUT —`; original signal preserved in `news_blackout.overridden_from`
- ✅ UI: News-Blackout toggle in header (default ON), red 2-border override banner in AI Signal card when active, ambient "Next USD event" gold pill when next event is within 4h
- ✅ Cache key includes `nb` and `bw` flags → no cache bleed between filter on/off
- ✅ blackout_window accepts 0-480 minutes (up to 8h — enough for FOMC-day full avoidance)
- ✅ Backend tests: 27/27 passed. Test file at `/app/backend/tests/test_news_blackout.py`.

### Phase 7 — Council Debate (Bull vs Bear vs Trader) (✅ Complete — Feb 23, 2026)
- ✅ TradingAgents-inspired 3-agent council on a new `engine="council"` mode
- ✅ Bull Researcher (Claude Sonnet 4.5) + Bear Researcher (Gemini 3.1 Pro) run in **parallel** → Head Trader (Claude Sonnet 4.5) synthesizes both into final verdict
- ✅ Parallelization keeps total latency at ~30-50s (safe under Cloudflare 100s edge timeout); 3 LLM calls per signal
- ✅ Returns full `council_debate` payload: bull thesis + key points + strongest factor + weakness, bear thesis + rebuttals + key points + strongest factor + weakness, plus `winner: BULL|BEAR|TIE`
- ✅ Frontend: 🏛 "Council" button (purple) next to Deep AI button; renders a beautiful collapsible "Council Debate" panel with green Bull card, red Bear card, and a winner badge
- ✅ ATR-based SL/TP preserved from rule baseline for transparency
- ✅ Cost: ~10-15¢ per call (3 LLM calls) — recommended for final go/no-go decisions before placing real trades

### Phase 8 — Full Risk Team Layer (TradingAgents architecture) (✅ Complete — Feb 23, 2026)
- ✅ Optional `with_risk_team=true` flag on `engine="council"` adds 3-role Risk Council + Portfolio Manager final authorization
- ✅ Roles: 🔥 **Aggressive** (push for full size on STRONG signals) · ⚖ **Neutral** (textbook 1-2% risk) · 🛡 **Conservative** (capital preservation, default HOLD)
- ✅ Each role votes APPROVE / APPROVE_REDUCED / REJECT with recommended position size %
- ✅ 👔 **Portfolio Manager** (Claude Sonnet 4.5) synthesizes votes → AUTHORIZE / AUTHORIZE_MODIFIED / REJECT with final position size, may tighten SL, references votes by name
- ✅ Manager decision rules: 2+ REJECTs → final REJECT; 1 REJECT → reduce size; size capped at 0-2% account risk
- ✅ Single combined LLM call (Bull ∥ Bear parallel → Combined Trader+Risk+Manager) — total 3 LLM calls in 3 stages
- ✅ Total latency ~50-58s through Cloudflare; uses **StreamingResponse with whitespace heartbeats** to keep connection alive past Cloudflare's 60s edge read-timeout
- ✅ Frontend: "+ Risk Team" header toggle; collapsible Risk Team panel showing 3 role cards + Manager box with Final Action / Size / Final SL / rationale / modifications
- ✅ Consensus label: `MANAGER_AUTHORIZED` or `MANAGER_REJECTED`
- ✅ Cost: ~15-20¢ per call (3 LLM calls) — use sparingly before final trade execution
- ✅ Live verification: Manager correctly split risk-team sizing (Aggressive 2.0% + Neutral 1.5% + Conservative 0.75% → final 1.25%) and tightened SL by 5.75 points to account for oversold bounce risk.
- 📈 **Win rate now 57.1%** overall (was 0% pre-ATR). **1h timeframe: 100% win rate (6W/0L, +0.72R avg)** — best performing horizon.

## Backlog (P1)
- Mobile responsive UI redesign (current desktop-first design breaks under 768px)
- Trailing-stop simulation (model break-even move after TP1 hits → realized R boost)
- Improve TwelveData 429-as-500 leak → graceful 429 with Retry-After or stale-cache fallback

## Backlog (P2)
- Multi-asset expansion (Silver, BTC, EUR/USD, Oil) reusing existing rule + AI engine
- Risk Calculator (compute position size in oz/lots from account size + risk %)
- WebSocket tick stream (replace 20s polling)
- Drawing tools on chart (trendlines, Fib retracements)
- Refactor `/app/backend/server.py` (1893 lines) into FastAPI routers: market, analysis, signals, ea, telegram

## Health
- Backend: ✅ Running, lint clean
- Frontend: ✅ Running, lint clean
- All endpoints tested end-to-end via testing agent (iteration_2.json: 100% pass rate on targeted features)


## Multi-Model AI Upgrade (Nov 2026)
User ask: "check this project all model of AI all" + "like CPI or anything make super stronger" (TwelveData key added).
- 5-model roster (Claude Opus 5.5 main, Sonnet 5.5, Haiku 5.5, GPT 5.5, GPT 6 Luna) replaces Claude 4.5 + Gemini — `backend/ai_models.py`
- Majority voting: UNANIMOUS / MAJORITY / CONFLICTED (tie→HOLD) / SINGLE_SOURCE; failed/timed-out (45s) models not counted
- Council roles each pick a model (bull, bear, trader, aggressive, neutral, conservative, manager); risk team now separate calls
- Presets Max quality / Balanced / Budget; settings saved in Mongo `ai_settings`, used by Deep AI, Council, auto-upgrade, EA
- Endpoints: GET /api/ai/models, GET/PUT /api/ai/settings, GET /api/ai/progress/{run_id}, GET /api/calendar/macro, /api/signals/stats?model=
- Live per-model progress in signal card; model tags in history; win-rate filter by model
- Macro calendar (CPI/NFP/FOMC/PCE… forecast vs previous → gold bias + event risk) feeds AI prompt + rule engine — `backend/macro_events.py`
- ForexFactory feed: 10-min backoff on failure + Mongo `calendar_cache` fallback

## Known issues
- Emergent LLM key returns "API key is inactive" → all AI calls fail (Rule Engine works). User needs to top up/activate Universal Key.
- ForexFactory currently rate-limits (429) → macro panel empty until feed recovers.

## Backlog
- P1: engine falls back to Rule on timeframe change / cancel stale requests; safe int parsing for LLM confidence; dedupe identical rule signals in history
- P2: per-model leaderboard, confidence-weighted voting, cost tracking per signal
- P3: auto-pick best model per timeframe, Telegram vote breakdown, multi-asset
