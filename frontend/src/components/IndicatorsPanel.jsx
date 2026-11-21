import { useEffect, useState } from "react";
import { fetchIndicators } from "@/lib/api";
import { Loader2 } from "lucide-react";

function fmt(n, d = 2) {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    return Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

function RSIGauge({ value }) {
    const v = value || 50;
    const pct = Math.min(100, Math.max(0, v));
    const color = v >= 70 ? "#FF2A55" : v <= 30 ? "#00B86B" : "#D4AF37";
    return (
        <div>
            <div className="flex justify-between text-[10px] font-mono text-gray-500 uppercase tracking-[0.15em] mb-1">
                <span>Oversold</span>
                <span style={{ color }}>{fmt(v, 1)}</span>
                <span>Overbought</span>
            </div>
            <div className="h-1.5 bg-[#1A1A1A] rounded-sm relative overflow-hidden">
                <div className="absolute inset-y-0 left-[30%] w-px bg-[#00B86B]/40" />
                <div className="absolute inset-y-0 left-[70%] w-px bg-[#FF2A55]/40" />
                <div className="h-full transition-all" style={{ width: `${pct}%`, background: color }} />
            </div>
        </div>
    );
}

function Cell({ label, value, sub, color = "#FFFFFF", testId }) {
    return (
        <div className="bg-[#0F0F0F] border border-[#262626] p-3 rounded-sm" data-testid={testId}>
            <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.15em]">{label}</div>
            <div className="font-mono font-bold text-lg mt-1" style={{ color }}>{value}</div>
            {sub && <div className="text-[10px] font-mono text-gray-500 mt-0.5">{sub}</div>}
        </div>
    );
}

export default function IndicatorsPanel({ interval, refreshKey }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [err, setErr] = useState(null);

    useEffect(() => {
        let alive = true;
        const load = async () => {
            setLoading(true);
            setErr(null);
            try {
                const d = await fetchIndicators(interval);
                if (alive) setData(d);
            } catch (e) {
                if (alive) setErr(e?.response?.data?.detail || e.message);
            } finally {
                if (alive) setLoading(false);
            }
        };
        load();
        return () => { alive = false; };
    }, [interval, refreshKey]);

    const macdBull = data && data.macd != null && data.macd_signal != null && data.macd > data.macd_signal;
    const aboveE20 = data && data.ema20 != null && data.price > data.ema20;
    const aboveE50 = data && data.ema50 != null && data.price > data.ema50;
    const aboveE200 = data && data.ema200 != null && data.price > data.ema200;

    return (
        <div className="bg-[#121212] border border-[#262626] rounded-sm" data-testid="indicators-panel">
            <div className="flex items-center justify-between px-4 py-2 border-b border-[#262626]">
                <span className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em]">Technical Indicators</span>
                <span className="text-[10px] font-mono text-[#D4AF37] uppercase">{interval}</span>
            </div>
            {loading && !data && (
                <div className="p-6 text-center">
                    <Loader2 className="w-5 h-5 mx-auto animate-spin text-[#D4AF37]" />
                </div>
            )}
            {err && <div className="p-4 text-xs font-mono text-[#FF2A55]">{err}</div>}
            {data && (
                <div className="p-3 space-y-3">
                    <div className="bg-[#0F0F0F] border border-[#262626] p-3 rounded-sm">
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.15em]">RSI(14)</span>
                            <span className="text-[10px] font-mono text-gray-400">
                                {data.rsi >= 70 ? "OVERBOUGHT" : data.rsi <= 30 ? "OVERSOLD" : "NEUTRAL"}
                            </span>
                        </div>
                        <RSIGauge value={data.rsi} />
                    </div>

                    <div className="grid grid-cols-3 gap-2">
                        <Cell
                            label="MACD"
                            value={fmt(data.macd, 3)}
                            sub={`Sig ${fmt(data.macd_signal, 3)}`}
                            color={macdBull ? "#00B86B" : "#FF2A55"}
                            testId="ind-macd"
                        />
                        <Cell
                            label="MACD Hist"
                            value={fmt(data.macd_hist, 3)}
                            color={data.macd_hist >= 0 ? "#00B86B" : "#FF2A55"}
                        />
                        <Cell
                            label="Price"
                            value={fmt(data.price)}
                            color="#D4AF37"
                        />
                    </div>

                    <div className="grid grid-cols-3 gap-2">
                        <Cell
                            label="EMA 20"
                            value={fmt(data.ema20)}
                            sub={aboveE20 ? "▲ Above" : "▼ Below"}
                            color={aboveE20 ? "#00B86B" : "#FF2A55"}
                            testId="ind-ema20"
                        />
                        <Cell
                            label="EMA 50"
                            value={fmt(data.ema50)}
                            sub={aboveE50 ? "▲ Above" : "▼ Below"}
                            color={aboveE50 ? "#00B86B" : "#FF2A55"}
                        />
                        <Cell
                            label="EMA 200"
                            value={fmt(data.ema200)}
                            sub={aboveE200 ? "▲ Above" : "▼ Below"}
                            color={aboveE200 ? "#00B86B" : "#FF2A55"}
                        />
                    </div>

                    <div className="grid grid-cols-3 gap-2">
                        <Cell label="BB Upper" value={fmt(data.bb_upper)} color="#FF2A55" />
                        <Cell label="BB Mid" value={fmt(data.bb_mid)} color="#A3A3A3" />
                        <Cell label="BB Lower" value={fmt(data.bb_lower)} color="#00B86B" />
                    </div>
                </div>
            )}
        </div>
    );
}
