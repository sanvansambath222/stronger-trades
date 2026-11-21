export const FAMILY_COLOR = { claude: "#F59E0B", openai: "#14B8A6", rule: "#00B86B" };

export const MODEL_META = {
    opus: { short: "Opus 5.5", label: "Claude Opus 5.5", family: "claude", speed: "slow" },
    sonnet: { short: "Sonnet 5.5", label: "Claude Sonnet 5.5", family: "claude", speed: "medium" },
    haiku: { short: "Haiku 5.5", label: "Claude Haiku 5.5", family: "claude", speed: "fast" },
    gpt55: { short: "GPT 5.5", label: "GPT 5.5", family: "openai", speed: "medium" },
    gpt6luna: { short: "GPT 6 Luna", label: "GPT 6 Luna", family: "openai", speed: "fast" },
    rule: { short: "Rule", label: "AURUM Rule Engine", family: "rule", speed: "fast" },
};

export const ROLE_LABELS = {
    bull: "Bull Researcher",
    bear: "Bear Researcher",
    trader: "Head Trader",
    aggressive: "Aggressive Risk",
    neutral: "Neutral Risk",
    conservative: "Conservative Risk",
    manager: "Portfolio Manager",
};

const SPEED_RANK = { fast: 1, medium: 2, slow: 3 };
const RANK_SPEED = { 1: "fast", 2: "medium", 3: "slow" };

export function estimateRun(settings, engine, withRiskTeam) {
    if (!settings) return null;
    const rank = (ids) => Math.max(...ids.map((id) => SPEED_RANK[MODEL_META[id]?.speed] || 2));
    if (engine === "council") {
        const roles = ["bull", "bear", "trader", ...(withRiskTeam ? ["aggressive", "neutral", "conservative", "manager"] : [])];
        const r = Math.min(3, rank(roles.map((k) => settings.roles[k])) + (withRiskTeam ? 1 : 0));
        return { calls: roles.length, speed: RANK_SPEED[r] };
    }
    return { calls: settings.ensemble.length, speed: RANK_SPEED[rank(settings.ensemble)] };
}

export function ModelTag({ id, testId }) {
    const meta = MODEL_META[id];
    if (!meta) return null;
    const color = FAMILY_COLOR[meta.family];
    return (
        <span
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm font-mono text-[9px] uppercase tracking-[0.08em] whitespace-nowrap"
            style={{ color, background: `${color}14`, border: `1px solid ${color}40` }}
            data-testid={testId}
            title={meta.label}
        >
            <span className="w-1 h-1 rounded-full" style={{ background: color }} />
            {meta.short}
        </span>
    );
}
