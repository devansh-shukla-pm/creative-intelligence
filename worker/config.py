"""Worker configuration. Everything comes from environment variables (GitHub Actions secrets in production)."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def _b(name: str, default: str = "") -> bool:
    return os.environ.get(name, default) in ("1", "true", "True", "yes")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")          # same key the API uses to encrypt Meta tokens
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Models (same choices as the creative extraction dashboard; override per environment)
EXTRACTION_MODEL = os.environ.get("EXTRACTION_MODEL", "qwen/qwen3.8-flash")   # multimodal: can watch video / read images
CLUSTER_MODEL = os.environ.get("CLUSTER_MODEL", "openai/gpt-4o-mini")         # text only, reliable JSON
NAMING_MODEL = os.environ.get("NAMING_MODEL", CLUSTER_MODEL)
INSIGHT_MODEL = os.environ.get("INSIGHT_MODEL", "anthropic/claude-sonnet-4.5")

META_API_VERSION = os.environ.get("META_API_VERSION", "v23.0")
MOCK_META = _b("MOCK_META")        # fixture ads instead of Meta
MOCK_LLM = _b("MOCK_LLM")          # deterministic fake LLM, no API key needed

EXTRACT_CONCURRENCY = int(os.environ.get("EXTRACT_CONCURRENCY", "6"))
EXTRACT_ATTEMPTS = int(os.environ.get("EXTRACT_ATTEMPTS", "3"))   # per ad across runs, then marked failed
CLUSTER_BATCH = int(os.environ.get("CLUSTER_BATCH", "40"))
LLM_TIMEOUT_S = int(os.environ.get("LLM_TIMEOUT_S", "120"))

# Lab eligibility (account currency units; defaults are INR)
LAB_MIN_ADS = int(os.environ.get("LAB_MIN_ADS", "15"))
LAB_MIN_SPEND = float(os.environ.get("LAB_MIN_SPEND", "300000"))
LAB_BACKTEST_REPS = int(os.environ.get("LAB_BACKTEST_REPS", "2"))

PROMPTS_DIR = ROOT / "prompts"
INSIGHT_ENGINE_DIR = ROOT / "insight-engine"
