"""Worker configuration. Everything comes from environment variables (GitHub Actions secrets in production)."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def _env(name: str, default: str = "") -> str:
    """Environment value, treating an empty string as unset (GitHub Actions passes unset vars as empty)."""
    v = os.environ.get(name)
    return default if v is None or v.strip() == "" else v

def _b(name: str, default: str = "") -> bool:
    return _env(name, default) in ("1", "true", "True", "yes")

DATABASE_URL = _env("DATABASE_URL", "")
ENCRYPTION_KEY = _env("ENCRYPTION_KEY", "")          # same key the API uses to encrypt Meta tokens
OPENROUTER_API_KEY = _env("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Models (same choices as the creative extraction dashboard; override per environment)
EXTRACTION_MODEL = _env("EXTRACTION_MODEL", "qwen/qwen3.8-flash")   # multimodal: can watch video / read images
CLUSTER_MODEL = _env("CLUSTER_MODEL", "openai/gpt-4o-mini")         # text only, reliable JSON
NAMING_MODEL = _env("NAMING_MODEL", CLUSTER_MODEL)
INSIGHT_MODEL = _env("INSIGHT_MODEL", "anthropic/claude-sonnet-4.5")

META_API_VERSION = _env("META_API_VERSION", "v23.0")
MOCK_META = _b("MOCK_META")        # fixture ads instead of Meta
MOCK_LLM = _b("MOCK_LLM")          # deterministic fake LLM, no API key needed

EXTRACT_CONCURRENCY = int(_env("EXTRACT_CONCURRENCY", "16"))
EXTRACT_ATTEMPTS = int(_env("EXTRACT_ATTEMPTS", "3"))   # per ad across runs, then marked failed
CLUSTER_BATCH = int(_env("CLUSTER_BATCH", "40"))
LLM_TIMEOUT_S = int(_env("LLM_TIMEOUT_S", "120"))

# Lab eligibility (account currency units; defaults are INR)
LAB_MIN_ADS = int(_env("LAB_MIN_ADS", "15"))
LAB_MIN_SPEND = float(_env("LAB_MIN_SPEND", "300000"))
LAB_BACKTEST_REPS = int(_env("LAB_BACKTEST_REPS", "2"))

PROMPTS_DIR = ROOT / "prompts"
INSIGHT_ENGINE_DIR = ROOT / "insight-engine"
