import subprocess
from pathlib import Path

import yaml

from api.config import settings


def update_settings(settings_input_path: Path, settings_output_path: Path, target_srid: int, bbox_str: str, case_id: str = "default_case") -> None:
    with open(settings_input_path, "r", encoding="utf-8") as f:
        netascore_settings = yaml.safe_load(f) or {}

    netascore_settings["global"]["case_id"] = case_id
    netascore_settings["global"]["target_srid"] = target_srid

    netascore_settings["database"]["host"] = settings.db_host
    netascore_settings["database"]["port"] = settings.db_port
    netascore_settings["database"]["dbname"] = settings.db_name
    netascore_settings["database"]["username"] = settings.db_username
    netascore_settings["database"]["password"] = settings.db_password
    if not netascore_settings["database"]["password"]:
        del netascore_settings["database"]["password"]

    if netascore_settings["import"]["place_name"]:
        del netascore_settings["import"]["place_name"]
    netascore_settings["import"]["bbox"] = bbox_str
    netascore_settings["import"]["buffer"] = int(0)

    netascore_settings["index"]["compute_explanation"] = False

    settings_output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(netascore_settings, f, sort_keys=False, allow_unicode=True)


def run_netascore(netascore_dir: Path, netascore_settings: Path) -> None:
    cmd = ["python", "generate_index.py", str(netascore_settings)]
    subprocess.run(cmd, cwd=netascore_dir, check=True)
