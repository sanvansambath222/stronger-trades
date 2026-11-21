import { useEffect, useRef, useState } from "react";
import {
    createChart,
    CandlestickSeries,
    HistogramSeries,
    LineSeries,
    createSeriesMarkers,
    LineStyle,
} from "lightweight-charts";
import { fetchCandles } from "@/lib/api";
import { Loader2 } from "lucide-react";

function calcEMA(values, period) {
    const out = new Array(values.length).fill(null);
    if (values.length < period) return out;
    const k = 2 / (period + 1);
    let sum = 0;
    for (let i = 0; i < period; i++) sum += values[i];
    let prev = sum / period;
    out[period - 1] = prev;
    for (let i = period; i < values.length; i++) {
        prev = values[i] * k + prev * (1 - k);
        out[i] = prev;
    }
    return out;
}

function calcRSI(values, period = 14) {
    const out = new Array(values.length).fill(null);
    if (values.length <= period) return out;
    let gains = 0, losses = 0;
    for (let i = 1; i <= period; i++) {
        const ch = values[i] - values[i - 1];
        if (ch >= 0) gains += ch; else losses -= ch;
    }
    let avgG = gains / period;
    let avgL = losses / period;
    out[period] = avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL);
    for (let i = period + 1; i < values.length; i++) {
        const ch = values[i] - values[i - 1];
        const g = Math.max(ch, 0);
        const l = Math.max(-ch, 0);
        avgG = (avgG * (period - 1) + g) / period;
        avgL = (avgL * (period - 1) + l) / period;
        out[i] = avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL);
    }
    return out;
}

function Legend({ color, label }) {
    return (
        <span className="inline-flex items-center gap-1.5 text-gray-300">
            <span className="inline-block w-4 h-[2px]" style={{ background: color }} />
            <span>{label}</span>
        </span>
    );
}

