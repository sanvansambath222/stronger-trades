import { useEffect, useState } from "react";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Send, Bell, ExternalLink, Loader2, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { fetchTelegramConfig, updateTelegramConfig, sendTelegramTest } from "@/lib/api";

export default function TelegramSettings() {
    const [open, setOpen] = useState(false);
    const [config, setConfig] = useState(null);
    const [botToken, setBotToken] = useState("");
    const [chatId, setChatId] = useState("");
    const [enabled, setEnabled] = useState(false);
    const [alertMode, setAlertMode] = useState("strong");
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);

    useEffect(() => {
        if (!open) return;
        fetchTelegramConfig().then((cfg) => {
            setConfig(cfg);
            setChatId(cfg.chat_id || "");
            setEnabled(cfg.enabled || false);
            setAlertMode(cfg.alert_mode || "strong");
        }).catch(() => {});
    }, [open]);

    const handleSave = async () => {
        setSaving(true);
        try {
            const payload = { enabled, chat_id: chatId, alert_mode: alertMode };
            if (botToken.trim()) payload.bot_token = botToken.trim();
            const updated = await updateTelegramConfig(payload);
            setConfig(updated);
            setBotToken("");
            toast.success("Telegram settings saved");
        } catch (e) {
            toast.error(e?.response?.data?.detail || "Save failed");
        } finally {
            setSaving(false);
        }
    };

    const handleTest = async () => {
        setTesting(true);
        try {
            await sendTelegramTest();
            toast.success("Test message sent — check your Telegram!");
        } catch (e) {
            toast.error(e?.response?.data?.detail || "Test failed");
        } finally {
            setTesting(false);
        }
    };

    const isConfigured = config?.has_token && config?.chat_id;

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <button
                    data-testid="open-telegram-settings-btn"
                    className="text-xs font-mono uppercase tracking-wider px-3 py-1.5 border border-[#262626] hover:border-[#D4AF37] hover:text-[#D4AF37] transition-colors rounded-sm flex items-center gap-1"
                >
                    <Bell className="w-3 h-3" />
                    <span className="hidden sm:inline">Alerts</span>
                    {config?.enabled && (
                        <span className="w-1.5 h-1.5 rounded-full bg-[#00B86B] live-dot" />
                    )}
                </button>
            </DialogTrigger>
            <DialogContent
                className="bg-[#0F0F0F] border-[#262626] text-white max-w-lg max-h-[90vh] overflow-y-auto"
                data-testid="telegram-settings-modal"
            >
                <DialogHeader>
                    <DialogTitle className="font-black tracking-tighter text-2xl">
                        Telegram <span className="text-[#D4AF37]">Alerts</span>
                    </DialogTitle>
                    <p className="text-xs font-mono text-gray-400 leading-relaxed">
                        Get an instant push notification on your phone every time a
                        <span className="text-[#00B86B] font-bold"> STRONG + DOUBLE CONFIRMED </span>
                        signal is generated.
                    </p>
                </DialogHeader>

                <div className="space-y-4 pt-2">
                    {/* Setup instructions */}
                    <div className="bg-[#1A1A1A] border border-[#262626] p-3 rounded-sm text-xs font-mono space-y-2 text-gray-300">
                        <p className="font-bold text-[#D4AF37] uppercase tracking-[0.15em] text-[10px]">
                            One-time setup
                        </p>
                        <ol className="space-y-1.5 list-decimal pl-4">
                            <li>
                                Open Telegram → search{" "}
                                <a
                                    href="https://t.me/BotFather"
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-[#D4AF37] hover:underline inline-flex items-center gap-0.5"
                                >
                                    @BotFather <ExternalLink className="w-3 h-3" />
                                </a>{" "}
                                → send <code className="text-[#00B86B]">/newbot</code> → copy the bot token
                            </li>
                            <li>
                                Search{" "}
                                <a
                                    href="https://t.me/userinfobot"
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-[#D4AF37] hover:underline inline-flex items-center gap-0.5"
                                >
                                    @userinfobot <ExternalLink className="w-3 h-3" />
                                </a>{" "}
                                → send any message → copy your <b>chat ID</b>
                            </li>
                            <li>Send <code className="text-[#00B86B]">/start</code> to YOUR bot (required once)</li>
                            <li>Paste both below and hit Save</li>
                        </ol>
                    </div>

                    {/* Bot Token */}
                    <div className="space-y-1.5">
                        <Label htmlFor="bot-token" className="text-[10px] font-mono uppercase tracking-[0.2em] text-gray-400">
                            Bot Token
                            {config?.has_token && (
                                <span className="ml-2 text-[#00B86B] inline-flex items-center gap-1">
                                    <CheckCircle2 className="w-3 h-3" /> Set
                                </span>
                            )}
                        </Label>
                        <Input
                            id="bot-token"
                            data-testid="bot-token-input"
                            type="password"
                            placeholder={config?.has_token ? config.bot_token_masked : "123456789:ABCdefGhIJKlmnoPQR…"}
                            value={botToken}
                            onChange={(e) => setBotToken(e.target.value)}
                            className="font-mono text-sm bg-[#1A1A1A] border-[#262626] text-white"
                        />
                    </div>

                    {/* Chat ID */}
                    <div className="space-y-1.5">
                        <Label htmlFor="chat-id" className="text-[10px] font-mono uppercase tracking-[0.2em] text-gray-400">
                            Chat ID
                        </Label>
                        <Input
                            id="chat-id"
                            data-testid="chat-id-input"
                            placeholder="123456789"
                            value={chatId}
                            onChange={(e) => setChatId(e.target.value)}
                            className="font-mono text-sm bg-[#1A1A1A] border-[#262626] text-white"
                        />
                    </div>

                    {/* Alert mode selector */}
                    <div className="bg-[#1A1A1A] border border-[#262626] rounded-sm p-3 space-y-3">
                        <div className="flex items-center justify-between">
                            <div>
                                <Label className="text-sm text-white font-medium">Enable alerts</Label>
                                <p className="text-[10px] font-mono text-gray-500 mt-0.5">
                                    Master switch
                                </p>
                            </div>
                            <Switch
                                checked={enabled}
                                onCheckedChange={setEnabled}
                                data-testid="alert-enabled-switch"
                            />
                        </div>
                        <div className="border-t border-[#262626] pt-3">
                            <Label className="text-sm text-white font-medium block mb-2">Alert me on</Label>
                            <div className="grid grid-cols-3 gap-1.5">
                                {[
                                    { id: "strong", label: "Strong Only", sub: "DOUBLE + STRONG", color: "#00B86B" },
                                    { id: "actionable", label: "BUY / SELL", sub: "All actionable", color: "#D4AF37" },
                                    { id: "all", label: "All Signals", sub: "Including HOLD", color: "#3B82F6" },
                                ].map((opt) => (
                                    <button
                                        key={opt.id}
                                        type="button"
                                        onClick={() => setAlertMode(opt.id)}
                                        data-testid={`mode-${opt.id}-btn`}
                                        className={`p-2 rounded-sm border text-left transition-all ${
                                            alertMode === opt.id
                                                ? "border-[#D4AF37] bg-[#D4AF37]/10"
                                                : "border-[#262626] bg-[#0F0F0F] hover:border-gray-600"
                                        }`}
                                    >
                                        <div
                                            className="text-xs font-mono font-bold uppercase tracking-tight"
                                            style={{ color: alertMode === opt.id ? "#D4AF37" : opt.color }}
                                        >
                                            {opt.label}
                                        </div>
                                        <div className="text-[9px] font-mono text-gray-500 mt-0.5 leading-tight">
                                            {opt.sub}
                                        </div>
                                    </button>
                                ))}
                            </div>
                            <p className="text-[10px] font-mono text-gray-500 mt-2 leading-relaxed">
                                {alertMode === "strong" && "Only the highest-confidence signals (both AIs agree + STRONG strength). Few alerts, very high quality."}
                                {alertMode === "actionable" && "Every BUY or SELL signal regardless of strength. HOLD signals skipped."}
                                {alertMode === "all" && "Every signal pushed to Telegram, including HOLD/neutral. Maximum visibility."}
                            </p>
                        </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2 pt-2">
                        <Button
                            onClick={handleSave}
                            disabled={saving}
                            data-testid="save-telegram-btn"
                            className="flex-1 bg-[#D4AF37] hover:bg-[#C09F2C] text-black font-mono uppercase tracking-wider"
                        >
                            {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                            Save Settings
                        </Button>
                        <Button
                            onClick={handleTest}
                            disabled={testing || !isConfigured}
                            data-testid="test-telegram-btn"
                            variant="outline"
                            className="border-[#262626] text-white hover:bg-[#1A1A1A] hover:text-[#D4AF37] font-mono uppercase tracking-wider"
                        >
                            {testing ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Send className="w-3 h-3 mr-1" />}
                            Test
                        </Button>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
