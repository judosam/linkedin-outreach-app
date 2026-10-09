"""Central configuration for the Outreach Command Center backend.

All values come from environment / .env with safe defaults. The pipeline
scripts share the same .env (see pipeline_common.py).
"""
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    # Load .env from the project root (one level above app/)
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Web app ---
ADMIN_USERNAME = os.environ.get('OCC_ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('OCC_ADMIN_PASSWORD', '')
if not ADMIN_PASSWORD or ADMIN_PASSWORD in ('change-me', 'outreach-admin-2026'):
    raise RuntimeError('Set OCC_ADMIN_PASSWORD to a unique password in .env before starting the app')
SESSION_TTL_HOURS = int(os.environ.get('OCC_SESSION_TTL_HOURS', '12'))

# --- Sheets (same values pipeline_common uses) ---
MASTER_SHEET_ID = os.environ.get('MASTER_SHEET_ID', '1xdZtLvQZ6cshlI75-XuLU7dSuniL-2NIqVZ8mQYHUxk')
SERVICE_ACCOUNT_FILE = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE', './credentials.json')

# --- Local persistence ---
APP_DATA_DIR = Path(os.environ.get('OCC_APP_DATA_DIR', PROJECT_ROOT / 'app_data'))
DB_PATH = APP_DATA_DIR / 'app_data.db'

# Pipeline imports (scripts at project root) are resolved via sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
