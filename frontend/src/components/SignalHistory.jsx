import { useEffect, useState, useMemo } from "react";
import { fetchSignalHistory } from "@/lib/api";
import { Loader2, Filter } from "lucide-react";
import { ModelTag } from "@/lib/modelMeta";

function fmt(n, d = 2) {
    if (n === null || n === undefined) return "—";
    return Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

function timeAgo(iso) {
    if (!iso) return "";
    const t = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (t < 60) return `${t}s`;
    if (t < 3600) return `${Math.floor(t / 60)}m`;
    if (t < 86400) return `${Math.floor(t / 3600)}h`;
    return `${Math.floor(t / 86400)}d`;
}

const actionColor = (a) => a === "BUY" ? "#00B86B" : a === "SELL" ? "#FF2A55" : "#D4AF37";

const consensusDot = (c) => {
    if (c === "DOUBLE_CONFIRMED" || c === "UNANIMOUS") return { color: "#00B86B", title: "All AIs agree" };
    if (c === "MAJORITY") return { color: "#7AB8FF", title: "Majority of AIs agree" };
    if (c === "CONFLICTED") return { color: "#FF2A55", title: "AIs disagree" };
    if (c === "SINGLE_SOURCE") return { color: "#D4AF37", title: "One AI responded" };
    return { color: "#737373", title: "Legacy" };
};

const outcomeStyle = (o) => {
    if (!o) return { label: "•", color: "#737373", bg: "transparent", title: "Active / Ungraded" };
    if (o === "TP1") return { label: "✓ TP1", color: "#00B86B", bg: "rgba(0,184,107,0.12)", title: "Hit TP1" };
    if (o === "TP2") return { label: "✓✓ TP2", color: "#00B86B", bg: "rgba(0,184,107,0.18)", title: "Hit TP2" };
    if (o === "TP3") return { label: "✓✓✓ TP3", color: "#00B86B", bg: "rgba(0,184,107,0.25)", title: "Hit TP3" };
    if (o === "SL") return { label: "✗ SL", color: "#FF2A55", bg: "rgba(255,42,85,0.15)", title: "Hit Stop Loss" };
    if (o === "EXPIRED") return { label: "⏸ EXP", color: "#A3A3A3", bg: "rgba(163,163,163,0.1)", title: "Expired" };
    if (o === "NO_DATA") return { label: "?", color: "#737373", bg: "transparent", title: "Outside data window" };
    return { label: o, color: "#737373", bg: "transparent", title: o };
};


export default function SignalHistory({ refreshKey }) {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [strongOnly, setStrongOnly] = useState(false);

    useEffect(() => {
        let alive = true;
        setLoading(true);
        fetchSignalHistory(30)
            .then((d) => { if (alive) setItems(d.signals || []); })
            .catch(() => {})
            .finally(() => { if (alive) setLoading(false); });
        return () => { alive = false; };
    }, [refreshKey]);

    const filtered = useMemo(() => {
        if (!strongOnly) return items;
        return items.filter((s) =>
            s.consensus !== "CONFLICTED" &&
            s.signal_strength !== "WEAK" &&
            s.action !== "HOLD"
        );
    }, [items, strongOnly]);

    const shown = filtered.slice(0, 10);

    return (
        <div className="bg-[#121212] border border-[#262626] rounded-sm h-full" data-testid="signal-history">
            <div className="flex items-center justify-between px-4 py-2 border-b border-[#262626] gap-2">
                <span className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em]">Signal History</span>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setStrongOnly((s) => !s)}
                        data-testid="strong-signals-toggle"
                        className={`flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-[0.1em] px-2 py-1 rounded-sm border transition-all ${
                            strongOnly
                                ? "border-[#00B86B] bg-[#00B86B]/10 text-[#00B86B]"
                                : "border-[#262626] text-gray-500 hover:text-gray-300"
                        }`}
                    >
                        <Filter className="w-3 h-3" />
                        Strong Only
                    </button>
                    <span className="text-[10px] font-mono text-gray-600">
                        {filtered.length}/{items.length}
                    </span>
                </div>
            </div>
            {loading && (
                <div className="p-6 text-center"><Loader2 className="w-4 h-4 mx-auto animate-spin text-[#D4AF37]" /></div>
            )}
            {!loading && shown.length === 0 && (
                <div className="p-4 text-xs font-mono text-gray-500">
                    {strongOnly ? "No strong signals yet. Toggle off to see all." : "No signals yet. Generate one above."}
                </div>
            )}
            {!loading && shown.length > 0 && (
                <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.1em] border-b border-[#262626]">
                                <th className="px-3 py-2 text-left">Time</th>
                                <th className="px-3 py-2 text-left">TF</th>
                                <th className="px-3 py-2 text-left">Action</th>
                                <th className="px-3 py-2 text-center">AI</th>
                                <th className="px-3 py-2 text-left">Models</th>
                                <th className="px-3 py-2 text-right">Conf</th>
                                <th className="px-3 py-2 text-right">Entry</th>
                                <th className="px-3 py-2 text-right">SL</th>
                                <th className="px-3 py-2 text-right">TP</th>
                                <th className="px-3 py-2 text-center">Result</th>
                            </tr>
                        </thead>
                        <tbody>
                            {shown.map((s, i) => {
                                const dot = consensusDot(s.consensus);
                                const out = outcomeStyle(s.outcome);
                                return (
                                    <tr key={s.id || i} className="border-b border-[#262626]/60 hover:bg-[#1A1A1A]" data-testid={`signal-row-${i}`}>
                                        <td className="px-3 py-2 font-mono text-xs text-gray-400">{timeAgo(s.created_at)} ago</td>
                                        <td className="px-3 py-2 font-mono text-xs text-gray-300">{s.timeframe}</td>
                                        <td className="px-3 py-2 font-mono font-bold text-xs" style={{ color: actionColor(s.action) }}>
                                            {s.action}
                                        </td>
                                        <td className="px-3 py-2 text-center">
                                            <span
                                                className="inline-block w-2 h-2 rounded-full"
                                                style={{ background: dot.color }}
                                                title={dot.title}
                                            />
                                        </td>
                                        <td className="px-3 py-2" data-testid={`signal-models-${i}`}>
                                            <div className="flex flex-wrap gap-1 max-w-[180px]">
                                                {(s.models_used || []).length > 0
                                                    ? s.models_used.map((m) => <ModelTag key={m} id={m} />)
                                                    : <span className="text-[10px] font-mono text-gray-600">{(s.votes || []).map((v) => v.model).join(", ").slice(0, 40) || "—"}</span>}
                                            </div>
                                        </td>
                                        <td className="px-3 py-2 font-mono text-xs text-right text-white">{s.confidence}%</td>
                                        <td className="px-3 py-2 font-mono text-xs text-right text-white">{fmt(s.entry)}</td>
                                        <td className="px-3 py-2 font-mono text-xs text-right text-[#FF2A55]">{fmt(s.stop_loss)}</td>
                                        <td className="px-3 py-2 font-mono text-xs text-right text-[#00B86B]">{fmt(s.tp1 ?? s.take_profit)}</td>
                                        <td className="px-3 py-2 text-center">
                                            <span
                                                className="inline-block px-1.5 py-0.5 rounded-sm font-mono text-[10px] tracking-tight"
                                                style={{ color: out.color, background: out.bg }}
                                                title={out.title}
                                            >
                                                {out.label}
                                            </span>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}
