"""Environment-driven configuration for the Text-to-SQL assistant."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:         # python-dotenv is optional
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
EXAMPLES_DIR = ROOT / "examples"

# Which Spider database to work with
DB_NAME = os.getenv("DB_NAME", "concert_singer")
DB_PATH = DATA_DIR / f"{DB_NAME}.sqlite"
EXAMPLES_PATH = EXAMPLES_DIR / "examples.json"   # used by demo mode + few-shot prompts
DEV_PATH = EXAMPLES_DIR / "dev.json"             # held-out questions for evaluation

# LLM settings (all optional)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
MODEL = os.getenv("MODEL", "gpt-4o-mini")

# Safety limits
MAX_ROWS = int(os.getenv("MAX_ROWS", "200"))
TIMEOUT_SECONDS = float(os.getenv("TIMEOUT_SECONDS", "5"))


def default_mode() -> str:
    """'llm' when an API key is present, otherwise free 'demo' mode."""
    return "llm" if OPENAI_API_KEY else "demo"
