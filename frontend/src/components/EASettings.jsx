import { useState } from "react";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Bot, Download, Copy, ExternalLink, Check, AlertTriangle, Shield, Send, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { sendEAToTelegram } from "@/lib/api";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

export default function EASettings() {
    const [open, setOpen] = useState(false);
    const [copied, setCopied] = useState(false);
    const [sendingToTg, setSendingToTg] = useState(false);

    const apiUrl = BACKEND_URL;
    const downloadUrl = `${BACKEND_URL}/api/ea/download`;

    const copyUrl = async () => {
        try {
            await navigator.clipboard.writeText(apiUrl);
            setCopied(true);
            toast.success("API URL copied to clipboard");
            setTimeout(() => setCopied(false), 2000);
        } catch {
            toast.error("Copy failed — select and copy manually");
        }
    };

    const handleSendToTelegram = async () => {
        setSendingToTg(true);
        try {
            await sendEAToTelegram();
            toast.success("EA file sent to your Telegram!");
        } catch (e) {
            const detail = e?.response?.data?.detail || "Send failed";
            if (detail.includes("not configured")) {
                toast.error("Set up Telegram first (Alerts button)");
            } else {
                toast.error(detail);
            }
        } finally {
            setSendingToTg(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <button
                    data-testid="open-ea-settings-btn"
                    className="text-xs font-mono uppercase tracking-wider px-3 py-1.5 border border-[#262626] hover:border-[#D4AF37] hover:text-[#D4AF37] transition-colors rounded-sm flex items-center gap-1"
                >
                    <Bot className="w-3 h-3" />
                    <span className="hidden sm:inline">MT5 EA</span>
                </button>
            </DialogTrigger>
            <DialogContent
                className="bg-[#0F0F0F] border-[#262626] text-white max-w-2xl max-h-[90vh] overflow-y-auto"
                data-testid="ea-settings-modal"
            >
                <DialogHeader>
                    <DialogTitle className="font-black tracking-tighter text-2xl">
                        AURUM <span className="text-[#D4AF37]">MT5 Auto-Trader</span>
                    </DialogTitle>
                    <p className="text-xs font-mono text-gray-400 leading-relaxed">
                        Download the Expert Advisor and connect AURUM directly to MetaTrader 5.
                        Your bot will auto-execute STRONG + DOUBLE_CONFIRMED signals with
                        risk-based position sizing and scale-out at TP1.
                    </p>
                </DialogHeader>

                <div className="space-y-4 pt-2">
                    {/* Strategy summary */}
                    <div className="bg-[#1A1A1A] border border-[#262626] p-3 rounded-sm">
                        <div className="text-[10px] font-mono text-[#D4AF37] uppercase tracking-[0.2em] mb-2 flex items-center gap-1.5">
                            <Shield className="w-3 h-3" /> Default Strategy
                        </div>
                        <ul className="text-xs text-gray-300 space-y-1 leading-relaxed">
                            <li>· Risk <b className="text-white">1% per trade</b> (configurable in EA inputs)</li>
                            <li>· Filter: <b className="text-[#00B86B]">STRONG + DOUBLE_CONFIRMED</b> signals only</li>
                            <li>· Semi-auto: <b className="text-white">confirmation popup</b> before each trade</li>
                            <li>· Scale-out: close <b className="text-white">50% at TP1</b>, move SL to entry (BE)</li>
                            <li>· Remaining 50% runs to <b className="text-[#00B86B]">TP3</b> risk-free</li>
                            <li>· Max <b className="text-white">2 concurrent positions</b></li>
                        </ul>
                    </div>

                    {/* Download */}
                    <div className="bg-[#1A1A1A] border border-[#262626] p-3 rounded-sm space-y-2">
                        <div className="text-[10px] font-mono text-[#D4AF37] uppercase tracking-[0.2em]">
                            Step 1 · Get the EA File
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <a
                                href={downloadUrl}
                                download="AurumXAUUSD.mq5"
                                data-testid="download-ea-btn"
                                className="inline-flex items-center gap-2 px-4 py-2 bg-[#D4AF37] hover:bg-[#C09F2C] text-black font-mono uppercase tracking-wider text-sm font-bold rounded-sm transition-colors"
                            >
                                <Download className="w-4 h-4" />
                                Download .mq5
                            </a>
                            <button
                                onClick={handleSendToTelegram}
                                disabled={sendingToTg}
                                data-testid="send-ea-telegram-btn"
                                className="inline-flex items-center gap-2 px-4 py-2 border border-[#3B82F6] text-[#3B82F6] hover:bg-[#3B82F6]/10 font-mono uppercase tracking-wider text-sm font-bold rounded-sm transition-colors disabled:opacity-50"
                            >
                                {sendingToTg ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                                Send to Telegram
                            </button>
                        </div>
                        <p className="text-[10px] font-mono text-gray-500 mt-1">
                            Tip: "Send to Telegram" pushes the file to your phone — then forward it to your PC.
                        </p>
                    </div>

                    {/* API URL */}
                    <div className="bg-[#1A1A1A] border border-[#262626] p-3 rounded-sm space-y-2">
                        <div className="text-[10px] font-mono text-[#D4AF37] uppercase tracking-[0.2em]">
                            Step 2 · Your API URL (paste into EA inputs)
                        </div>
                        <div className="flex items-stretch gap-2">
                            <div className="flex-1 bg-[#0A0A0A] border border-[#262626] px-3 py-2 rounded-sm font-mono text-xs text-[#D4AF37] overflow-x-auto whitespace-nowrap" data-testid="ea-api-url">
                                {apiUrl}
                            </div>
                            <button
                                onClick={copyUrl}
                                data-testid="copy-api-url-btn"
                                className="px-3 py-2 border border-[#262626] hover:border-[#D4AF37] hover:text-[#D4AF37] rounded-sm transition-colors"
                            >
                                {copied ? <Check className="w-4 h-4 text-[#00B86B]" /> : <Copy className="w-4 h-4" />}
                            </button>
                        </div>
                    </div>

                    {/* Whitelist step */}
                    <div className="bg-[#1A1A1A] border border-[#262626] p-3 rounded-sm space-y-2">
                        <div className="text-[10px] font-mono text-[#D4AF37] uppercase tracking-[0.2em]">
                            Step 3 · Whitelist URL in MT5 (CRITICAL!)
                        </div>
                        <div className="text-xs text-gray-300 space-y-1.5 leading-relaxed">
                            <p>In MT5, go to <code className="text-[#00B86B]">Tools → Options → Expert Advisors</code></p>
                            <ol className="list-decimal pl-4 space-y-1">
                                <li>Tick <b className="text-white">"Allow algorithmic trading"</b></li>
                                <li>Tick <b className="text-white">"Allow WebRequest for listed URL"</b></li>
                                <li>Add the API URL above to the list</li>
                                <li>Click OK</li>
                            </ol>
                        </div>
                    </div>

                    {/* Install + Run */}
                    <div className="bg-[#1A1A1A] border border-[#262626] p-3 rounded-sm space-y-2">
                        <div className="text-[10px] font-mono text-[#D4AF37] uppercase tracking-[0.2em]">
                            Step 4 · Install & Run
                        </div>
                        <ol className="text-xs text-gray-300 space-y-1.5 list-decimal pl-4 leading-relaxed">
                            <li>In MT5: <code className="text-[#00B86B]">File → Open Data Folder → MQL5 → Experts</code></li>
                            <li>Copy <code className="text-[#00B86B]">AurumXAUUSD.mq5</code> into that folder</li>
                            <li>In MT5 Navigator (Ctrl+N): right-click <b>Expert Advisors</b> → <b className="text-white">Refresh</b></li>
                            <li>Double-click <b className="text-white">AurumXAUUSD</b> → set <b>InpApiUrl</b> = your URL above</li>
                            <li>Set <b>InpSymbol</b> to your broker's gold symbol (XAUUSD / XAUUSDm / GOLD)</li>
                            <li>Tick <b className="text-white">"Allow Algo Trading"</b> in the dialog → OK</li>
                            <li>Top toolbar: ensure the <b>Algo Trading</b> button is GREEN</li>
                        </ol>
                    </div>

                    {/* Warning */}
                    <div className="bg-[#1F1414] border border-[#FF2A55]/50 p-3 rounded-sm">
                        <div className="text-[10px] font-mono text-[#FF2A55] uppercase tracking-[0.2em] mb-2 flex items-center gap-1.5">
                            <AlertTriangle className="w-3 h-3" /> IMPORTANT
                        </div>
                        <ul className="text-xs text-gray-200 space-y-1 leading-relaxed">
                            <li>· <b className="text-[#FF2A55]">TEST ON A DEMO ACCOUNT FOR AT LEAST 1 WEEK</b> before going live</li>
                            <li>· MT5 must run 24/7 (your PC or a $5/mo VPS) for the EA to work</li>
                            <li>· Past performance ≠ future results. Trading involves risk of loss.</li>
                            <li>· Start with 0.5% risk on demo; ramp to 1% only after consistent results</li>
                        </ul>
                    </div>

                    <div className="flex items-center justify-between pt-2 gap-2">
                        <a
                            href="https://www.metatrader5.com/en/download"
                            target="_blank"
                            rel="noreferrer"
                            className="text-xs font-mono text-gray-400 hover:text-[#D4AF37] inline-flex items-center gap-1"
                        >
                            <ExternalLink className="w-3 h-3" /> Don't have MT5? Download free
                        </a>
                        <Button
                            onClick={() => setOpen(false)}
                            className="bg-[#D4AF37] hover:bg-[#C09F2C] text-black font-mono uppercase tracking-wider"
                        >
                            Got it
                        </Button>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
