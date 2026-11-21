import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Target, TrendingUp, TrendingDown, Award, Loader2, BarChart3 } from "lucide-react";

function fmt(n, d = 1) {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    return Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

function StatBox({ label, value, sub, color = "#FFFFFF", icon: Icon, testId }) {
    return (
        <div
            className="bg-[#0F0F0F] border border-[#262626] p-3 rounded-sm flex items-center gap-3"
            data-testid={testId}
        >
            {Icon && <Icon className="w-5 h-5" style={{ color }} />}
            <div className="flex-1">
                <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.15em]">{label}</div>
                <div className="font-mono font-bold text-2xl leading-none mt-1" style={{ color }}>
                    {value}
                </div>
                {sub && <div className="text-[10px] font-mono text-gray-500 mt-1">{sub}</div>}
            </div>
        </div>
    );
}

export default function WinRateTracker({ refreshKey }) {
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [err, setErr] = useState(null);

    useEffect(() => {
        let alive = true;
        setLoading(true);
        api.get("/signals/stats")
            .then((r) => { if (alive) setStats(r.data); })
            .catch((e) => { if (alive) setErr(e?.response?.data?.detail || e.message); })
            .finally(() => { if (alive) setLoading(false); });
        return () => { alive = false; };
    }, [refreshKey]);

    const overall = stats?.overall;
    const wrColor = !overall ? "#A3A3A3"
        : overall.win_rate >= 60 ? "#00B86B"
        : overall.win_rate >= 45 ? "#D4AF37"
        : "#FF2A55";
    const rColor = !overall ? "#A3A3A3"
        : overall.avg_r > 0.5 ? "#00B86B"
        : overall.avg_r >= 0 ? "#D4AF37"
        : "#FF2A55";

    return (
        <div className="bg-[#121212] border border-[#262626] rounded-sm" data-testid="winrate-tracker">
            <div className="flex items-center justify-between px-4 py-2 border-b border-[#262626]">
                <div className="flex items-center gap-2">
                    <BarChart3 className="w-3.5 h-3.5 text-[#D4AF37]" />
                    <span className="text-[10px] font-mono text-[#D4AF37] uppercase tracking-[0.2em]">
                        Track Record · Win-Rate Tracker
                    </span>
                </div>
                <span className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.15em]">
                    Auto-graded from historical candles
                </span>
            </div>

            {loading && (
                <div className="p-6 text-center"><Loader2 className="w-5 h-5 mx-auto animate-spin text-[#D4AF37]" /></div>
            )}

            {err && <div className="p-4 text-xs font-mono text-[#FF2A55]" data-testid="winrate-error">{err}</div>}

            {stats && (
                <div className="p-3 space-y-3">
                    {/* Hero stats */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                        <StatBox
                            label="Win Rate"
                            value={overall.total ? `${fmt(overall.win_rate, 1)}%` : "—"}
                            sub={`${overall.wins}W · ${overall.losses}L · ${overall.expired}E`}
                            color={wrColor}
                            icon={Target}
                            testId="stat-win-rate"
                        />
                        <StatBox
                            label="Avg R-Multiple"
                            value={overall.total ? `${overall.avg_r >= 0 ? "+" : ""}${fmt(overall.avg_r, 2)}R` : "—"}
                            sub="per signal"
                            color={rColor}
                            icon={overall.avg_r >= 0 ? TrendingUp : TrendingDown}
                            testId="stat-avg-r"
                        />
                        <StatBox
                            label="Total Graded"
                            value={overall.total}
                            sub="completed signals"
                            color="#FFFFFF"
                            icon={BarChart3}
                            testId="stat-total"
                        />
                        <StatBox
                            label="Best Streak"
                            value={stats.best_streak || 0}
                            sub="wins in a row"
                            color="#D4AF37"
                            icon={Award}
                            testId="stat-streak"
                        />
                    </div>

                    {/* Period stats */}
                    <div className="grid grid-cols-2 gap-2">
                        <div className="bg-[#0F0F0F] border border-[#262626] p-2 rounded-sm" data-testid="period-7d">
                            <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.15em]">
                                Last 7 days
                            </div>
                            <div className="flex items-baseline gap-3 mt-1">
                                <span className="font-mono font-bold text-lg text-white">
                                    {stats.period_7d.total ? `${fmt(stats.period_7d.win_rate, 1)}%` : "—"}
                                </span>
                                <span className="text-xs font-mono text-gray-400">
                                    {stats.period_7d.wins}W · {stats.period_7d.losses}L · avg {fmt(stats.period_7d.avg_r, 2)}R
                                </span>
                            </div>
                        </div>
                        <div className="bg-[#0F0F0F] border border-[#262626] p-2 rounded-sm" data-testid="period-30d">
                            <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.15em]">
                                Last 30 days
                            </div>
                            <div className="flex items-baseline gap-3 mt-1">
                                <span className="font-mono font-bold text-lg text-white">
                                    {stats.period_30d.total ? `${fmt(stats.period_30d.win_rate, 1)}%` : "—"}
                                </span>
                                <span className="text-xs font-mono text-gray-400">
                                    {stats.period_30d.wins}W · {stats.period_30d.losses}L · avg {fmt(stats.period_30d.avg_r, 2)}R
                                </span>
                            </div>
                        </div>
                    </div>

                    {/* By timeframe */}
                    {stats.by_timeframe && stats.by_timeframe.length > 0 && (
                        <div className="bg-[#0F0F0F] border border-[#262626] rounded-sm overflow-hidden">
                            <div className="px-3 py-2 border-b border-[#262626]">
                                <span className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.15em]">
                                    Performance by Timeframe
                                </span>
                            </div>
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.1em] border-b border-[#262626]">
                                        <th className="px-3 py-1.5 text-left">TF</th>
                                        <th className="px-3 py-1.5 text-right">Total</th>
                                        <th className="px-3 py-1.5 text-right">W / L</th>
                                        <th className="px-3 py-1.5 text-right">Win %</th>
                                        <th className="px-3 py-1.5 text-right">Avg R</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {stats.by_timeframe.map((row) => (
                                        <tr key={row.timeframe} className="border-b border-[#262626]/60 hover:bg-[#1A1A1A]" data-testid={`tf-row-${row.timeframe}`}>
                                            <td className="px-3 py-1.5 font-mono text-xs text-[#D4AF37]">{row.timeframe}</td>
                                            <td className="px-3 py-1.5 font-mono text-xs text-right text-white">{row.total}</td>
                                            <td className="px-3 py-1.5 font-mono text-xs text-right text-gray-300">
                                                <span className="text-[#00B86B]">{row.wins}</span>
                                                <span className="text-gray-600"> / </span>
                                                <span className="text-[#FF2A55]">{row.losses}</span>
                                            </td>
                                            <td
                                                className="px-3 py-1.5 font-mono text-xs text-right font-bold"
                                                style={{ color: row.win_rate >= 60 ? "#00B86B" : row.win_rate >= 45 ? "#D4AF37" : "#FF2A55" }}
                                            >
                                                {fmt(row.win_rate, 1)}%
                                            </td>
                                            <td
                                                className="px-3 py-1.5 font-mono text-xs text-right"
                                                style={{ color: row.avg_r >= 0 ? "#00B86B" : "#FF2A55" }}
                                            >
                                                {row.avg_r >= 0 ? "+" : ""}{fmt(row.avg_r, 2)}R
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}

                    {overall.total === 0 && (
                        <div className="text-center py-4 text-xs font-mono text-gray-500" data-testid="winrate-empty">
                            No graded signals yet. Signals are auto-graded after their expiry window.
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
