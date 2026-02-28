from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

JOBS_DIR = PROJECT_ROOT / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

NETASCORE_DIR = PROJECT_ROOT / "netascore"
NETASCORE_PROFILE_BIKE = NETASCORE_DIR / "examples" / "profile_bike.yml"
NETASCORE_PROFILE_WALK = NETASCORE_DIR / "examples" / "profile_walk.yml"
NETASCORE_SETTINGS = NETASCORE_DIR / "examples" / "settings_osm_query.yml"
