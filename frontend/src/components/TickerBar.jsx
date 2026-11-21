import { useEffect, useRef, useState } from "react";
import { fetchQuote } from "@/lib/api";

function formatNum(n, d = 2) {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

export default function TickerBar({ refreshKey }) {
    const [quote, setQuote] = useState(null);
    const [tick, setTick] = useState(null); // "up" | "down" | null
    const prevPrice = useRef(null);

    useEffect(() => {
        let alive = true;
        const load = async () => {
            try {
                const q = await fetchQuote();
                if (!alive) return;
                if (prevPrice.current !== null && q.price !== prevPrice.current) {
                    setTick(q.price > prevPrice.current ? "up" : "down");
                    setTimeout(() => setTick(null), 600);
                }
                prevPrice.current = q.price;
                setQuote(q);
            } catch {
                /* ignore */
            }
        };
        load();
        const id = window.setInterval(load, 20000);
        return () => { alive = false; window.clearInterval(id); };
    }, [refreshKey]);

    const isUp = quote && quote.percent_change >= 0;
    const accent = isUp ? "#00B86B" : "#FF2A55";

    return (
        <div className="border-t border-[#262626] bg-[#0A0A0A] px-4 py-2 flex items-center gap-6 overflow-x-auto" data-testid="ticker-bar">
            <div className="flex items-center gap-3">
                <span className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em]">Symbol</span>
                <span className="font-mono font-bold text-[#D4AF37] text-sm" data-testid="ticker-symbol">XAU/USD</span>
            </div>
            <div className={`px-2 ${tick === "up" ? "tick-up" : tick === "down" ? "tick-down" : ""}`}>
                <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em]">Price</div>
                <div className="font-mono font-bold text-2xl tracking-tight" data-testid="ticker-price">
                    {quote ? formatNum(quote.price) : "—"}
                </div>
            </div>
            <div>
                <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em]">24h Change</div>
                <div className="font-mono font-medium text-sm" style={{ color: quote ? accent : "#737373" }}>
                    {quote ? `${isUp ? "+" : ""}${formatNum(quote.change)} (${isUp ? "+" : ""}${formatNum(quote.percent_change, 2)}%)` : "—"}
                </div>
            </div>
            <div className="hidden md:block">
                <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em]">High</div>
                <div className="font-mono text-sm text-white">{quote ? formatNum(quote.high) : "—"}</div>
            </div>
            <div className="hidden md:block">
                <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em]">Low</div>
                <div className="font-mono text-sm text-white">{quote ? formatNum(quote.low) : "—"}</div>
            </div>
            <div className="hidden lg:block">
                <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em]">Open</div>
                <div className="font-mono text-sm text-white">{quote ? formatNum(quote.open) : "—"}</div>
            </div>
            <div className="hidden lg:block">
                <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em]">Prev Close</div>
                <div className="font-mono text-sm text-white">{quote ? formatNum(quote.previous_close) : "—"}</div>
            </div>
        </div>
    );
}
