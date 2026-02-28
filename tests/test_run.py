import argparse
from pathlib import Path

from api.app import delete_old_jobs
from pipeline.run import run_pipeline, setup_logging

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
        od_clusters_b=TEST_DATA_DIR / "a_klynger.gpkg",
        od_table=TEST_DATA_DIR / "Data_2023_0099_Tabel_1.csv",
        stops=TEST_DATA_DIR / "dynlayer.gpkg",
        od_clusters_a_id_field="klynge_id",
        od_clusters_a_count_field="Beboere",
        od_clusters_b_id_field="klynge_id",
        od_clusters_b_count_field="Arbejdere",
        od_table_a_id_field="Bopael_klynge_id",
        od_table_b_id_field="Arbejssted_klynge_id",
        od_table_trips_field="Antal",
        stops_id_field="stopnummer",
        output_format="GPKG",
        seed=None,
    )

    if UPLOAD_NETASCORE:
        kwargs["netascore_gpkg"] = TEST_DATA_DIR / "netascore_20251008_200432.gpkg"

    run_pipeline(**kwargs)


if __name__ == "__main__":
    main()
