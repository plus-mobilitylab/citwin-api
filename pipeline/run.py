import logging
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict

import geopandas as gpd
import pandas as pd
from networkx import Graph

from api.paths import JOBS_DIR, NETASCORE_DIR, NETASCORE_PROFILE_BIKE, NETASCORE_PROFILE_WALK, NETASCORE_SETTINGS
from pipeline.steps.build_graphs import build_graph, build_graph_quality
from pipeline.steps.disaggregate_data import distribute_points_in_raster, disaggregate_table_to_edges
from pipeline.steps.evaluate_stops import evaluate_accessibility
from pipeline.steps.filter_network import add_network_distance
from pipeline.steps.handle_data import calculate_distance, ensure_wgs84, get_utm_srid, compute_bbox_str, filter_gdf
from pipeline.steps.generate_netascore import update_settings, run_netascore
from pipeline.steps.snap_points import build_balltree, snap_with_balltree

DISTANCE_THRESHOLD = calculate_distance(15, 15)
INDEX_THRESHOLD = 0.5

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------------------------------------------------
# logging setup
# ----------------------------------------------------------------------------------------------------------------------

def setup_logging():
    root = logging.getLogger()
    if root.hasHandlers():
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    for noisy in ["pyogrio"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

# ----------------------------------------------------------------------------------------------------------------------
# context container
# ----------------------------------------------------------------------------------------------------------------------

@dataclass
class PipelineContext:
    job_id: str
    job_dir: Path
    output_format: str
    seed: Optional[int] = None
    generated_netascore: bool = False

    od_clusters_a_gdf: Optional[gpd.GeoDataFrame] = None
    od_clusters_b_gdf: Optional[gpd.GeoDataFrame] = None
    od_table_df: Optional[pd.DataFrame] = None
    stops_gdf: Optional[gpd.GeoDataFrame] = None
    stops_buffer_gdf: Optional[gpd.GeoSeries] = None
    bbox_str: Optional[str] = None
    target_srid: Optional[int] = None

    od_points_a_gdf: Optional[gpd.GeoDataFrame] = None
    od_points_b_gdf: Optional[gpd.GeoDataFrame] = None
    od_edges_gdf: Optional[gpd.GeoDataFrame] = None

    netascore_gpkg: Optional[Path] = None
    netascore_edges_gdf: Optional[gpd.GeoDataFrame] = None
    netascore_nodes_gdf: Optional[gpd.GeoDataFrame] = None

    G_base: Optional[Graph] = None
    G_base_reversed: Optional[Graph] = None
    G_quality: Optional[Graph] = None
    G_quality_reversed: Optional[Graph] = None

    edges_base_gdf: Optional[gpd.GeoDataFrame] = None
    edges_quality_gdf: Optional[gpd.GeoDataFrame] = None
    routes_base_gdf: Optional[gpd.GeoDataFrame] = None
    routes_quality_gdf: Optional[gpd.GeoDataFrame] = None
    households_gdf: Optional[gpd.GeoDataFrame] = None
    outputs: Optional[Dict[str, Path]] = None

# ----------------------------------------------------------------------------------------------------------------------
# base class for pipeline step
# ----------------------------------------------------------------------------------------------------------------------

class PipelineStep:
    def run(self, ctx):
        raise NotImplementedError()

    def __call__(self, ctx, idx=None, total=None):
        logger.info(f"◯ [{idx}/{total}] {self.__class__.__name__}")
        t0 = time.time()
        result = self.run(ctx)
        t1 = time.time()
        logger.info(f"● [{idx}/{total}] {self.__class__.__name__} ({t1 - t0:.1f} s)")
        return result

# ----------------------------------------------------------------------------------------------------------------------
# pipeline steps
# ----------------------------------------------------------------------------------------------------------------------

class HandleDataStep(PipelineStep):
    def __init__(self, od_clusters_a, od_clusters_b, od_table, stops):
        self.od_clusters_a = od_clusters_a
        self.od_clusters_b = od_clusters_b
        self.od_table = od_table
        self.stops = stops

    def run(self, ctx):
        ctx.od_clusters_a_gdf = ensure_wgs84(gpd.read_file(self.od_clusters_a))
        ctx.od_clusters_b_gdf = ensure_wgs84(gpd.read_file(self.od_clusters_b))
        ctx.od_table_df = pd.read_csv(self.od_table, delimiter=";")
        ctx.stops_gdf = ensure_wgs84(gpd.read_file(self.stops))

        ctx.target_srid = get_utm_srid(ctx.stops_gdf)
        logger.info(f"– target_srid: {ctx.target_srid}")
        ctx.stops_buffer_gdf = ctx.stops_gdf.to_crs(epsg=ctx.target_srid).geometry.buffer(DISTANCE_THRESHOLD * 2).to_crs(epsg=4326)
        ctx.bbox_str = compute_bbox_str(ctx.stops_buffer_gdf)
        logger.info(f"– bbox_str: {ctx.bbox_str}")

        logger.info(f"– keeping clusters within distance <= {DISTANCE_THRESHOLD * 2} m")
        ctx.od_clusters_a_gdf = filter_gdf(ctx.od_clusters_a_gdf, ctx.stops_buffer_gdf)
        ctx.od_clusters_b_gdf = filter_gdf(ctx.od_clusters_b_gdf, ctx.stops_buffer_gdf)


class DisaggregateDataStep(PipelineStep):
    def __init__(self, fields):
        self.fields = fields

    def run(self, ctx):
        a_id, a_count, b_id, b_count, t_a_id, t_b_id, t_trips = self.fields

        logger.info("– distribute points in clusters")
        ctx.od_points_a_gdf = distribute_points_in_raster(ctx.od_clusters_a_gdf, a_id, a_count, ctx.seed)
        ctx.od_points_b_gdf = distribute_points_in_raster(ctx.od_clusters_b_gdf, b_id, b_count, ctx.seed)

        logger.info("– disaggregate table to edges")
        ctx.od_edges_gdf = disaggregate_table_to_edges(ctx.od_points_a_gdf, ctx.od_points_b_gdf, ctx.od_table_df, t_a_id, t_b_id, t_trips, ctx.seed)


class GenerateNetascoreStep(PipelineStep):
    def run(self, ctx):
        if ctx.netascore_gpkg is None:
            case_id = "default_case"
            netascore_data_dir = NETASCORE_DIR / "data"
            netascore_data_dir.mkdir(parents=True, exist_ok=True)

            logger.info("– update settings")
            shutil.copy(NETASCORE_PROFILE_BIKE, netascore_data_dir / "profile_bike.yml")
            shutil.copy(NETASCORE_PROFILE_WALK, netascore_data_dir / "profile_walk.yml")
            update_settings(NETASCORE_SETTINGS, netascore_data_dir / "settings.yml", ctx.target_srid, ctx.bbox_str,
                            case_id)

            logger.info("– run netascore")
            run_netascore(NETASCORE_DIR, netascore_data_dir / "settings.yml")
            ctx.netascore_gpkg = ctx.job_dir / "netascore.gpkg"
            shutil.copy(netascore_data_dir / f"netascore_{case_id}.gpkg", ctx.netascore_gpkg)
            shutil.rmtree(netascore_data_dir, ignore_errors=True)
            ctx.generated_netascore = True

        ctx.netascore_edges_gdf = ensure_wgs84(gpd.read_file(ctx.netascore_gpkg, layer="edge"))
        ctx.netascore_nodes_gdf = ensure_wgs84(gpd.read_file(ctx.netascore_gpkg, layer="node"))


class BuildGraphsStep(PipelineStep):
    def run(self, ctx):
        graph_nodes_gdf = ctx.netascore_nodes_gdf.reset_index().rename(columns={'index': 'node_id'})
        graph_nodes_gdf['node_id'] = graph_nodes_gdf['node_id'] + 1

        logger.info("- building base graph")
        ctx.G_base = build_graph(ctx.netascore_edges_gdf, graph_nodes_gdf)
        ctx.G_base_reversed = ctx.G_base.reverse(copy=True)

        logger.info(f"- building quality graph with index >= {INDEX_THRESHOLD}")
        ctx.G_quality = build_graph_quality(ctx.netascore_edges_gdf, graph_nodes_gdf, INDEX_THRESHOLD)
        ctx.G_quality_reversed = ctx.G_quality.reverse(copy=True)


class SnapPointsStep(PipelineStep):
    def run(self, ctx):
        logger.info("– building balltree on graph nodes")
        balltree_base, node_ids_base = build_balltree(ctx.G_base)
        balltree_quality, node_ids_quality = build_balltree(ctx.G_quality)

        logger.info("– snapping points to graph nodes")
        ctx.od_points_a_gdf = snap_with_balltree(ctx.od_points_a_gdf, balltree_base, node_ids_base)
        ctx.od_points_b_gdf = snap_with_balltree(ctx.od_points_b_gdf, balltree_base, node_ids_base)
        ctx.stops_gdf = snap_with_balltree(ctx.stops_gdf, balltree_base, node_ids_base, "node_id_base")
        ctx.stops_gdf = snap_with_balltree(ctx.stops_gdf, balltree_quality, node_ids_quality, "node_id_quality")


class FilterNetworkStep(PipelineStep):
    def run(self, ctx):
        logger.info("– adding network distance")
        ctx.od_edges_gdf = add_network_distance(ctx.od_edges_gdf, ctx.od_points_a_gdf, ctx.od_points_b_gdf, ctx.G_base)

        logger.info(f"– removing edges and points with distance > {DISTANCE_THRESHOLD} m")
        ctx.od_edges_gdf = ctx.od_edges_gdf[ctx.od_edges_gdf["distance"] <= DISTANCE_THRESHOLD]
        valid_a_ids = ctx.od_edges_gdf["point_a_id"].unique()
        valid_b_ids = ctx.od_edges_gdf["point_b_id"].unique()
        ctx.od_points_a_gdf = ctx.od_points_a_gdf[ctx.od_points_a_gdf["point_id"].isin(valid_a_ids)]
        ctx.od_points_b_gdf = ctx.od_points_b_gdf[ctx.od_points_b_gdf["point_id"].isin(valid_b_ids)]


class EvaluateStopsStep(PipelineStep):
    def __init__(self, stops_id_field):
        self.stops_id_field = stops_id_field

    def run(self, ctx):
        ctx.edges_base_gdf, ctx.edges_quality_gdf, ctx.routes_base_gdf, ctx.routes_quality_gdf, ctx.stops_gdf, ctx.households_gdf = evaluate_accessibility(
            ctx.netascore_edges_gdf, ctx.stops_gdf, ctx.od_points_a_gdf, self.stops_id_field, ctx.G_base, ctx.G_quality,
            ctx.G_base_reversed, ctx.G_quality_reversed, DISTANCE_THRESHOLD
        )


class ExportResultsStep(PipelineStep):
    def run(self, ctx):
        extension = {"GeoJSON": "geojson", "GPKG": "gpkg"}[ctx.output_format]
        driver = {"GeoJSON": "GeoJSON", "GPKG": "GPKG"}[ctx.output_format]

        od_points_a = ctx.job_dir / f"od_points_a.{extension}"
        od_points_b = ctx.job_dir / f"od_points_b.{extension}"
        od_edges = ctx.job_dir / f"od_edges.{extension}"
        edges_base = ctx.job_dir / f"edges_base.{extension}"
        edges_quality = ctx.job_dir / f"edges_quality.{extension}"
        routes_base = ctx.job_dir / f"routes_base.{extension}"
        routes_quality = ctx.job_dir / f"routes_quality.{extension}"
        stops_updated = ctx.job_dir / f"stops_updated.{extension}"
        households = ctx.job_dir / f"households.{extension}"

        ctx.od_points_a_gdf.to_file(od_points_a, driver=driver)
        ctx.od_points_b_gdf.to_file(od_points_b, driver=driver)
        ctx.od_edges_gdf.to_file(od_edges, driver=driver)
        ctx.edges_base_gdf.to_file(edges_base, driver=driver)
        ctx.edges_quality_gdf.to_file(edges_quality, driver=driver)
        ctx.routes_base_gdf.to_file(routes_base, driver=driver)
        ctx.routes_quality_gdf.to_file(routes_quality, driver=driver)
        ctx.stops_gdf.to_file(stops_updated, driver=driver)
        ctx.households_gdf.to_file(households, driver=driver)

        outputs = {
            "stops_updated": stops_updated,
            "households": households
        }

        if ctx.generated_netascore:
            outputs["netascore_gpkg"] = ctx.netascore_gpkg

        ctx.outputs = outputs

# ----------------------------------------------------------------------------------------------------------------------
# main orchestrator
# ----------------------------------------------------------------------------------------------------------------------

def run_pipeline(
        od_clusters_a: Path,
        od_clusters_b: Path,
        od_table: Path,
        stops: Path,

        od_clusters_a_id_field: str,
        od_clusters_a_count_field: str,
        od_clusters_b_id_field: str,
        od_clusters_b_count_field: str,
        od_table_a_id_field: str,
        od_table_b_id_field: str,
        od_table_trips_field: str,
        stops_id_field: str,

        netascore_gpkg: Optional[Path] = None,
        output_format: str = "GeoJSON",
        seed: Optional[int] = None,

        job_dir: Optional[Path] = None,
) -> Dict[str, Path]:
    if output_format not in {"GeoJSON", "GPKG"}:
        raise ValueError(f"Unsupported output format: {output_format}")

    if job_dir is None:
        job_id = str(uuid.uuid4())
        job_dir = JOBS_DIR / job_id
    else:
        job_id = job_dir.name

    job_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"□ job_id: {job_id}")
    t0 = time.time()

    ctx = PipelineContext(
        job_id=job_id,
        job_dir=job_dir,
        netascore_gpkg=netascore_gpkg,
        output_format=output_format,
        seed=seed
    )

    fields = (
        od_clusters_a_id_field, od_clusters_a_count_field,
        od_clusters_b_id_field, od_clusters_b_count_field,
        od_table_a_id_field, od_table_b_id_field, od_table_trips_field
    )

    steps = [
        HandleDataStep(od_clusters_a, od_clusters_b, od_table, stops),
        DisaggregateDataStep(fields),
        GenerateNetascoreStep(),
        BuildGraphsStep(),
        SnapPointsStep(),
        FilterNetworkStep(),
        EvaluateStopsStep(stops_id_field),
        ExportResultsStep()
    ]
    for i, step in enumerate(steps, 1):
        step(ctx, idx=i, total=len(steps))

    t1 = time.time()
    logger.info(f"■ job_id: {job_id} ({t1 - t0:.1f} s)")

    return ctx.outputs
