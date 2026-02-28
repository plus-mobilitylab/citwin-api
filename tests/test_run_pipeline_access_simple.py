import argparse
from pathlib import Path

from api.app import delete_old_jobs
from pipeline.run import run_pipeline_access_simple, setup_logging

parser = argparse.ArgumentParser()
parser.add_argument("--upload-netascore", action="store_true")
args = parser.parse_args()

UPLOAD_NETASCORE = args.upload_netascore

TEST_DATA_DIR = Path(__file__).resolve().parents[0] / "data"

setup_logging()


def main():
    delete_old_jobs()

    kwargs = dict(
        od_clusters_a=TEST_DATA_DIR / "b_klynger.gpkg",
        pois=TEST_DATA_DIR / "dynlayer_skodstrup.gpkg",
        od_clusters_a_id_field="klynge_id",
        od_clusters_a_count_field="Beboere",
        pois_id_field="stopnummer",
        mode="bike",
        output_format="GPKG",
        seed=0,
    )

    if UPLOAD_NETASCORE:
        kwargs["netascore_gpkg"] = TEST_DATA_DIR / "netascore_20251008_200432.gpkg"

    run_pipeline_access_simple(**kwargs)


if __name__ == "__main__":
    main()
