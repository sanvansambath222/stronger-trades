import { useEffect, useState } from "react";
import { Cpu, Check, Loader2, Gauge } from "lucide-react";
import { toast } from "sonner";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { saveAISettings } from "@/lib/api";
import { MODEL_META, ROLE_LABELS, FAMILY_COLOR, ModelTag, estimateRun } from "@/lib/modelMeta";

const PRESETS = [
    { id: "max", label: "Max quality", hint: "Opus everywhere" },
    { id: "balanced", label: "Balanced", hint: "Opus lead · Sonnet/GPT 5.5" },
    { id: "budget", label: "Budget", hint: "Haiku/Luna · Sonnet lead" },
];
const MODEL_IDS = ["opus", "sonnet", "haiku", "gpt55", "gpt6luna"];
const SPEED_COLOR = { fast: "#00B86B", medium: "#D4AF37", slow: "#FF8A33" };

function CostHint({ label, est, testId }) {
    if (!est) return null;
    return (
        <div className="flex items-center justify-between text-[10px] font-mono uppercase tracking-[0.12em] text-gray-400" data-testid={testId}>
            <span className="flex items-center gap-1.5"><Gauge className="w-3 h-3 text-[#D4AF37]" />{label}</span>
            <span>
                ~{est.calls} AI calls · <span style={{ color: SPEED_COLOR[est.speed] }}>{est.speed}</span>
            </span>
        </div>
    );
}

function ModelToggle({ id, on, onToggle }) {
    const meta = MODEL_META[id];
    const color = FAMILY_COLOR[meta.family];
    return (
        <button
            type="button"
            onClick={onToggle}
            data-testid={`model-toggle-${id}`}
            aria-pressed={on}
            className="w-full flex items-center justify-between px-3 py-2.5 rounded-sm border transition-colors"
            style={{ borderColor: on ? `${color}80` : "#262626", background: on ? `${color}10` : "#0F0F0F" }}
        >
            <div className="flex items-center gap-2.5">
                <span className="w-2 h-2 rounded-full" style={{ background: color, opacity: on ? 1 : 0.35 }} />
                <div className="text-left">
                    <div className="text-sm text-white font-medium">{meta.label}</div>
                    <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.12em]">
                        {meta.family === "claude" ? "Anthropic" : "OpenAI"} · {meta.speed}
                        {id === "opus" && " · main model"}
                    </div>
                </div>
            </div>
            <span
                className="w-5 h-5 rounded-sm border flex items-center justify-center"
                style={{ borderColor: on ? color : "#404040", background: on ? color : "transparent" }}
            >
                {on && <Check className="w-3.5 h-3.5 text-black" />}
            </span>
        </button>
    );
}

function RolePicker({ role, value, onChange }) {
    return (
        <div className="flex items-center justify-between gap-3 px-3 py-2 border border-[#262626] bg-[#0F0F0F] rounded-sm" data-testid={`role-card-${role}`}>
            <div className="min-w-0">
                <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.15em]">{ROLE_LABELS[role]}</div>
                <div className="mt-1"><ModelTag id={value} /></div>
            </div>
            <select
                value={value}
                onChange={(e) => onChange(e.target.value)}
                data-testid={`role-select-${role}`}
                className="bg-[#141414] border border-[#333] text-xs font-mono text-white rounded-sm px-2 py-1.5 focus:outline-none focus:border-[#D4AF37]"
            >
                {MODEL_IDS.map((m) => (
                    <option key={m} value={m}>{MODEL_META[m].label}</option>
                ))}
            </select>
        </div>
    );
}

