from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

BASE_JOBS_DIR = PROJECT_ROOT / "jobs"
BASE_JOBS_DIR.mkdir(parents=True, exist_ok=True)

NETASCORE_DIR = PROJECT_ROOT / "netascore"
NETASCORE_SETTINGS_TEMPLATE = NETASCORE_DIR / "examples" / "settings_osm_query.yml"
