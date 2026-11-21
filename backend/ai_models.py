import time
from typing import Dict, List, Optional
from pydantic import BaseModel, field_validator

MODEL_ROSTER: Dict[str, Dict[str, str]] = {
    "opus": {"provider": "anthropic", "model": "claude-opus-5-5", "label": "Claude Opus 5.5", "family": "claude", "speed": "slow"},
    "sonnet": {"provider": "anthropic", "model": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "family": "claude", "speed": "medium"},
    "haiku": {"provider": "anthropic", "model": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "family": "claude", "speed": "fast"},
    "gpt55": {"provider": "openai", "model": "gpt-5.5", "label": "GPT 5.5", "family": "openai", "speed": "medium"},
    "gpt6luna": {"provider": "openai", "model": "gpt-6-luna", "label": "GPT 6 Luna", "family": "openai", "speed": "fast"},
}

ROLES = [
    ("bull", "Bull Researcher"),
    ("bear", "Bear Researcher"),
    ("trader", "Head Trader"),
    ("aggressive", "Aggressive Risk"),
    ("neutral", "Neutral Risk"),
    ("conservative", "Conservative Risk"),
    ("manager", "Portfolio Manager"),
]
ROLE_IDS = [r[0] for r in ROLES]

PRESETS: Dict[str, Dict] = {
    "max": {
        "label": "Max quality",
        "ensemble": ["opus", "sonnet", "gpt55"],
        "roles": {r: "opus" for r in ROLE_IDS},
    },
    "balanced": {
        "label": "Balanced",
        "ensemble": ["opus", "sonnet", "gpt55"],
        "roles": {"bull": "sonnet", "bear": "gpt55", "trader": "opus", "aggressive": "gpt6luna",
                  "neutral": "sonnet", "conservative": "haiku", "manager": "opus"},
    },
    "budget": {
        "label": "Budget",
        "ensemble": ["haiku", "gpt6luna", "sonnet"],
        "roles": {"bull": "haiku", "bear": "gpt6luna", "trader": "sonnet", "aggressive": "gpt6luna",
                  "neutral": "haiku", "conservative": "haiku", "manager": "sonnet"},
    },
}

MODEL_TIMEOUT_SECONDS = 45


class AISettings(BaseModel):
    ensemble: List[str]
    roles: Dict[str, str]
    preset: Optional[str] = None

    @field_validator("ensemble")
    @classmethod
    def _check_ensemble(cls, v):
        v = [m for m in dict.fromkeys(v) if m in MODEL_ROSTER]
        if not v:
            raise ValueError("At least one model must be enabled for the vote")
        return v

    @field_validator("roles")
    @classmethod
    def _check_roles(cls, v):
        default = PRESETS["balanced"]["roles"]
        return {r: (v.get(r) if v.get(r) in MODEL_ROSTER else default[r]) for r in ROLE_IDS}

    def cache_tag(self) -> str:
        return ",".join(self.ensemble) + "|" + ",".join(self.roles[r] for r in ROLE_IDS)


def default_settings() -> AISettings:
    p = PRESETS["balanced"]
    return AISettings(ensemble=list(p["ensemble"]), roles=dict(p["roles"]), preset="balanced")


def model_label(model_id: str) -> str:
    return MODEL_ROSTER.get(model_id, {}).get("label", model_id)


# In-memory live progress so the UI can show votes as each model finishes
_PROGRESS: Dict[str, Dict] = {}


def progress_push(run_id: Optional[str], item: dict) -> None:
    if not run_id:
        return
    now = time.time()
    for k in [k for k, v in _PROGRESS.items() if now - v["updated"] > 600]:
        _PROGRESS.pop(k, None)
    entry = _PROGRESS.setdefault(run_id, {"items": [], "updated": now})
    entry["items"].append(item)
    entry["updated"] = now


def progress_get(run_id: str) -> List[dict]:
    return _PROGRESS.get(run_id, {}).get("items", [])
