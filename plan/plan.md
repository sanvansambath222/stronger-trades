# AURUM Terminal: Multi-Model AI Upgrade

An upgrade to the existing Tradestronger (AURUM Terminal) XAUUSD gold trading dashboard. The current Claude Sonnet 4.5 + Gemini 3.1 Pro setup is replaced with a choice of five newer AI models: Claude Opus 5.5, Sonnet 5.5, Haiku 5.5, GPT 5.5 and GPT 6 Luna. The chosen models vote on each Buy/Sell signal, and the user can pick which model plays each Council and Risk Team role.

## Who it's for
- The current owner of AURUM Terminal: a gold (XAUUSD) trader who wants stronger, cross-checked AI signals before trading or before letting the MT5 Expert Advisor trade.

## Core features and experience
- **AI model roster:** five models can be switched on or off: Claude Opus 5.5, Claude Sonnet 5.5, Claude Haiku 5.5, GPT 5.5 and GPT 6 Luna. Gemini is removed.
- **Default model:** Claude Opus 5.5 is the main model. It is on by default and leads the Head Trader and Portfolio Manager roles.
- **Ensemble voting (Deep AI mode):** every model that is switched on analyses the same chart, indicators, multi-timeframe trend, DXY and news. Each one returns BUY, SELL or HOLD with a confidence level, and the majority decides.
  - Consensus badges are extended for any number of models: UNANIMOUS, MAJORITY, CONFLICTED (tie, which gives HOLD) and SINGLE_SOURCE.
  - A per-model breakdown shows each model's vote, confidence and one-line reason. Models that failed or timed out are marked and do not count.
- **Role picker for Council mode:** a dropdown for each role lets the user choose which model plays it: Bull Researcher, Bear Researcher, Head Trader, the Aggressive, Neutral and Conservative risk roles, and Portfolio Manager.
- **Preset buttons:** "Max quality" (Opus everywhere), "Balanced" (Opus lead, Sonnet/GPT 5.5 researchers) and "Budget" (Haiku/GPT 6 Luna researchers, Sonnet lead).
- **Cost & speed hint:** before running, a small label shows roughly how many AI calls a signal will use and its expected speed (fast, medium or slow).
- **Saved settings:** the model choices and role assignments are remembered between visits and also apply to auto-upgrade signals and the signals sent to the MT5 EA.
- **Model column in signal history:** the history shows which models produced each signal. The win-rate stats can be filtered by model, so the user can see which AI performs best.
- **Kept as is:** the live chart, indicators, Rule Engine, ATR-based SL/TP, news blackout, economic calendar, Telegram alerts and the MT5 EA.

## User flow
1. Open the terminal and click the new **AI Models** button in the header.
2. Switch the models for the vote on or off, or tap a preset.
3. In the **Council Roles** tab, pick a model for each role.
4. Close the panel and press **Deep AI** or **Council**. The signal card shows the final verdict, the consensus badge and each model's vote.
5. Review the results in Signal History and in the per-model win-rate stats.

## UI/UX feel
- Same dark trader theme with gold accent as today. The new panel opens as a slide-over drawer.
- Each model has a small coloured tag: amber for Claude and teal for OpenAI. The tags appear on vote chips and role cards.
- Votes appear one by one as each model finishes, so long ensemble runs don't look frozen.

## Implementation phases
- **Phase 1 (MVP, built now):**
  - Five-model roster replaces Claude 4.5 and Gemini.
  - Majority voting for any number of models, with per-model votes shown.
  - Role picker for the Bull, Bear, Head Trader, Risk Team and Portfolio Manager roles, plus presets.
  - Settings are saved and used by auto-upgrade and the EA.
  - Model tags in signal history.
- **Phase 2:**
  - Per-model win-rate leaderboard and filters.
  - Confidence-weighted voting option, where Opus counts more.
  - Cost tracking per signal.
- **Phase 3:**
  - Auto-pick the best-performing model per timeframe based on past results.
  - Telegram messages that include the vote breakdown.
  - Multi-asset support (Silver, BTC, EUR/USD) using the same model setup.

## Assumptions
- The work is an upgrade to the existing Tradestronger code from GitHub, not a new app. Existing features stay unchanged.
- Gemini 3.1 Pro is removed because it was not selected. Signals already in history keep their old model labels.
- All models run on the Emergent Universal Key, so no personal API keys are needed. Each signal uses key balance, and the cost grows with the number of models switched on.
- Default vote set: Claude Opus 5.5, Claude Sonnet 5.5 and GPT 5.5. Haiku 5.5 and GPT 6 Luna are available but off by default.
- Default roles ("Balanced"): Bull is Claude Sonnet 5.5, Bear is GPT 5.5, and Head Trader and Portfolio Manager are Claude Opus 5.5. Aggressive is GPT 6 Luna, Neutral is Claude Sonnet 5.5 and Conservative is Claude Haiku 5.5.
- A model that doesn't answer within about 45 seconds is skipped, and the vote continues with the rest.
- A tie in the vote gives HOLD.
- With only one model switched on, the signal is labelled SINGLE_SOURCE.
- The dashboard stays public with no login, the same as today.
