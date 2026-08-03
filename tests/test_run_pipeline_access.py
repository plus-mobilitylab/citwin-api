import argparse
from pathlib import Path

from api.app import delete_old_jobs
from pipeline.run import run_pipeline_access, setup_logging

parser = argparse.ArgumentParser()
parser.add_argument("--upload-netascore", action="store_true")
parser.add_argument("--include-perception", action="store_false")
args = parser.parse_args()

UPLOAD_NETASCORE = args.upload_netascore
INCLUDE_PERCEPTION = args.include_percetion

TEST_DATA_DIR = Path(__file__).resolve().parents[0] / "data"

setup_logging()


def main():
    delete_old_jobs()

    kwargs = dict(
        od_clusters_a=TEST_DATA_DIR / "b_klynger.gpkg",
        od_clusters_b=TEST_DATA_DIR / "a_klynger.gpkg",
        od_table=TEST_DATA_DIR / "Data_2023_0099_Tabel_1.csv",
        pois=TEST_DATA_DIR / "dynlayer_skodstrup.gpkg",
        od_clusters_a_id_field="klynge_id",
        od_clusters_a_count_field="Beboere",
        od_clusters_b_id_field="klynge_id",
        od_clusters_b_count_field="Arbejdere",
        od_table_a_id_field="Bopael_klynge_id",
        od_table_b_id_field="Arbejssted_klynge_id",
        od_table_trips_field="Antal",
        pois_id_field="stopnummer",
        travel_mode="bike",
        output_format="GPKG",
        seed=0,
    )

    if UPLOAD_NETASCORE:
        kwargs["netascore_gpkg"] = TEST_DATA_DIR / "netascore_20251008_200432.gpkg"

    if INCLUDE_PERCEPTION:
        kwargs["netascore_gpkg"] = TEST_DATA_DIR / "streetscapes_perception.csv"

    run_pipeline_access(**kwargs)


if __name__ == "__main__":
    main()