export default function PriceChart({ interval, refreshKey, aiSignal }) {
    const containerRef = useRef(null);
    const chartRef = useRef(null);
    const candleRef = useRef(null);
    const volRef = useRef(null);
    const ema20Ref = useRef(null);
    const ema50Ref = useRef(null);
    const ema200Ref = useRef(null);
    const rsiRef = useRef(null);
    const priceLinesRef = useRef([]);
    const markersRef = useRef(null);
    const lastCandlesRef = useRef([]);
    const [loading, setLoading] = useState(true);
    const [err, setErr] = useState(null);

    // Create chart once
    useEffect(() => {
        if (!containerRef.current) return;
        const chart = createChart(containerRef.current, {
            layout: {
                background: { color: "#0F0F0F" },
                textColor: "#A3A3A3",
                fontFamily: "'JetBrains Mono', monospace",
                panes: { separatorColor: "#262626", separatorHoverColor: "#3a3a3a", enableResize: false },
            },
            localization: { locale: "en-US" },
            grid: {
                vertLines: { color: "rgba(38,38,38,0.35)" },
                horzLines: { color: "rgba(38,38,38,0.35)" },
            },
            crosshair: { mode: 1 },
            rightPriceScale: { borderColor: "#262626" },
            timeScale: { borderColor: "#262626", timeVisible: true, secondsVisible: false },
            width: containerRef.current.clientWidth,
            height: 640,
        });

        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: "#00B86B",
            downColor: "#FF2A55",
            borderUpColor: "#00B86B",
            borderDownColor: "#FF2A55",
            wickUpColor: "#00B86B",
            wickDownColor: "#FF2A55",
        });

        const ema20Series = chart.addSeries(LineSeries, {
            color: "#3B82F6", lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        const ema50Series = chart.addSeries(LineSeries, {
            color: "#D4AF37", lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        const ema200Series = chart.addSeries(LineSeries, {
            color: "#A78BFA", lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });

        const volSeries = chart.addSeries(HistogramSeries, {
            priceFormat: { type: "volume" },
            priceScaleId: "",
            color: "rgba(212,175,55,0.25)",
        });
        volSeries.priceScale().applyOptions({ scaleMargins: { top: 0.88, bottom: 0 } });

        // RSI pane (paneIndex = 1)
        const rsiSeries = chart.addSeries(
            LineSeries,
            { color: "#D4AF37", lineWidth: 2, priceLineVisible: false, lastValueVisible: true, priceFormat: { type: "price", precision: 2, minMove: 0.01 } },
            1,
        );
        rsiSeries.createPriceLine({ price: 70, color: "rgba(255,42,85,0.5)", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false });
        rsiSeries.createPriceLine({ price: 30, color: "rgba(0,184,107,0.5)", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false });
        rsiSeries.createPriceLine({ price: 50, color: "rgba(115,115,115,0.4)", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false });

        // Set pane heights
        try {
            const panes = chart.panes();
            if (panes && panes[1]) panes[1].setHeight(140);
        } catch { /* ignore */ }

        chartRef.current = chart;
        candleRef.current = candleSeries;
        volRef.current = volSeries;
        ema20Ref.current = ema20Series;
        ema50Ref.current = ema50Series;
        ema200Ref.current = ema200Series;
        rsiRef.current = rsiSeries;

        const onResize = () => {
            if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
        };
        window.addEventListener("resize", onResize);
        return () => {
            window.removeEventListener("resize", onResize);
            chart.remove();
            chartRef.current = null;
        };
    }, []);

    // Load candles + overlays
    useEffect(() => {
        let alive = true;
        const load = async () => {
            setLoading(true);
            setErr(null);
            try {
                const data = await fetchCandles(interval, 250);
                if (!alive || !candleRef.current) return;
                const cs = data.candles.map((c) => ({
                    time: c.time, open: c.open, high: c.high, low: c.low, close: c.close,
                }));
                const vols = data.candles.map((c) => ({
                    time: c.time,
                    value: c.volume || 0,
                    color: c.close >= c.open ? "rgba(0,184,107,0.25)" : "rgba(255,42,85,0.25)",
                }));
                const closes = data.candles.map((c) => c.close);
                const e20 = calcEMA(closes, 20);
                const e50 = calcEMA(closes, 50);
                const e200 = calcEMA(closes, 200);
                const rsi = calcRSI(closes, 14);

                candleRef.current.setData(cs);
                volRef.current.setData(vols);
                ema20Ref.current.setData(
                    cs.map((c, i) => (e20[i] != null ? { time: c.time, value: e20[i] } : null)).filter(Boolean),
                );
                ema50Ref.current.setData(
                    cs.map((c, i) => (e50[i] != null ? { time: c.time, value: e50[i] } : null)).filter(Boolean),
                );
                ema200Ref.current.setData(
                    cs.map((c, i) => (e200[i] != null ? { time: c.time, value: e200[i] } : null)).filter(Boolean),
                );
                rsiRef.current.setData(
                    cs.map((c, i) => (rsi[i] != null ? { time: c.time, value: rsi[i] } : null)).filter(Boolean),
                );

                lastCandlesRef.current = cs;
                chartRef.current?.timeScale().fitContent();
            } catch (e) {
                setErr(e?.response?.data?.detail || e.message || "Failed to load chart");
            } finally {
                if (alive) setLoading(false);
            }
        };
        load();
        const id = window.setInterval(load, 30000);
        return () => { alive = false; window.clearInterval(id); };
    }, [interval, refreshKey]);

    // Draw AI signal: Entry/SL/TP1/TP2/TP3 lines + BUY/SELL marker
    useEffect(() => {
        const series = candleRef.current;
        if (!series) return;

        // clear previous lines
        priceLinesRef.current.forEach((pl) => {
            try { series.removePriceLine(pl); } catch { /* ignore */ }
        });
        priceLinesRef.current = [];

        // clear previous marker
        if (markersRef.current) {
            try { markersRef.current.setMarkers([]); } catch { /* ignore */ }
        }

        if (!aiSignal) return;
        const action = (aiSignal.action || "HOLD").toUpperCase();
        if (action === "HOLD") return;

        const isBuy = action === "BUY";

        priceLinesRef.current.push(
            series.createPriceLine({
                price: aiSignal.entry,
                color: "#FFFFFF",
                lineWidth: 2,
                lineStyle: LineStyle.Solid,
                axisLabelVisible: true,
                title: "Entry",
            }),
        );
        priceLinesRef.current.push(
            series.createPriceLine({
                price: aiSignal.stop_loss,
                color: "#FF2A55",
                lineWidth: 2,
                lineStyle: LineStyle.Dashed,
                axisLabelVisible: true,
                title: "SL",
            }),
        );

        const tpList = [
            { title: "TP1", price: aiSignal.tp1 ?? aiSignal.take_profit },
            { title: "TP2", price: aiSignal.tp2 },
            { title: "TP3", price: aiSignal.tp3 },
        ].filter((t) => t.price != null);

        tpList.forEach((t) => {
            priceLinesRef.current.push(
                series.createPriceLine({
                    price: t.price,
                    color: "#00B86B",
                    lineWidth: 1,
                    lineStyle: LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: t.title,
                }),
            );
        });

        // Marker at most recent candle
        if (lastCandlesRef.current.length > 0) {
            const last = lastCandlesRef.current[lastCandlesRef.current.length - 1];
            const marker = [{
                time: last.time,
                position: isBuy ? "belowBar" : "aboveBar",
                color: isBuy ? "#00B86B" : "#FF2A55",
                shape: isBuy ? "arrowUp" : "arrowDown",
                text: action,
            }];
            if (!markersRef.current) {
                markersRef.current = createSeriesMarkers(series, marker);
            } else {
                markersRef.current.setMarkers(marker);
            }
        }
    }, [aiSignal]);

    return (
        <div className="bg-[#0F0F0F] border border-[#262626] rounded-sm overflow-hidden" data-testid="price-chart">
            {/* Legend / Title bar */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-[#262626] bg-[#0A0A0A] flex-wrap gap-2">
                <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em]">
                    Signal Chart · XAUUSD {interval.toUpperCase()} ·{" "}
                    <span className="text-[#D4AF37]">at analysis time</span>
                    {loading && <Loader2 className="inline w-3 h-3 ml-2 animate-spin" />}
                </div>
                <div className="flex items-center gap-4 text-[10px] font-mono">
                    <Legend color="#3B82F6" label="EMA20" />
                    <Legend color="#D4AF37" label="EMA50" />
                    <Legend color="#A78BFA" label="EMA200" />
                    <Legend color="#737373" label="Bollinger" />
                </div>
            </div>
            {err && (
                <div className="px-4 py-2 text-xs font-mono text-[#FF2A55]" data-testid="chart-error">
                    {err}
                </div>
            )}
            <div ref={containerRef} className="w-full" data-testid="chart-canvas" />
            <div className="flex items-center justify-between px-4 py-1 border-t border-[#262626] bg-[#0A0A0A]">
                <span className="text-[10px] font-mono text-gray-400 tracking-[0.15em] uppercase">RSI 14</span>
                <span className="text-[10px] font-mono text-gray-500 tracking-[0.15em] uppercase">
                    70 overbought · 30 oversold
                </span>
            </div>
        </div>
    );
}
