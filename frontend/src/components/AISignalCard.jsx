import { useEffect, useState } from "react";
import {
    TrendingUp, TrendingDown, Minus, Sparkles, RefreshCw, Loader2,
    Clock, Shield, Newspaper, DollarSign, Layers, Activity,
    CheckCircle2, AlertTriangle, XCircle, Bot, Zap, Scale, Gavel,
    Flame, ShieldCheck, Briefcase,
} from "lucide-react";
import { ModelTag, MODEL_META, ROLE_LABELS, estimateRun } from "@/lib/modelMeta";

function fmt(n, d = 2) {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    return Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

function formatDuration(ms) {
    if (ms <= 0) return "EXPIRED";
    const s = Math.floor(ms / 1000);
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${sec}s`;
    return `${sec}s`;
}

const actionStyle = {
    BUY: { color: "#00B86B", bg: "rgba(0,184,107,0.12)", Icon: TrendingUp, border: "#00B86B" },
    SELL: { color: "#FF2A55", bg: "rgba(255,42,85,0.12)", Icon: TrendingDown, border: "#FF2A55" },
    HOLD: { color: "#D4AF37", bg: "rgba(212,175,55,0.12)", Icon: Minus, border: "#D4AF37" },
};

const strengthStyle = {
    VERY_STRONG: { label: "VERY STRONG", color: "#00B86B", bg: "rgba(0,184,107,0.15)" },
    STRONG: { label: "STRONG", color: "#10B981", bg: "rgba(16,185,129,0.15)" },
    MODERATE: { label: "MODERATE", color: "#D4AF37", bg: "rgba(212,175,55,0.15)" },
    WEAK: { label: "WEAK", color: "#FF2A55", bg: "rgba(255,42,85,0.15)" },
};

const consensusStyle = {
    DOUBLE_CONFIRMED: { label: "DOUBLE CONFIRMED", color: "#00B86B", bg: "rgba(0,184,107,0.15)", Icon: CheckCircle2 },
    SINGLE_SOURCE: { label: "SINGLE SOURCE", color: "#D4AF37", bg: "rgba(212,175,55,0.12)", Icon: AlertTriangle },
    CONFLICTED: { label: "CONFLICTED", color: "#FF2A55", bg: "rgba(255,42,85,0.12)", Icon: XCircle },
    UNANIMOUS: { label: "UNANIMOUS", color: "#00B86B", bg: "rgba(0,184,107,0.15)", Icon: CheckCircle2 },
    MAJORITY: { label: "MAJORITY", color: "#7AB8FF", bg: "rgba(122,184,255,0.10)", Icon: CheckCircle2 },
};

function MacroPanel({ macro }) {
    if (!macro) return null;
    const riskColor = macro.event_risk === "HIGH" ? "#FF2A55" : macro.event_risk === "ELEVATED" ? "#D4AF37" : "#00B86B";
    const events = (macro.events || []).filter((e) => e.impact !== "Low").slice(0, 5);
    return (
        <div className="border border-[#262626] bg-[#0F0F0F] rounded-sm p-3" data-testid="macro-panel">
            <div className="flex items-center justify-between mb-2">
                <div className="text-[10px] font-mono text-[#D4AF37] uppercase tracking-[0.2em] flex items-center gap-1.5">
                    <Newspaper className="w-3 h-3" /> Macro Calendar · CPI / NFP / Fed
                </div>
                <div className="flex items-center gap-1.5 text-[9px] font-mono uppercase tracking-[0.1em]">
                    <span style={{ color: sentimentColor(macro.gold_bias) }} data-testid="macro-bias">Gold {macro.gold_bias}</span>
                    <span className="text-gray-600">·</span>
                    <span style={{ color: riskColor }} data-testid="macro-risk">Risk {macro.event_risk}</span>
                </div>
            </div>
            {events.length === 0 ? (
                <div className="text-[11px] text-gray-500">No high/medium-impact USD releases in the last 24h or next 48h.</div>
            ) : (
                <div className="space-y-1">
                    {events.map((e, i) => (
                        <div key={i} className="flex items-center justify-between gap-2 text-[11px]" data-testid={`macro-event-${i}`}>
                            <span className="text-gray-300 truncate">
                                <span className="font-mono text-[9px] mr-1" style={{ color: e.impact === "High" ? "#FF2A55" : "#D4AF37" }}>●</span>
                                {e.title}
                            </span>
                            <span className="font-mono text-[10px] text-gray-500 whitespace-nowrap">
                                {e.forecast || "—"} vs {e.previous || "—"} ·{" "}
                                <span style={{ color: sentimentColor(e.gold_bias) }}>{e.released ? "out" : `${(e.minutes_until / 60).toFixed(1)}h`}</span>
                            </span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

function LiveProgress({ items, engine }) {
    return (
        <div className="p-4" data-testid="ai-live-progress">
            <div className="flex items-center gap-2 mb-3">
                <Loader2 className="w-4 h-4 animate-spin text-[#D4AF37]" />
                <span className="text-xs font-mono text-gray-400 uppercase tracking-[0.2em]">
                    {engine === "council" ? "Council in session…" : "Models voting…"}
                </span>
            </div>
            {items.length === 0 && (
                <p className="text-[10px] font-mono text-gray-600 tracking-[0.15em]">Gathering chart, indicators, DXY & news…</p>
            )}
            <div className="space-y-1.5">
                {items.map((it, i) => (
                    <div
                        key={i}
                        className="flex items-center justify-between gap-2 px-2 py-1.5 border border-[#262626] bg-[#0A0A0A] rounded-sm vote-in"
                        style={{ animationDelay: `${i * 40}ms` }}
                        data-testid={`live-item-${i}`}
                    >
                        <div className="flex items-center gap-2 min-w-0">
                            <ModelTag id={it.engine_model} />
                            {it.kind === "role" && (
                                <span className="text-[10px] font-mono text-gray-400 uppercase tracking-[0.1em] truncate">{ROLE_LABELS[it.role]}</span>
                            )}
                        </div>
                        {it.available === false ? (
                            <span className="text-[10px] font-mono text-gray-500 uppercase">failed / timed out</span>
                        ) : it.kind === "vote" ? (
                            <span className="font-mono font-bold text-xs" style={{ color: voteActionColor(it.action) }}>
                                {it.action} · {it.confidence}%
                            </span>
                        ) : (
                            <CheckCircle2 className="w-3.5 h-3.5 text-[#00B86B]" />
                        )}
                    </div>
                ))}
            </div>
        </div>
    );
}

const voteActionColor = (a) =>
    a === "BUY" ? "#00B86B" : a === "SELL" ? "#FF2A55" : a === "N/A" ? "#737373" : "#D4AF37";

const sentimentColor = (s) =>
    s === "BULLISH" ? "#00B86B" : s === "BEARISH" ? "#FF2A55" : "#A3A3A3";

function CountdownBadge({ expiresAt }) {
    const [now, setNow] = useState(Date.now());
    useEffect(() => {
        const id = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(id);
    }, []);
    if (!expiresAt) return null;
    const exp = new Date(expiresAt).getTime();
    const remaining = exp - now;
    const expired = remaining <= 0;
    return (
        <div
            className="flex items-center gap-1.5 px-2 py-1 rounded-sm border font-mono text-[10px] uppercase tracking-[0.1em]"
            style={{
                color: expired ? "#FF2A55" : "#D4AF37",
                background: expired ? "rgba(255,42,85,0.1)" : "rgba(212,175,55,0.08)",
                borderColor: expired ? "rgba(255,42,85,0.4)" : "rgba(212,175,55,0.3)",
            }}
            data-testid="signal-expiry"
        >
            <Clock className="w-3 h-3" />
            {expired ? "Expired" : `Expires in ${formatDuration(remaining)}`}
        </div>
    );
}

function StepRow({ icon: Icon, title, text, testId }) {
    if (!text) return null;
    return (
        <div className="flex items-start gap-2 py-2 border-b border-[#262626]/60 last:border-b-0" data-testid={testId}>
            <Icon className="w-3.5 h-3.5 text-[#D4AF37] mt-0.5 shrink-0" />
            <div className="flex-1">
                <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.15em] mb-0.5">{title}</div>
                <div className="text-xs text-gray-200 leading-relaxed">{text}</div>
            </div>
        </div>
    );
}

export default function AISignalCard({ signal, loading, error, onRegenerate, onDeepAI, onCouncil, engine, aiSettings, withRiskTeam = false, liveProgress = [], confidenceThreshold = 0, strongOnly = false }) {
    const action = (signal?.action || "HOLD").toUpperCase();
    const style = actionStyle[action] || actionStyle.HOLD;
    const Icon = style.Icon;

    const tps = signal ? [
        { label: "TP1", v: signal.tp1 ?? signal.take_profit },
        { label: "TP2", v: signal.tp2 },
        { label: "TP3", v: signal.tp3 },
    ].filter((x) => x.v != null) : [];

    const strength = signal?.signal_strength ? strengthStyle[signal.signal_strength] : null;
    const consensus = signal?.consensus ? consensusStyle[signal.consensus] : null;
    const ConsensusIcon = consensus?.Icon;
    const belowThreshold = signal && signal.confidence < confidenceThreshold;
    const blockedByStrongFilter = signal
        && strongOnly
        && action !== "HOLD"
        && !["STRONG", "VERY_STRONG"].includes(signal.signal_strength);
    const muted = belowThreshold || blockedByStrongFilter;
    const steps = signal?.analysis_steps;
    const votes = signal?.votes || [];
    const newsSources = signal?.news_sources || [];
    const autoUpgraded = !!signal?.auto_upgraded;
    const slMethod = signal?.sl_method;
    const blackout = signal?.news_blackout;
    const inBlackout = !!blackout?.in_blackout;
    const nextEvent = blackout?.next_event;
    const overriddenFrom = blackout?.overridden_from;
    const council = signal?.council_debate;
    const isCouncil = engine === "council" || !!council;
    const nModels = votes.filter((v) => v.engine_model && MODEL_META[v.engine_model] && v.model_id !== "rule").length || aiSettings?.ensemble?.length || 0;
    const deepEst = estimateRun(aiSettings, "ai");
    const councilEst = estimateRun(aiSettings, "council", withRiskTeam);

    return (
        <div
            className="border border-[#262626] rounded-sm overflow-hidden relative"
            style={{ background: "linear-gradient(180deg, #141414 0%, #0F0F0F 100%)" }}
            data-testid="ai-signal-card"
        >
            <div className="flex items-center justify-between px-4 py-2 border-b border-[#262626]">
                <div className="flex items-center gap-2">
                    {isCouncil ? (
                        <>
                            <Scale className="w-3.5 h-3.5 text-[#A855F7]" />
                            <span className="text-[10px] font-mono text-[#A855F7] uppercase tracking-[0.2em]">
                                Council · Bull vs Bear vs Trader
                            </span>
                        </>
                    ) : engine === "ai" || autoUpgraded ? (
                        <>
                            <Sparkles className="w-3.5 h-3.5 text-[#D4AF37]" />
                            <span className="text-[10px] font-mono text-[#D4AF37] uppercase tracking-[0.2em]">
                                {autoUpgraded ? `Auto-Upgraded · ${nModels}-model vote` : `Deep AI · ${nModels}-model vote`}
                            </span>
                        </>
                    ) : (
                        <>
                            <Zap className="w-3.5 h-3.5 text-[#00B86B]" />
                            <span className="text-[10px] font-mono text-[#00B86B] uppercase tracking-[0.2em]">
                                Rule Engine · FREE
                            </span>
                        </>
                    )}
                </div>
                <div className="flex items-center gap-1.5">
                    {onCouncil && (
                        <button
                            onClick={onCouncil}
                            disabled={loading}
                            data-testid="council-btn"
                            title={councilEst ? `Bull vs Bear vs Trader debate · ~${councilEst.calls} AI calls · ${councilEst.speed}` : "Council debate"}
                            className="text-[10px] font-mono uppercase tracking-[0.1em] px-2 py-1 border border-[#A855F7]/50 text-[#A855F7] hover:bg-[#A855F7]/10 rounded-sm transition-colors disabled:opacity-50 flex items-center gap-1"
                        >
                            <Scale className="w-3 h-3" />
                            Council
                        </button>
                    )}
                    {onDeepAI && (
                        <button
                            onClick={onDeepAI}
                            disabled={loading}
                            data-testid="deep-ai-btn"
                            title={deepEst ? `Multi-model vote · ~${deepEst.calls} AI calls · ${deepEst.speed}` : "Multi-model vote"}
                            className="text-[10px] font-mono uppercase tracking-[0.1em] px-2 py-1 border border-[#D4AF37]/40 text-[#D4AF37] hover:bg-[#D4AF37]/10 rounded-sm transition-colors disabled:opacity-50 flex items-center gap-1"
                        >
                            <Sparkles className="w-3 h-3" />
                            Deep AI
                        </button>
                    )}
                    <button
                        onClick={onRegenerate}
                        disabled={loading}
                        data-testid="regen-ai-btn"
                        className="text-[10px] font-mono uppercase text-gray-400 hover:text-[#D4AF37] disabled:opacity-50 p-1"
                    >
                        {loading ? <Loader2 className="w-3 h-3 inline animate-spin" /> : <RefreshCw className="w-3 h-3 inline" />}
                    </button>
                </div>
            </div>

            {deepEst && councilEst && (
                <div className="px-4 py-1.5 border-b border-[#262626] flex items-center justify-between text-[9px] font-mono uppercase tracking-[0.12em] text-gray-500" data-testid="run-cost-hint">
                    <span>Deep AI · ~{deepEst.calls} calls · <span className="text-gray-300">{deepEst.speed}</span></span>
                    <span>Council · ~{councilEst.calls} calls · <span className="text-gray-300">{councilEst.speed}</span></span>
                </div>
            )}

            {error && (
                <div className="p-4 text-xs font-mono text-[#FF2A55]" data-testid="ai-error">
                    {error}
                </div>
            )}

            {!signal && !error && loading && <LiveProgress items={liveProgress} engine={engine} />}

            {signal && (
                <div className="p-4 space-y-4">
                    {/* News-blackout HARD warning (signal overridden) */}
                    {inBlackout && overriddenFrom && (
                        <div
                            className="px-3 py-2 border-2 border-[#FF2A55] bg-[#FF2A55]/15 rounded-sm text-[10px] font-mono uppercase tracking-[0.15em] text-[#FF2A55] flex items-start gap-2"
                            data-testid="blackout-override-banner"
                        >
                            <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                            <div>
                                <div className="font-bold">News blackout · {overriddenFrom} → HOLD</div>
                                {blackout?.current_event && (
                                    <div className="text-gray-300 normal-case tracking-normal mt-0.5">
                                        {blackout.current_event.title}
                                        {blackout.current_event.minutes_until != null && (
                                            <span className="text-[#FF2A55]">
                                                {" · "}
                                                {blackout.current_event.minutes_until > 0
                                                    ? `in ${Math.round(blackout.current_event.minutes_until)}m`
                                                    : `${Math.abs(Math.round(blackout.current_event.minutes_until))}m ago`}
                                            </span>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Ambient "next event" pill (only when NOT in blackout) */}
                    {!inBlackout && nextEvent && blackout?.filter_enabled && nextEvent.minutes_until <= 240 && (
                        <div
                            className="px-3 py-1.5 border border-[#D4AF37]/30 bg-[#D4AF37]/5 rounded-sm text-[10px] font-mono uppercase tracking-[0.15em] text-[#D4AF37] flex items-center gap-2"
                            data-testid="next-event-pill"
                        >
                            <Newspaper className="w-3 h-3" />
                            <span>Next USD event:</span>
                            <span className="text-white normal-case tracking-normal truncate">{nextEvent.title}</span>
                            <span className="ml-auto">
                                {nextEvent.minutes_until < 60
                                    ? `in ${Math.round(nextEvent.minutes_until)}m`
                                    : `in ${(nextEvent.minutes_until / 60).toFixed(1)}h`}
                            </span>
                        </div>
                    )}

                    {/* Auto-upgraded info banner */}
                    {autoUpgraded && (
                        <div
                            className="px-3 py-2 border border-[#D4AF37]/40 bg-[#D4AF37]/10 rounded-sm text-[10px] font-mono uppercase tracking-[0.15em] text-[#D4AF37] flex items-center gap-2"
                            data-testid="auto-upgrade-banner"
                        >
                            <Sparkles className="w-3 h-3" />
                            Rule engine flagged STRONG → auto-upgraded to multi-model AI vote
                        </div>
                    )}

                    {/* Below-threshold warning */}
                    {belowThreshold && (
                        <div
                            className="px-3 py-2 border border-[#FF2A55]/40 bg-[#FF2A55]/10 rounded-sm text-[10px] font-mono uppercase tracking-[0.15em] text-[#FF2A55]"
                            data-testid="below-threshold-warning"
                        >
                            ⚠ Below your {confidenceThreshold}% threshold — do not act.
                        </div>
                    )}

                    {/* Strong-only block warning */}
                    {blockedByStrongFilter && !belowThreshold && (
                        <div
                            className="px-3 py-2 border border-[#FF2A55]/40 bg-[#FF2A55]/10 rounded-sm text-[10px] font-mono uppercase tracking-[0.15em] text-[#FF2A55]"
                            data-testid="strong-only-warning"
                        >
                            ⚠ {signal.signal_strength?.replace("_", " ")} setup blocked by Strong-only filter — wait for STRONG signal.
                        </div>
                    )}

                    {/* Action + confidence */}
                    <div
                        className="flex items-center justify-between px-4 py-3 rounded-sm border"
                        style={{ background: style.bg, borderColor: style.border, opacity: muted ? 0.5 : 1 }}
                        data-testid="ai-action-display"
                    >
                        <div className="flex items-center gap-3">
                            <Icon className="w-7 h-7" style={{ color: style.color }} />
                            <div>
                                <div className="font-black tracking-tighter text-3xl" style={{ color: style.color }}>
                                    {action}
                                </div>
                                <div className="text-[10px] font-mono text-gray-400 uppercase tracking-[0.2em]">
                                    {signal.timeframe} · {signal.sentiment}
                                </div>
                            </div>
                        </div>
                        <div className="text-right">
                            <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em]">
                                Confidence
                            </div>
                            <div className="font-mono font-bold text-3xl" style={{ color: style.color }}>
                                {signal.confidence}%
                            </div>
                        </div>
                    </div>

                    {/* Strength badge + Expiry + R:R */}
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                        {strength && (
                            <div
                                className="flex items-center gap-1.5 px-2 py-1 rounded-sm border font-mono text-[10px] uppercase tracking-[0.1em]"
                                style={{ color: strength.color, background: strength.bg, borderColor: `${strength.color}55` }}
                                data-testid="signal-strength"
                            >
                                <Shield className="w-3 h-3" />
                                {strength.label}
                            </div>
                        )}
                        <CountdownBadge expiresAt={signal.expires_at} />
                        {signal.risk_reward != null && (
                            <div
                                className="flex items-center gap-1.5 px-2 py-1 rounded-sm border border-[#262626] font-mono text-[10px] uppercase tracking-[0.1em] text-gray-300"
                                data-testid="risk-reward"
                            >
                                <Activity className="w-3 h-3 text-[#D4AF37]" />
                                R:R {fmt(signal.risk_reward, 1)}
                            </div>
                        )}
                    </div>

                    {/* AI Consensus Panel */}
                    {(consensus || votes.length > 0) && (
                        <div
                            className="border rounded-sm p-3 space-y-2"
                            style={{
                                borderColor: consensus ? `${consensus.color}55` : "#262626",
                                background: consensus ? consensus.bg : "#0F0F0F",
                            }}
                            data-testid="ai-consensus-panel"
                        >
                            <div className="flex items-center justify-between">
                                <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-gray-500 flex items-center gap-1.5">
                                    <Bot className="w-3 h-3" /> AI Ensemble Consensus
                                </div>
                                {consensus && ConsensusIcon && (
                                    <div
                                        className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.15em] font-bold"
                                        style={{ color: consensus.color }}
                                        data-testid="consensus-badge"
                                    >
                                        <ConsensusIcon className="w-3.5 h-3.5" />
                                        {consensus.label}
                                    </div>
                                )}
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                                {votes.map((v) => (
                                    <div
                                        key={v.model_id}
                                        className={`p-2 rounded-sm border ${v.available ? "border-[#262626] bg-[#0A0A0A]" : "border-[#1A1A1A] bg-[#0A0A0A] opacity-50"}`}
                                        data-testid={`vote-${v.model_id}`}
                                    >
                                        <div className="flex items-center justify-between gap-1">
                                            <div className="text-[9px] font-mono text-gray-500 uppercase tracking-[0.1em] truncate">
                                                {v.model}
                                            </div>
                                            {v.engine_model && MODEL_META[v.engine_model] && v.model_id !== v.engine_model && (
                                                <ModelTag id={v.engine_model} />
                                            )}
                                        </div>
                                        <div className="flex items-baseline gap-2 mt-1">
                                            <span
                                                className="font-mono font-bold text-sm"
                                                style={{ color: voteActionColor(v.action) }}
                                            >
                                                {v.action}
                                            </span>
                                            {v.available && (
                                                <span className="font-mono text-xs text-gray-300">{v.confidence}%</span>
                                            )}
                                            {!v.available && (
                                                <span className="font-mono text-[9px] text-gray-500 uppercase">not counted</span>
                                            )}
                                        </div>
                                        {v.summary && v.available && (
                                            <div className="text-[10px] text-gray-400 leading-snug mt-1 line-clamp-2" data-testid={`vote-reason-${v.model_id}`}>
                                                {v.summary}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Entry & SL */}
                    <div className="grid grid-cols-2 gap-2">
                        <div className="bg-[#1A1A1A] border border-[#262626] p-2 rounded-sm">
                            <div className="text-[9px] font-mono text-gray-500 uppercase tracking-[0.15em]">Entry</div>
                            <div className="font-mono font-bold text-base text-white" data-testid="ai-entry">
                                {fmt(signal.entry)}
                            </div>
                        </div>
                        <div className="bg-[#1A1A1A] border border-[#262626] p-2 rounded-sm">
                            <div className="text-[9px] font-mono text-[#FF2A55] uppercase tracking-[0.15em]">Stop Loss</div>
                            <div className="font-mono font-bold text-base text-[#FF2A55]" data-testid="ai-sl">
                                {fmt(signal.stop_loss)}
                            </div>
                        </div>
                    </div>

                    {slMethod && (
                        <div
                            className="text-[9px] font-mono text-gray-500 uppercase tracking-[0.15em] -mt-2"
                            data-testid="sl-method"
                            title="Volatility-aware SL distance source"
                        >
                            SL distance · <span className="text-[#D4AF37]">{slMethod}</span>
                        </div>
                    )}

                    {/* TP ladder */}
                    {tps.length > 0 && (
                        <div className={`grid gap-2 ${tps.length === 3 ? "grid-cols-3" : tps.length === 2 ? "grid-cols-2" : "grid-cols-1"}`}>
                            {tps.map((tp) => (
                                <div
                                    key={tp.label}
                                    className="bg-[#0F1F15] border border-[#00B86B]/30 p-2 rounded-sm"
                                    data-testid={`ai-${tp.label.toLowerCase()}`}
                                >
                                    <div className="text-[9px] font-mono text-[#00B86B] uppercase tracking-[0.15em]">
                                        {tp.label}
                                    </div>
                                    <div className="font-mono font-bold text-sm text-[#00B86B]">{fmt(tp.v)}</div>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Confluence row: HTF / LTF / News / DXY */}
                    <div className="grid grid-cols-2 gap-2 pt-1">
                        <div className="bg-[#0F0F0F] border border-[#262626] p-2 rounded-sm" data-testid="confluence-htf">
                            <div className="text-[9px] font-mono text-gray-500 uppercase tracking-[0.15em] flex items-center gap-1">
                                <Layers className="w-3 h-3" /> Higher TF
                            </div>
                            <div className="font-mono font-bold text-xs mt-1" style={{ color: sentimentColor(signal.higher_tf_trend) }}>
                                {signal.higher_tf_trend || "—"}
                            </div>
                        </div>
                        <div className="bg-[#0F0F0F] border border-[#262626] p-2 rounded-sm" data-testid="confluence-ltf">
                            <div className="text-[9px] font-mono text-gray-500 uppercase tracking-[0.15em] flex items-center gap-1">
                                <Layers className="w-3 h-3" /> Lower TF
                            </div>
                            <div className="font-mono font-bold text-xs mt-1" style={{ color: sentimentColor(signal.lower_tf_momentum) }}>
                                {signal.lower_tf_momentum || "—"}
                            </div>
                        </div>
                        <div className="bg-[#0F0F0F] border border-[#262626] p-2 rounded-sm" data-testid="confluence-news">
                            <div className="text-[9px] font-mono text-gray-500 uppercase tracking-[0.15em] flex items-center gap-1">
                                <Newspaper className="w-3 h-3" /> News
                            </div>
                            <div className="font-mono font-bold text-xs mt-1" style={{ color: sentimentColor(signal.news_sentiment) }}>
                                {signal.news_sentiment || "—"}
                            </div>
                        </div>
                        <div className="bg-[#0F0F0F] border border-[#262626] p-2 rounded-sm" data-testid="confluence-dxy">
                            <div className="text-[9px] font-mono text-gray-500 uppercase tracking-[0.15em] flex items-center gap-1">
                                <DollarSign className="w-3 h-3" /> DXY
                            </div>
                            <div className="font-mono font-bold text-xs mt-1 text-white">
                                {signal.dxy_price != null
                                    ? `${fmt(signal.dxy_price)} (${signal.dxy_change_pct >= 0 ? "+" : ""}${fmt(signal.dxy_change_pct, 2)}%)`
                                    : "n/a"}
                            </div>
                        </div>
                    </div>

                    <MacroPanel macro={signal.macro_context} />

                    {/* Verdict & reasoning */}
                    <div>
                        <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em] mb-1">Verdict</div>
                        <div className="text-sm text-white font-medium leading-snug" data-testid="ai-summary">
                            {signal.summary}
                        </div>
                    </div>

                    {/* Council Debate transcript */}
                    {council && (
                        <CouncilDebate council={council} />
                    )}

                    {/* Risk Team (Aggressive / Neutral / Conservative + Manager) */}
                    {council?.risk_team && (
                        <RiskTeamPanel riskTeam={council.risk_team} roles={council.roles} />
                    )}

                    {/* Analysis steps */}
                    {steps && (
                        <div className="border-t border-[#262626] pt-3">
                            <div className="text-[10px] font-mono text-[#D4AF37] uppercase tracking-[0.2em] mb-1">
                                Multi-Factor Breakdown
                            </div>
                            <div className="divide-y divide-[#262626]/60">
                                <StepRow icon={Layers} title="Trend" text={steps.trend} testId="step-trend" />
                                <StepRow icon={Activity} title="Momentum" text={steps.momentum} testId="step-momentum" />
                                <StepRow icon={Newspaper} title="News" text={steps.news} testId="step-news" />
                                <StepRow icon={DollarSign} title="Macro" text={steps.macro} testId="step-macro" />
                                <StepRow icon={Sparkles} title="Verdict" text={steps.verdict} testId="step-verdict" />
                            </div>
                        </div>
                    )}

                    {!steps && signal.reasoning && (
                        <div>
                            <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em] mb-1">Reasoning</div>
                            <div className="text-xs text-gray-300 leading-relaxed" data-testid="ai-reasoning">
                                {signal.reasoning}
                            </div>
                        </div>
                    )}

                    {/* News sources fed into analysis */}
                    {newsSources.length > 0 && (
                        <div className="border-t border-[#262626] pt-3" data-testid="news-sources-panel">
                            <div className="text-[10px] font-mono text-[#D4AF37] uppercase tracking-[0.2em] mb-2 flex items-center gap-1.5">
                                <Newspaper className="w-3 h-3" /> World-Trade Intel ({newsSources.length} sources)
                            </div>
                            <div className="space-y-1.5 max-h-48 overflow-y-auto">
                                {newsSources.slice(0, 8).map((n, i) => (
                                    <a
                                        key={i}
                                        href={n.link}
                                        target="_blank"
                                        rel="noreferrer"
                                        className="block text-xs text-gray-300 hover:text-[#D4AF37] leading-snug transition-colors"
                                        data-testid={`source-item-${i}`}
                                    >
                                        <span className="text-[9px] font-mono text-gray-600 uppercase tracking-[0.1em] mr-1">
                                            [{n.source || "news"}]
                                        </span>
                                        {n.title}
                                    </a>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

function CouncilDebate({ council }) {
    const [open, setOpen] = useState(true);
    const bull = council?.bull || {};
    const bear = council?.bear || {};
    const winner = (council?.winner || "TIE").toUpperCase();
    const winnerStyle = winner === "BULL"
        ? { fg: "#00B86B", label: "Bull wins" }
        : winner === "BEAR"
            ? { fg: "#FF2A55", label: "Bear wins" }
            : { fg: "#D4AF37", label: "Stalemate" };

    return (
        <div className="border-t border-[#262626] pt-3" data-testid="council-debate-panel">
            <button
                onClick={() => setOpen((o) => !o)}
                className="w-full flex items-center justify-between mb-2 group"
                data-testid="council-toggle"
            >
                <div className="text-[10px] font-mono text-[#A855F7] uppercase tracking-[0.2em] flex items-center gap-1.5">
                    <Gavel className="w-3 h-3" />
                    Council Debate
                </div>
                <div className="flex items-center gap-2">
                    <span
                        className="text-[10px] font-mono uppercase tracking-[0.15em] px-1.5 py-0.5 rounded-sm"
                        style={{ color: winnerStyle.fg, border: `1px solid ${winnerStyle.fg}55` }}
                        data-testid="council-winner-badge"
                    >
                        {winnerStyle.label}
                    </span>
                    <span className="text-[10px] font-mono text-gray-500 group-hover:text-[#A855F7]">
                        {open ? "−" : "+"}
                    </span>
                </div>
            </button>

            {open && (
                <div className="space-y-2">
                    {/* BULL */}
                    <div
                        className="border border-[#00B86B]/30 bg-[#00B86B]/5 rounded-sm p-2.5"
                        data-testid="council-bull-card"
                    >
                        <div className="flex items-center justify-between mb-1.5">
                            <div className="text-[10px] font-mono text-[#00B86B] uppercase tracking-[0.2em] flex items-center gap-1">
                                <TrendingUp className="w-3 h-3" /> Bull Researcher
                                {council?.roles?.bull && <ModelTag id={council.roles.bull} />}
                            </div>
                            {bull.confidence_in_buy != null && (
                                <span className="text-[10px] font-mono text-[#00B86B]" data-testid="council-bull-conf">
                                    Conf BUY · {bull.confidence_in_buy}%
                                </span>
                            )}
                        </div>
                        {bull.thesis && (
                            <p className="text-xs text-gray-300 leading-snug mb-1.5">{bull.thesis}</p>
                        )}
                        {(bull.key_points || []).length > 0 && (
                            <ul className="text-[11px] text-gray-400 space-y-1 list-disc list-inside leading-snug">
                                {bull.key_points.slice(0, 4).map((p, i) => (
                                    <li key={i}>{p}</li>
                                ))}
                            </ul>
                        )}
                        {bull.strongest_factor && (
                            <div className="text-[10px] font-mono text-[#00B86B]/70 mt-1.5 italic">
                                ★ {bull.strongest_factor}
                            </div>
                        )}
                    </div>

                    {/* BEAR */}
                    <div
                        className="border border-[#FF2A55]/30 bg-[#FF2A55]/5 rounded-sm p-2.5"
                        data-testid="council-bear-card"
                    >
                        <div className="flex items-center justify-between mb-1.5">
                            <div className="text-[10px] font-mono text-[#FF2A55] uppercase tracking-[0.2em] flex items-center gap-1">
                                <TrendingDown className="w-3 h-3" /> Bear Researcher
                                {council?.roles?.bear && <ModelTag id={council.roles.bear} />}
                            </div>
                            {bear.confidence_in_sell != null && (
                                <span className="text-[10px] font-mono text-[#FF2A55]" data-testid="council-bear-conf">
                                    Conf SELL · {bear.confidence_in_sell}%
                                </span>
                            )}
                        </div>
                        {bear.thesis && (
                            <p className="text-xs text-gray-300 leading-snug mb-1.5">{bear.thesis}</p>
                        )}
                        {(bear.rebuttals || []).length > 0 && (
                            <>
                                <div className="text-[9px] font-mono text-[#FF2A55]/80 uppercase tracking-[0.15em] mt-1.5 mb-1">
                                    Rebuttals to bull
                                </div>
                                <ul className="text-[11px] text-gray-400 space-y-1 list-disc list-inside leading-snug">
                                    {bear.rebuttals.slice(0, 4).map((r, i) => (
                                        <li key={i}>{r}</li>
                                    ))}
                                </ul>
                            </>
                        )}
                        {bear.strongest_factor && (
                            <div className="text-[10px] font-mono text-[#FF2A55]/70 mt-1.5 italic">
                                ★ {bear.strongest_factor}
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}


const VOTE_STYLE = {
    APPROVE: { fg: "#00B86B", label: "APPROVE" },
    APPROVE_REDUCED: { fg: "#D4AF37", label: "APPROVE (REDUCED)" },
    REJECT: { fg: "#FF2A55", label: "REJECT" },
};

const DECISION_STYLE = {
    AUTHORIZE: { fg: "#00B86B", border: "#00B86B", bg: "rgba(0,184,107,0.08)", label: "AUTHORIZED" },
    AUTHORIZE_MODIFIED: { fg: "#D4AF37", border: "#D4AF37", bg: "rgba(212,175,55,0.08)", label: "AUTHORIZED (MODIFIED)" },
    REJECT: { fg: "#FF2A55", border: "#FF2A55", bg: "rgba(255,42,85,0.10)", label: "REJECTED" },
};

const ROLE_META = {
    aggressive: { icon: Flame, fg: "#FF8A33", label: "Aggressive" },
    neutral: { icon: Scale, fg: "#7AB8FF", label: "Neutral" },
    conservative: { icon: ShieldCheck, fg: "#5BE3C7", label: "Conservative" },
};

function RiskRoleCard({ role, data, modelId }) {
    const meta = ROLE_META[role] || { icon: Shield, fg: "#999", label: role };
    const Icon = meta.icon;
    const voteStyle = VOTE_STYLE[String(data?.vote || "").toUpperCase()] || VOTE_STYLE.APPROVE_REDUCED;
    return (
        <div
            className="border rounded-sm p-2.5"
            style={{ borderColor: `${meta.fg}40`, background: `${meta.fg}0D` }}
            data-testid={`risk-${role}-card`}
        >
            <div className="flex items-center justify-between mb-1.5 gap-2">
                <div className="text-[10px] font-mono uppercase tracking-[0.15em] flex items-center gap-1" style={{ color: meta.fg }}>
                    <Icon className="w-3 h-3" /> {meta.label} {modelId && <ModelTag id={modelId} />}
                </div>
                <span
                    className="text-[10px] font-mono uppercase tracking-[0.1em] px-1.5 py-0.5 rounded-sm whitespace-nowrap"
                    style={{ color: voteStyle.fg, border: `1px solid ${voteStyle.fg}55` }}
                    data-testid={`risk-${role}-vote`}
                >
                    {voteStyle.label} · {Number(data?.recommended_size_pct || 0).toFixed(1)}%
                </span>
            </div>
            {data?.stance && (
                <p className="text-xs text-gray-300 leading-snug mb-1.5">{data.stance}</p>
            )}
            {(data?.key_concerns || []).length > 0 && (
                <ul className="text-[11px] text-gray-400 space-y-1 list-disc list-inside leading-snug">
                    {data.key_concerns.slice(0, 3).map((c, i) => (
                        <li key={i}>{c}</li>
                    ))}
                </ul>
            )}
            {data?.size_rationale && (
                <div className="text-[10px] font-mono mt-1.5 italic" style={{ color: `${meta.fg}b3` }}>
                    ★ {data.size_rationale}
                </div>
            )}
        </div>
    );
}

function RiskTeamPanel({ riskTeam, roles = {} }) {
    const [open, setOpen] = useState(true);
    const mgr = riskTeam?.manager || {};
    const decisionKey = String(mgr.decision || "AUTHORIZE").toUpperCase();
    const ds = DECISION_STYLE[decisionKey] || DECISION_STYLE.AUTHORIZE;

    return (
        <div className="border-t border-[#262626] pt-3" data-testid="risk-team-panel">
            <button
                onClick={() => setOpen((o) => !o)}
                className="w-full flex items-center justify-between mb-2 group"
                data-testid="risk-team-toggle-btn"
            >
                <div className="text-[10px] font-mono uppercase tracking-[0.2em] flex items-center gap-1.5" style={{ color: ds.fg }}>
                    <Briefcase className="w-3 h-3" />
                    Risk Team · Manager
                </div>
                <div className="flex items-center gap-2">
                    <span
                        className="text-[10px] font-mono uppercase tracking-[0.15em] px-1.5 py-0.5 rounded-sm font-bold"
                        style={{ color: ds.fg, border: `1px solid ${ds.fg}`, background: ds.bg }}
                        data-testid="manager-decision-badge"
                    >
                        {ds.label}
                    </span>
                    <span className="text-[10px] font-mono text-gray-500 group-hover:text-white">
                        {open ? "−" : "+"}
                    </span>
                </div>
            </button>

            {open && (
                <div className="space-y-2">
                    <RiskRoleCard role="aggressive" data={riskTeam.aggressive} modelId={roles.aggressive} />
                    <RiskRoleCard role="neutral" data={riskTeam.neutral} modelId={roles.neutral} />
                    <RiskRoleCard role="conservative" data={riskTeam.conservative} modelId={roles.conservative} />

                    {/* Manager box */}
                    <div
                        className="border-2 rounded-sm p-3"
                        style={{ borderColor: ds.border, background: ds.bg }}
                        data-testid="manager-card"
                    >
                        <div className="flex items-center justify-between mb-2 gap-2">
                            <div className="text-[10px] font-mono uppercase tracking-[0.2em] flex items-center gap-1.5" style={{ color: ds.fg }}>
                                <Gavel className="w-3.5 h-3.5" /> Portfolio Manager {roles.manager && <ModelTag id={roles.manager} />}
                            </div>
                            {mgr.tilt && (
                                <span className="text-[10px] font-mono uppercase tracking-[0.15em] text-gray-400">
                                    Tilt · <span style={{ color: ds.fg }}>{mgr.tilt}</span>
                                </span>
                            )}
                        </div>

                        <div className="grid grid-cols-3 gap-2 mb-2">
                            <div className="bg-[#0F0F0F] border border-[#262626] p-1.5 rounded-sm">
                                <div className="text-[9px] font-mono text-gray-500 uppercase tracking-[0.1em]">Final Action</div>
                                <div className="font-mono font-bold text-sm" style={{ color: ds.fg }} data-testid="manager-final-action">
                                    {mgr.final_action || "—"}
                                </div>
                            </div>
                            <div className="bg-[#0F0F0F] border border-[#262626] p-1.5 rounded-sm">
                                <div className="text-[9px] font-mono text-gray-500 uppercase tracking-[0.1em]">Size · Risk</div>
                                <div className="font-mono font-bold text-sm text-white" data-testid="manager-size">
                                    {Number(mgr.position_size_pct || 0).toFixed(2)}%
                                </div>
                            </div>
                            <div className="bg-[#0F0F0F] border border-[#262626] p-1.5 rounded-sm">
                                <div className="text-[9px] font-mono text-[#FF2A55] uppercase tracking-[0.1em]">Final SL</div>
                                <div className="font-mono font-bold text-sm text-[#FF2A55]" data-testid="manager-final-sl">
                                    {mgr.final_sl ? Number(mgr.final_sl).toFixed(2) : "—"}
                                </div>
                            </div>
                        </div>

                        {mgr.rationale && (
                            <p className="text-xs text-gray-300 leading-snug mb-1.5" data-testid="manager-rationale">
                                {mgr.rationale}
                            </p>
                        )}

                        {(mgr.modifications || []).length > 0 && (
                            <>
                                <div className="text-[9px] font-mono uppercase tracking-[0.15em] mt-2 mb-1" style={{ color: ds.fg }}>
                                    Modifications applied
                                </div>
                                <ul className="text-[11px] text-gray-400 space-y-1 list-disc list-inside leading-snug">
                                    {mgr.modifications.slice(0, 4).map((m, i) => (
                                        <li key={i}>{m}</li>
                                    ))}
                                </ul>
                            </>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
