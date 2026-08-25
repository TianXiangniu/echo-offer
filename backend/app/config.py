from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_URL = f"sqlite:///{BASE_DIR / 'data' / 'app.db'}"
LOCAL_USER_ID = "local-user"
WORKFLOW_VERSION = "alpha-local-v1"
