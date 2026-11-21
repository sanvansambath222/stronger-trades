import { useEffect, useState, useCallback, useRef } from "react";
import TickerBar from "@/components/TickerBar";
import PriceChart from "@/components/PriceChart";
import AISignalCard from "@/components/AISignalCard";
import IndicatorsPanel from "@/components/IndicatorsPanel";
import NewsFeed from "@/components/NewsFeed";
import SignalHistory from "@/components/SignalHistory";
import WinRateTracker from "@/components/WinRateTracker";
import { Activity, Cpu } from "lucide-react";
import { fetchAISignal, fetchAISettings, fetchAIModels, fetchAIProgress } from "@/lib/api";
import AIModelsDrawer from "@/components/AIModelsDrawer";
import RiskGuard from "@/components/RiskGuard";
import { fetchRiskStatus } from "@/lib/api";
import TelegramSettings from "@/components/TelegramSettings";
import EASettings from "@/components/EASettings";

const TIMEFRAMES = [
    { id: "1min", label: "1m" },
    { id: "5min", label: "5m" },
    { id: "15min", label: "15m" },
    { id: "1h", label: "1H" },
    { id: "4h", label: "4H" },
    { id: "1day", label: "1D" },
];

export default function Dashboard() {
    const [interval, setInterval] = useState("15min");
    const [refreshKey, setRefreshKey] = useState(0);
    const [aiSignal, setAiSignal] = useState(null);
    const [aiLoading, setAiLoading] = useState(false);
    const [aiError, setAiError] = useState(null);
    const [confidenceThreshold, setConfidenceThreshold] = useState(60);
    const [engine, setEngine] = useState("rule");
    const [autoUpgrade, setAutoUpgrade] = useState(true);
    const [strongOnly, setStrongOnly] = useState(false);
    const [newsBlackout, setNewsBlackout] = useState(true);
    const [blackoutWindow] = useState(15);
    const [withRiskTeam, setWithRiskTeam] = useState(false);
    const [aiSettings, setAiSettings] = useState(null);
    const [presets, setPresets] = useState(null);
    const [modelsOpen, setModelsOpen] = useState(false);
    const [liveProgress, setLiveProgress] = useState([]);
    const [riskStatus, setRiskStatus] = useState(null);
    const [historyKey, setHistoryKey] = useState(0);
    const loadRisk = useCallback(() => { fetchRiskStatus().then(setRiskStatus).catch(() => {}); }, []);
    useEffect(() => {
        loadRisk();
        const id = window.setInterval(loadRisk, 60000);
        return () => window.clearInterval(id);
    }, [loadRisk, refreshKey]);

    useEffect(() => {
        fetchAISettings().then(setAiSettings).catch(() => {});
        fetchAIModels().then((d) => setPresets(d.presets)).catch(() => {});
    }, []);

    const refresh = () => setRefreshKey((k) => k + 1);
    const engineRef = useRef(engine);

    const loadAI = useCallback(async (forceEngine) => {
        const useEngine = forceEngine || engineRef.current;
        // Only meaningful when running council; ignored otherwise by backend
        const useRiskTeam = useEngine === "council" && withRiskTeam;
        const runId = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
        setAiLoading(true);
        setAiError(null);
        setLiveProgress([]);
        if (forceEngine) { setAiSignal(null); setEngine(forceEngine); engineRef.current = forceEngine; }
        const poll = useEngine !== "rule" || autoUpgrade
            ? window.setInterval(() => {
                fetchAIProgress(runId).then((d) => setLiveProgress(d.items || [])).catch(() => {});
            }, 1500)
            : null;
        try {
            const s = await fetchAISignal(interval, useEngine, autoUpgrade, newsBlackout, blackoutWindow, useRiskTeam, runId);
            setAiSignal(s);
        } catch (e) {
            setAiError(e?.response?.data?.detail || e.message || "Analysis failed");
            setAiSignal(null);
        } finally {
            if (poll) window.clearInterval(poll);
            setAiLoading(false);
            setHistoryKey((k) => k + 1);
        }
    }, [interval, autoUpgrade, newsBlackout, blackoutWindow, withRiskTeam]);

    useEffect(() => {
        document.title = "AURUM TERMINAL — XAU/USD Pro Analytics";
    }, []);

    useEffect(() => { loadAI(); }, [loadAI, refreshKey]);

    return (
        <div className="min-h-screen bg-[#0A0A0A] text-white">
            {/* Header */}
            <header className="border-b border-[#262626] bg-[#0A0A0A] sticky top-0 z-50">
                <div className="flex items-center justify-between px-4 py-3">
                    <div className="flex items-center gap-3">
                        <div className="w-8 h-8 bg-[#D4AF37] flex items-center justify-center rounded-sm">
                            <span className="text-black font-black font-mono text-sm">AU</span>
                        </div>
                        <div>
                            <h1 className="font-black tracking-tighter text-lg leading-none" data-testid="app-title">
                                AURUM<span className="text-[#D4AF37]">.</span>TERMINAL
                            </h1>
                            <p className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em]">
                                XAU/USD · Institutional Analytics
                            </p>
                        </div>
                    </div>
                    <div className="flex items-center gap-3">
                        <div className="hidden md:flex items-center gap-2 text-xs font-mono text-gray-400">
                            <span className="w-1.5 h-1.5 rounded-full bg-[#00B86B] live-dot" />
                            <span>LIVE · TWELVEDATA</span>
                        </div>
                        <button
                            onClick={() => setModelsOpen(true)}
                            data-testid="ai-models-btn"
                            className="text-xs font-mono uppercase tracking-wider px-3 py-1.5 border border-[#D4AF37]/50 text-[#D4AF37] hover:bg-[#D4AF37]/10 transition-colors rounded-sm flex items-center gap-1.5"
                        >
                            <Cpu className="w-3 h-3" /> AI Models
                            {aiSettings && (
                                <span className="text-[10px] text-gray-400" data-testid="ai-models-count">· {aiSettings.ensemble.length}</span>
                            )}
                        </button>
                        <TelegramSettings />
                        <EASettings />
                        <button
                            onClick={refresh}
                            data-testid="refresh-btn"
                            className="text-xs font-mono uppercase tracking-wider px-3 py-1.5 border border-[#262626] hover:border-[#D4AF37] hover:text-[#D4AF37] transition-colors rounded-sm"
                        >
                            <Activity className="inline w-3 h-3 mr-1" /> Refresh
                        </button>
                    </div>
                </div>
                <TickerBar refreshKey={refreshKey} />
            </header>

            {/* Timeframe selector */}
            <div className="border-b border-[#262626] bg-[#0A0A0A] px-4 py-2 flex items-center gap-1 overflow-x-auto">
                <span className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em] mr-3">
                    Timeframe
                </span>
                {TIMEFRAMES.map((tf) => (
                    <button
                        key={tf.id}
                        data-testid={`timeframe-${tf.id}-btn`}
                        onClick={() => setInterval(tf.id)}
                        className={`text-xs font-mono px-3 py-1 rounded-sm transition-all ${
                            interval === tf.id
                                ? "bg-[#262626] text-[#D4AF37]"
                                : "text-gray-400 hover:text-white"
                        }`}
                    >
                        {tf.label}
                    </button>
                ))}
                <div className="ml-auto flex items-center gap-3 flex-wrap">
                    <label
                        className="hidden md:flex items-center gap-1.5 text-[10px] font-mono text-gray-400 uppercase tracking-[0.15em] cursor-pointer select-none"
                        title="When ON: free Rule Engine watches continuously. If it spots a STRONG/VERY STRONG setup, it auto-upgrades to the multi-model AI vote you picked in AI Models."
                    >
                        <input
                            type="checkbox"
                            data-testid="auto-upgrade-toggle"
                            checked={autoUpgrade}
                            onChange={(e) => setAutoUpgrade(e.target.checked)}
                            className="accent-[#D4AF37] cursor-pointer"
                        />
                        Auto-upgrade to Deep AI
                    </label>
                    <label
                        className="hidden md:flex items-center gap-1.5 text-[10px] font-mono text-gray-400 uppercase tracking-[0.15em] cursor-pointer select-none"
                        title={`When ON: BUY/SELL signals are forced to HOLD inside ±${blackoutWindow} min of high-impact USD news (NFP, FOMC, CPI…). Avoids news-spike whipsaws.`}
                    >
                        <input
                            type="checkbox"
                            data-testid="news-blackout-toggle"
                            checked={newsBlackout}
                            onChange={(e) => setNewsBlackout(e.target.checked)}
                            className="accent-[#D4AF37] cursor-pointer"
                        />
                        News Blackout
                    </label>
                    <label
                        className="hidden md:flex items-center gap-1.5 text-[10px] font-mono text-gray-400 uppercase tracking-[0.15em] cursor-pointer select-none"
                        title="When ON: Council adds a 3-role Risk Team (Aggressive/Neutral/Conservative) + Portfolio Manager final authorization. Costs +4 AI calls."
                    >
                        <input
                            type="checkbox"
                            data-testid="risk-team-toggle"
                            checked={withRiskTeam}
                            onChange={(e) => setWithRiskTeam(e.target.checked)}
                            className="accent-[#A855F7] cursor-pointer"
                        />
                        + Risk Team
                    </label>
                    <label
                        className="hidden md:flex items-center gap-1.5 text-[10px] font-mono text-gray-400 uppercase tracking-[0.15em] cursor-pointer select-none"
                        title="Only act on STRONG/VERY STRONG signals. WEAK/MODERATE will be flagged as do-not-trade."
                    >
                        <input
                            type="checkbox"
                            data-testid="strong-only-toggle"
                            checked={strongOnly}
                            onChange={(e) => setStrongOnly(e.target.checked)}
                            className="accent-[#D4AF37] cursor-pointer"
                        />
                        Strong-only
                    </label>
                    <div className="hidden md:flex items-center gap-2">
                        <label className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em]" htmlFor="conf-thresh">
                            Min Confidence
                        </label>
                        <input
                            id="conf-thresh"
                            data-testid="confidence-threshold-slider"
                            type="range"
                            min={0}
                            max={95}
                            step={5}
                            value={confidenceThreshold}
                            onChange={(e) => setConfidenceThreshold(parseInt(e.target.value, 10))}
                            className="w-28 accent-[#D4AF37]"
                        />
                        <span className="text-xs font-mono text-[#D4AF37] w-10" data-testid="confidence-threshold-value">
                            {confidenceThreshold}%
                        </span>
                    </div>
                    <div className="text-[10px] font-mono text-gray-600 uppercase tracking-[0.2em]">
                        Selected · <span className="text-[#D4AF37]">{interval}</span>
                    </div>
                </div>
            </div>

            {/* Main grid */}
            <main className="p-2 grid grid-cols-12 gap-2">
                <section className="col-span-12 xl:col-span-9">
                    <PriceChart
                        interval={interval}
                        refreshKey={refreshKey}
                        aiSignal={(() => {
                            if (!aiSignal) return null;
                            if (aiSignal.confidence < confidenceThreshold) return null;
                            if (strongOnly && !["STRONG", "VERY_STRONG"].includes(aiSignal.signal_strength)) return null;
                            return aiSignal;
                        })()}
                    />
                    <div className="mt-2">
                        <WinRateTracker refreshKey={refreshKey} />
                    </div>
                    <div className="mt-2 grid grid-cols-12 gap-2">
                        <div className="col-span-12 lg:col-span-7">
                            <IndicatorsPanel interval={interval} refreshKey={refreshKey} />
                        </div>
                        <div className="col-span-12 lg:col-span-5">
                            <SignalHistory refreshKey={`${refreshKey}-${historyKey}`} />
                        </div>
                    </div>
                </section>
                <aside className="col-span-12 xl:col-span-3 space-y-2">
                    <RiskGuard status={riskStatus} onChanged={loadRisk} />
                    <AISignalCard
                        signal={aiSignal}
                        loading={aiLoading}
                        error={aiError}
                        onRegenerate={() => loadAI()}
                        onDeepAI={() => loadAI("ai")}
                        onCouncil={() => loadAI("council")}
                        engine={engine}
                        aiSettings={aiSettings}
                        withRiskTeam={withRiskTeam}
                        liveProgress={liveProgress}
                        riskStatus={riskStatus}
                        confidenceThreshold={confidenceThreshold}
                        strongOnly={strongOnly}
                    />
                    <NewsFeed />
                </aside>
            </main>

            <AIModelsDrawer
                open={modelsOpen}
                onOpenChange={setModelsOpen}
                settings={aiSettings}
                presets={presets}
                onSaved={setAiSettings}
            />

            <footer className="px-4 py-4 border-t border-[#262626] mt-4">
                <p className="text-[10px] font-mono text-gray-600 uppercase tracking-[0.2em]">
                    For research only · Not financial advice · Powered by Claude Opus 5.5 · Sonnet 5.5 · Haiku 5.5 · GPT 5.5 · GPT 6 Luna + TwelveData
                </p>
            </footer>
        </div>
    );
}