export default function AIModelsDrawer({ open, onOpenChange, settings, presets, onSaved }) {
    const [draft, setDraft] = useState(settings);
    const [saving, setSaving] = useState(false);

    useEffect(() => { if (open) setDraft(settings); }, [open, settings]);

    if (!draft) return null;

    const toggleModel = (id) => {
        const has = draft.ensemble.includes(id);
        if (has && draft.ensemble.length === 1) {
            toast.error("Keep at least one model switched on");
            return;
        }
        const ensemble = has ? draft.ensemble.filter((m) => m !== id) : MODEL_IDS.filter((m) => m === id || draft.ensemble.includes(m));
        setDraft({ ...draft, ensemble, preset: null });
    };
    const setRole = (role, model) => setDraft({ ...draft, roles: { ...draft.roles, [role]: model }, preset: null });
    const applyPreset = (id) => {
        const p = presets?.[id];
        if (p) setDraft({ ensemble: [...p.ensemble], roles: { ...p.roles }, preset: id });
    };

    const save = async () => {
        setSaving(true);
        try {
            const saved = await saveAISettings(draft);
            onSaved(saved);
            toast.success("AI model settings saved");
            onOpenChange(false);
        } catch (e) {
            toast.error(e?.response?.data?.detail?.[0]?.msg || "Could not save settings");
        } finally {
            setSaving(false);
        }
    };

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                side="right"
                className="w-full sm:max-w-md bg-[#0C0C0C] border-l border-[#262626] text-white p-0 flex flex-col"
                data-testid="ai-models-drawer"
            >
                <SheetHeader className="px-5 pt-5 pb-3 border-b border-[#262626] text-left">
                    <SheetTitle className="text-white font-black tracking-tighter flex items-center gap-2">
                        <Cpu className="w-4 h-4 text-[#D4AF37]" /> AI Models
                    </SheetTitle>
                    <SheetDescription className="text-[11px] font-mono text-gray-500 uppercase tracking-[0.12em]">
                        Used by Deep AI, Council, auto-upgrade & the MT5 EA
                    </SheetDescription>
                </SheetHeader>

                <div className="px-5 py-3 border-b border-[#262626]">
                    <div className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.15em] mb-2">Presets</div>
                    <div className="grid grid-cols-3 gap-1.5">
                        {PRESETS.map((p) => (
                            <button
                                key={p.id}
                                type="button"
                                onClick={() => applyPreset(p.id)}
                                data-testid={`preset-${p.id}-btn`}
                                className={`px-2 py-2 rounded-sm border text-left transition-colors ${
                                    draft.preset === p.id ? "border-[#D4AF37] bg-[#D4AF37]/10" : "border-[#262626] hover:border-[#404040]"
                                }`}
                            >
                                <div className={`text-xs font-bold ${draft.preset === p.id ? "text-[#D4AF37]" : "text-white"}`}>{p.label}</div>
                                <div className="text-[9px] font-mono text-gray-500 leading-tight mt-0.5">{p.hint}</div>
                            </button>
                        ))}
                    </div>
                </div>

                <Tabs defaultValue="vote" className="flex-1 flex flex-col min-h-0">
                    <TabsList className="mx-5 mt-3 bg-[#141414] border border-[#262626] rounded-sm grid grid-cols-2 h-9">
                        <TabsTrigger value="vote" data-testid="tab-vote" className="text-xs font-mono uppercase tracking-[0.1em] rounded-sm data-[state=active]:bg-[#262626] data-[state=active]:text-[#D4AF37]">
                            Vote Models
                        </TabsTrigger>
                        <TabsTrigger value="roles" data-testid="tab-roles" className="text-xs font-mono uppercase tracking-[0.1em] rounded-sm data-[state=active]:bg-[#262626] data-[state=active]:text-[#D4AF37]">
                            Council Roles
                        </TabsTrigger>
                    </TabsList>
                    <div className="flex-1 overflow-y-auto px-5 py-3">
                        <TabsContent value="vote" className="mt-0 space-y-2">
                            <p className="text-xs text-gray-400 leading-relaxed mb-2">
                                Each model switched on reads the same chart, indicators, DXY & news and votes BUY / SELL / HOLD. The majority decides; a tie gives HOLD.
                            </p>
                            {MODEL_IDS.map((id) => (
                                <ModelToggle key={id} id={id} on={draft.ensemble.includes(id)} onToggle={() => toggleModel(id)} />
                            ))}
                            <div className="pt-2">
                                <CostHint label="Deep AI run" est={estimateRun(draft, "ai")} testId="cost-hint-deep" />
                            </div>
                        </TabsContent>
                        <TabsContent value="roles" className="mt-0 space-y-2">
                            {Object.keys(ROLE_LABELS).map((r) => (
                                <RolePicker key={r} role={r} value={draft.roles[r]} onChange={(m) => setRole(r, m)} />
                            ))}
                            <div className="pt-2 space-y-1">
                                <CostHint label="Council run" est={estimateRun(draft, "council", false)} testId="cost-hint-council" />
                                <CostHint label="Council + Risk Team" est={estimateRun(draft, "council", true)} testId="cost-hint-council-risk" />
                            </div>
                        </TabsContent>
                    </div>
                </Tabs>

                <div className="px-5 py-4 border-t border-[#262626] flex items-center gap-2">
                    <button
                        type="button"
                        onClick={() => onOpenChange(false)}
                        data-testid="ai-models-cancel-btn"
                        className="flex-1 text-xs font-mono uppercase tracking-[0.12em] py-2.5 border border-[#262626] rounded-sm text-gray-400 hover:text-white transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={save}
                        disabled={saving}
                        data-testid="ai-models-save-btn"
                        className="flex-1 text-xs font-mono font-bold uppercase tracking-[0.12em] py-2.5 bg-[#D4AF37] text-black rounded-sm hover:bg-[#E5C04A] transition-colors disabled:opacity-60 flex items-center justify-center gap-1.5"
                    >
                        {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Save settings
                    </button>
                </div>
            </SheetContent>
        </Sheet>
    );
}
