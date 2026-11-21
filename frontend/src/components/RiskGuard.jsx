import { useEffect, useState } from "react";
import { ShieldAlert, ShieldCheck, Settings2, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { saveRiskSettings } from "@/lib/api";

const FIELDS = [
    { key: "account_balance", label: "Account balance ($)", step: 100, min: 1 },
    { key: "risk_pct", label: "Risk per trade (%)", step: 0.1, min: 0.1, max: 10 },
    { key: "max_daily_losses", label: "Max losing trades per day", step: 1, min: 1, max: 20 },
    { key: "max_daily_loss_pct", label: "Max daily loss (%)", step: 0.5, min: 0.5, max: 50 },
];

function RiskSettingsDialog({ open, onOpenChange, settings, onSaved }) {
    const [draft, setDraft] = useState(settings);
    const [saving, setSaving] = useState(false);
    useEffect(() => { if (open) setDraft(settings); }, [open, settings]);
    if (!draft) return null;

    const save = async () => {
        setSaving(true);
        try {
            await saveRiskSettings(draft);
            toast.success("Risk settings saved");
            onSaved();
            onOpenChange(false);
        } catch (e) {
            toast.error(e?.response?.data?.detail?.[0]?.msg || "Could not save risk settings");
        } finally {
            setSaving(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="bg-[#0C0C0C] border border-[#262626] text-white max-w-sm" data-testid="risk-settings-dialog">
                <DialogHeader>
                    <DialogTitle className="font-black tracking-tighter">Risk Guard</DialogTitle>
                    <DialogDescription className="text-[11px] font-mono text-gray-500 uppercase tracking-[0.12em]">
                        Position sizing + daily loss limit · also stops the MT5 EA
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-3">
                    {FIELDS.map((f) => (
                        <label key={f.key} className="flex items-center justify-between gap-3">
                            <span className="text-xs text-gray-300">{f.label}</span>
                            <input
                                type="number"
                                step={f.step}
                                min={f.min}
                                max={f.max}
                                value={draft[f.key]}
                                onChange={(e) => setDraft({ ...draft, [f.key]: Number(e.target.value) })}
                                data-testid={`risk-input-${f.key}`}
                                className="w-28 bg-[#141414] border border-[#333] rounded-sm px-2 py-1.5 font-mono text-sm text-right focus:outline-none focus:border-[#D4AF37]"
                            />
                        </label>
                    ))}
                    <label className="flex items-center justify-between gap-3 pt-1">
                        <span className="text-xs text-gray-300">Lock trading when limit is hit</span>
                        <input
                            type="checkbox"
                            checked={draft.enabled}
                            onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
                            data-testid="risk-input-enabled"
                            className="accent-[#D4AF37] w-4 h-4"
                        />
                    </label>
                </div>
                <button
                    type="button"
                    onClick={save}
                    disabled={saving}
                    data-testid="risk-save-btn"
                    className="mt-2 w-full text-xs font-mono font-bold uppercase tracking-[0.12em] py-2.5 bg-[#D4AF37] text-black rounded-sm hover:bg-[#E5C04A] transition-colors disabled:opacity-60 flex items-center justify-center gap-1.5"
                >
                    {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Save
                </button>
            </DialogContent>
        </Dialog>
    );
}

export default function RiskGuard({ status, onChanged }) {
    const [open, setOpen] = useState(false);
    if (!status) return null;
    const s = status.settings;
    const locked = status.locked;
    const color = locked ? "#FF2A55" : status.pnl_pct_today < 0 ? "#D4AF37" : "#00B86B";
    const Icon = locked ? ShieldAlert : ShieldCheck;
    const fmtMoney = (n) => `${n >= 0 ? "+" : "−"}$${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;

    return (
        <div
            className="border rounded-sm px-3 py-2.5"
            style={{ borderColor: `${color}55`, background: locked ? "rgba(255,42,85,0.08)" : "#121212" }}
            data-testid="risk-guard-card"
        >
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.18em]" style={{ color }}>
                    <Icon className="w-3.5 h-3.5" />
                    <span data-testid="risk-guard-state">{locked ? "Trading locked today" : "Risk Guard · OK"}</span>
                </div>
                <button
                    type="button"
                    onClick={() => setOpen(true)}
                    data-testid="risk-settings-btn"
                    className="text-gray-500 hover:text-[#D4AF37] transition-colors p-0.5"
                    title="Risk settings"
                >
                    <Settings2 className="w-3.5 h-3.5" />
                </button>
            </div>
            {locked && (
                <div className="text-xs text-gray-200 mt-1.5" data-testid="risk-lock-reason">
                    {status.reason}. No new trades until 00:00 UTC — the MT5 EA is paused too.
                </div>
            )}
            <div className="grid grid-cols-3 gap-2 mt-2 font-mono">
                <div>
                    <div className="text-[9px] text-gray-500 uppercase tracking-[0.12em]">Today P/L</div>
                    <div className="text-sm font-bold" style={{ color: status.pnl_today >= 0 ? "#00B86B" : "#FF2A55" }} data-testid="risk-pnl-today">
                        {fmtMoney(status.pnl_today)} <span className="text-[10px] text-gray-500">({status.pnl_pct_today.toFixed(2)}%)</span>
                    </div>
                </div>
                <div>
                    <div className="text-[9px] text-gray-500 uppercase tracking-[0.12em]">Losses</div>
                    <div className="text-sm font-bold text-white" data-testid="risk-losses-today">
                        {status.losses_today} / {s.max_daily_losses}
                    </div>
                </div>
                <div>
                    <div className="text-[9px] text-gray-500 uppercase tracking-[0.12em]">Risk / trade</div>
                    <div className="text-sm font-bold text-[#D4AF37]" data-testid="risk-per-trade">
                        {s.risk_pct}% · ${(s.account_balance * s.risk_pct / 100).toFixed(0)}
                    </div>
                </div>
            </div>
            <div className="text-[9px] font-mono text-gray-600 uppercase tracking-[0.12em] mt-1.5">
                Source · {status.source === "ea" ? "MT5 EA closed trades" : "auto-graded signals"} · limit −{s.max_daily_loss_pct}%
            </div>
            <RiskSettingsDialog open={open} onOpenChange={setOpen} settings={s} onSaved={onChanged} />
        </div>
    );
}
