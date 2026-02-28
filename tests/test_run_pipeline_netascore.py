from api.app import delete_old_jobs
from pipeline.run import run_pipeline_netascore, setup_logging

setup_logging()


def main():
    delete_old_jobs()

    kwargs = dict(
        target_srid=32632,
        bbox_str="56.1941,10.1816,56.3441,10.4393",
        output_format="GPKG",
    )

    run_pipeline_netascore(**kwargs)


if __name__ == "__main__":
    main()
