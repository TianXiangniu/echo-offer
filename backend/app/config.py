import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / "backend" / ".env")

DEFAULT_DATABASE_URL = f"sqlite:///{BASE_DIR / 'data' / 'app.db'}"
LOCAL_USER_ID = "local-user"
WORKFLOW_VERSION = "alpha-local-v1"
MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024
DEFAULT_UPLOAD_ROOT = BASE_DIR / "data" / "uploads"
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
SILICONFLOW_MODEL = os.getenv("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
SILICONFLOW_BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
ANALYSIS_TIMEOUT_SECONDS = float(os.getenv("ANALYSIS_TIMEOUT_SECONDS", "45"))
MAX_ANALYSIS_RESUME_CHARS = 100_000
