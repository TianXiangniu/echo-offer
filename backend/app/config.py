from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_URL = f"sqlite:///{BASE_DIR / 'data' / 'app.db'}"
LOCAL_USER_ID = "local-user"
WORKFLOW_VERSION = "alpha-local-v1"
MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024
DEFAULT_UPLOAD_ROOT = BASE_DIR / "data" / "uploads"
