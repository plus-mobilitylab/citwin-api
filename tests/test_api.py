import argparse
import time
from pathlib import Path

import requests

from api.config import settings

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://localhost:8000")
parser.add_argument("--upload-netascore", action="store_true")
parser.add_argument("--no-download", action="store_true")
args = parser.parse_args()

BASE_URL = args.base_url
UPLOAD_NETASCORE = args.upload_netascore
DOWNLOAD_FILES = not args.no_download

print(f"– base url: {BASE_URL}")
print(f"– upload netascore: {UPLOAD_NETASCORE}")
print(f"– download files: {DOWNLOAD_FILES}")

DATA_DIR = Path(__file__).parents[0] / "data"
DOWNLOADS_DIR = Path(__file__).parents[0] / "downloads"

API_KEY = settings.api_key

headers = {"x-api-key": API_KEY}


def main():
    # create a job
    files = {
        "od_clusters_a": open(DATA_DIR / "b_klynger.gpkg", "rb"),
        "od_clusters_b": open(DATA_DIR / "a_klynger.gpkg", "rb"),
        "od_table": open(DATA_DIR / "Data_2023_0099_Tabel_1.csv", "rb"),
        "stops": open(DATA_DIR / "dynlayer.gpkg", "rb"),
    }

    if UPLOAD_NETASCORE:
        files["netascore_gpkg"] = open(DATA_DIR / "netascore_20251008_200432.gpkg", "rb")

    data = {
        "od_clusters_a_id_field": "klynge_id",
        "od_clusters_a_count_field": "Beboere",
        "od_clusters_b_id_field": "klynge_id",
        "od_clusters_b_count_field": "Arbejdere",
        "od_table_a_id_field": "Bopael_klynge_id",
        "od_table_b_id_field": "Arbejssted_klynge_id",
        "od_table_trips_field": "Antal",
        "stops_id_field": "stopnummer",
        "output_format": "GPKG",
    }

    response = requests.post(f"{BASE_URL}/jobs", headers=headers, files=files, data=data)
    response.raise_for_status()
    job_id = response.json().get("job_id")
    print(f"□ job_id: {job_id}")

    # get job status
    while True:
        response = requests.get(f"{BASE_URL}/jobs/{job_id}", headers=headers).json()
        status = response.get("status")
        print(f"– status: {status}")
        if status == "done":
            break
        if status == "failed":
            error = response.get("error")
            raise RuntimeError(f"– status: {status}, error: {error}")
        time.sleep(5)

    # list downloads
    downloads = requests.get(f"{BASE_URL}/jobs/{job_id}/downloads", headers=headers).json()
    filenames = [download["filename"] for download in downloads]
    print(f"– downloads: {', '.join(filenames)}")

    # download files
    if DOWNLOAD_FILES:
        downloads_dir = DOWNLOADS_DIR / job_id
        downloads_dir.mkdir(exist_ok=True, parents=True)

        for download in downloads:
            key = download["key"]
            filename = download["filename"]
            print(f"- downloading: {filename}")
            response = requests.get(f"{BASE_URL}/jobs/{job_id}/download/{key}", headers=headers)
            response.raise_for_status()
            with open(downloads_dir / filename, "wb") as file:
                file.write(response.content)

    print(f"■ job_id: {job_id}")

if __name__ == "__main__":
    main()
