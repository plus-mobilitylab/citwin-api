import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, List

import geopandas as gpd
import pandas as pd
from networkx import Graph

from api.paths import JOBS_DIR, NETASCORE_DIR, NETASCORE_PROFILE_BIKE, NETASCORE_PROFILE_WALK, NETASCORE_SETTINGS
from pipeline.steps.build_graphs import build_graph, make_subgraph, keep_largest_component, remove_small_components
from pipeline.steps.disaggregate_data import distribute_points_in_raster, disaggregate_table_to_edges
from pipeline.steps.evaluate_pois import evaluate_access
from pipeline.steps.filter_trips import compute_network_distances_with_cutoff
from pipeline.steps.generate_netascore import update_settings, run_netascore
from pipeline.steps.handle_data import calculate_distance, ensure_wgs84, get_utm_srid, compute_bbox_str, filter_gdf
from pipeline.steps.snap_points import build_strtree, snap_with_strtree

TRAVEL_MODE_DEFAULTS = {
    "bike": {
        "travel_time_min": 15.0,
        "travel_speed_kmh": 12.0,
        "detour_threshold": 1.5,
        "index_threshold": 0.5,
        "length_minimum": 0.0,
    },
    "walk": {
        "travel_time_min": 15.0,
        "travel_speed_kmh": 5.0,
        "detour_threshold": 1.5,
        "index_threshold": 0.35,
        "length_minimum": 0.0,
    },
}

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
# job management
# ----------------------------------------------------------------------------------------------------------------------

def save_parameters(job_dir: Path, job_id: str, target_srid: int, bbox_str: str):
    data = {
        "job_id": job_id,
        "target_srid": target_srid,
        "bbox_str": bbox_str,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    with open(job_dir / "job.json", "w") as f:
        json.dump(data, f, indent=4)


def find_cached_netascore_gpkg(target_srid: int, bbox_str: str, current_job_dir: Path) -> Optional[Path]:
    timestamp_cutoff = datetime.now(timezone.utc) - timedelta(days=1)

    for job_dir in JOBS_DIR.iterdir():
        if not job_dir.is_dir() or job_dir == current_job_dir:
            continue

        job_file = job_dir / "job.json"
        if not job_file.exists():
            continue

        with open(job_file, "r") as f:
            job_data = json.load(f)

        timestamp = datetime.fromisoformat(job_data.get("timestamp"))
        if timestamp < timestamp_cutoff:
            continue

        if job_data.get("target_srid") == target_srid and job_data.get("bbox_str") == bbox_str:
            netascore_path = job_dir / "netascore.gpkg"
            if netascore_path.exists():
                return netascore_path

    return None

# ----------------------------------------------------------------------------------------------------------------------
# context container
# ----------------------------------------------------------------------------------------------------------------------

@dataclass
class PipelineAccessContext:
    job_id: str
    job_dir: Path
    output_format: str

    travel_mode: str
    travel_time_min: float
    travel_speed_kmh: float
    distance_threshold_m: float
    detour_threshold: float
    index_threshold: float
    length_minimum: Optional[float] = None

    seed: Optional[int] = None

    use_cached_netascore: bool = False
    generated_netascore: bool = False

    od_clusters_a_gdf: Optional[gpd.GeoDataFrame] = None
    od_clusters_b_gdf: Optional[gpd.GeoDataFrame] = None
    od_table_df: Optional[pd.DataFrame] = None
    pois_gdf: Optional[gpd.GeoDataFrame] = None
    pois_buffer_gdf: Optional[gpd.GeoSeries] = None
    bbox_str: Optional[str] = None
    target_srid: Optional[int] = None

    od_points_a_gdf: Optional[gpd.GeoDataFrame] = None
    od_points_b_gdf: Optional[gpd.GeoDataFrame] = None
    od_edges_gdf: Optional[gpd.GeoDataFrame] = None

    netascore_gpkg: Optional[Path] = None
    netascore_edges_gdf: Optional[gpd.GeoDataFrame] = None
    netascore_nodes_gdf: Optional[gpd.GeoDataFrame] = None

    G_base: Optional[Graph] = None
    G_quality: Optional[Graph] = None

    edges_base_gdf: Optional[gpd.GeoDataFrame] = None
    edges_quality_gdf: Optional[gpd.GeoDataFrame] = None
    routes_base_gdf: Optional[gpd.GeoDataFrame] = None
    routes_quality_gdf: Optional[gpd.GeoDataFrame] = None
    residents_gdf: Optional[gpd.GeoDataFrame] = None
    outputs: Optional[Dict[str, Path]] = None


@dataclass
class PipelineNetascoreContext:
    job_id: str
    job_dir: Path
    output_format: str

    bbox_str: str
    target_srid: int

    use_cached_netascore: bool = False
    generated_netascore: bool = False

    netascore_gpkg: Optional[Path] = None

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
    def __init__(self, od_clusters_a, od_clusters_b, od_table, pois, pois_id_field: Optional[str] = None, pois_id_list: Optional[List] = None):
        self.od_clusters_a = od_clusters_a
        self.od_clusters_b = od_clusters_b
        self.od_table = od_table
        self.pois = pois
        self.pois_id_field = pois_id_field
        self.pois_id_list = pois_id_list

    def run(self, ctx):
        logger.info("– load input data")
        ctx.od_clusters_a_gdf = ensure_wgs84(gpd.read_file(self.od_clusters_a))
        ctx.od_clusters_b_gdf = ensure_wgs84(gpd.read_file(self.od_clusters_b))
        ctx.od_table_df = pd.read_csv(self.od_table, delimiter=";")
        ctx.pois_gdf = ensure_wgs84(gpd.read_file(self.pois))

        if self.pois_id_field and self.pois_id_list:
            logger.info(f"- filter pois by list: {len(self.pois_id_list)}")
            ctx.pois_gdf = ctx.pois_gdf[ctx.pois_gdf[self.pois_id_field].isin(self.pois_id_list)]

        ctx.target_srid = get_utm_srid(ctx.pois_gdf)
        logger.info(f"– target_srid: {ctx.target_srid}")
        ctx.pois_buffer_gdf = ctx.pois_gdf.to_crs(epsg=ctx.target_srid).geometry.buffer(ctx.distance_threshold_m * 2).to_crs(epsg=4326)
        ctx.bbox_str = compute_bbox_str(ctx.pois_buffer_gdf)
        logger.info(f"– bbox_str: {ctx.bbox_str}")

        logger.info(f"– keep only clusters within distance <= {ctx.distance_threshold_m * 2} m")
        ctx.od_clusters_a_gdf = filter_gdf(ctx.od_clusters_a_gdf, ctx.pois_buffer_gdf)
        ctx.od_clusters_b_gdf = filter_gdf(ctx.od_clusters_b_gdf, ctx.pois_buffer_gdf)


class HandleDataSimpleStep(PipelineStep):
    def __init__(self, od_clusters_a, pois, pois_id_field: Optional[str] = None, pois_id_list: Optional[List] = None):
        self.od_clusters_a = od_clusters_a
        self.pois = pois
        self.pois_id_field = pois_id_field
        self.pois_id_list = pois_id_list

    def run(self, ctx):
        logger.info("– load input data")
        ctx.od_clusters_a_gdf = ensure_wgs84(gpd.read_file(self.od_clusters_a))
        ctx.pois_gdf = ensure_wgs84(gpd.read_file(self.pois))

        if self.pois_id_field and self.pois_id_list:
            logger.info(f"- filter pois by list: {len(self.pois_id_list)}")
            ctx.pois_gdf = ctx.pois_gdf[ctx.pois_gdf[self.pois_id_field].isin(self.pois_id_list)]

        ctx.target_srid = get_utm_srid(ctx.pois_gdf)
        logger.info(f"– target_srid: {ctx.target_srid}")
        ctx.pois_buffer_gdf = ctx.pois_gdf.to_crs(epsg=ctx.target_srid).geometry.buffer(ctx.distance_threshold_m * 2).to_crs(epsg=4326)
        ctx.bbox_str = compute_bbox_str(ctx.pois_buffer_gdf)
        logger.info(f"– bbox_str: {ctx.bbox_str}")

        logger.info(f"– keep only clusters within distance <= {ctx.distance_threshold_m * 2} m")
        ctx.od_clusters_a_gdf = filter_gdf(ctx.od_clusters_a_gdf, ctx.pois_buffer_gdf)


class SaveParametersStep(PipelineStep):
    def run(self, ctx):
        save_parameters(ctx.job_dir, ctx.job_id, ctx.target_srid, ctx.bbox_str)


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


class DisaggregateDataSimpleStep(PipelineStep):
    def __init__(self, fields):
        self.fields = fields

    def run(self, ctx):
        a_id, a_count = self.fields

        logger.info("– distribute points in cluster")
        ctx.od_points_a_gdf = distribute_points_in_raster(ctx.od_clusters_a_gdf, a_id, a_count, ctx.seed)


class GenerateNetascoreStep(PipelineStep):
    def run(self, ctx):
        if ctx.netascore_gpkg is None:
            if ctx.use_cached_netascore:
                cached_netascore_gpkg = find_cached_netascore_gpkg(ctx.target_srid, ctx.bbox_str, ctx.job_dir)
                if cached_netascore_gpkg:
                    logger.info(f"– load cached netascore")
                    ctx.netascore_gpkg = ctx.job_dir / "netascore.gpkg"
                    shutil.copy(cached_netascore_gpkg, ctx.netascore_gpkg)
                    ctx.generated_netascore = True
                    return

            case_id = "default_case"
            netascore_data_dir = NETASCORE_DIR / "data"
            netascore_data_dir.mkdir(parents=True, exist_ok=True)

            logger.info("– copy netascore profiles")
            shutil.copy(NETASCORE_PROFILE_BIKE, netascore_data_dir / "profile_bike.yml")
            shutil.copy(NETASCORE_PROFILE_WALK, netascore_data_dir / "profile_walk.yml")

            logger.info("– update netascore settings")
            update_settings(NETASCORE_SETTINGS, netascore_data_dir / "settings.yml", ctx.target_srid, ctx.bbox_str, case_id)

            logger.info("– run netascore")
            run_netascore(NETASCORE_DIR, netascore_data_dir / "settings.yml")
            ctx.netascore_gpkg = ctx.job_dir / "netascore.gpkg"
            shutil.copy(netascore_data_dir / f"netascore_{case_id}.gpkg", ctx.netascore_gpkg)
            shutil.rmtree(netascore_data_dir, ignore_errors=True)
            ctx.generated_netascore = True


class BuildGraphsStep(PipelineStep):
    def run(self, ctx):
        logger.info("- load netascore data")
        ctx.netascore_edges_gdf = ensure_wgs84(gpd.read_file(ctx.netascore_gpkg, layer="edge"))
        ctx.netascore_nodes_gdf = ensure_wgs84(gpd.read_file(ctx.netascore_gpkg, layer="node"))

        ctx.netascore_edges_gdf = ctx.netascore_edges_gdf.reset_index().rename(columns={'index': 'edge_id'})
        ctx.netascore_edges_gdf['edge_id'] = ctx.netascore_edges_gdf['edge_id'] + 1

        ctx.netascore_nodes_gdf = ctx.netascore_nodes_gdf.reset_index().rename(columns={'index': 'node_id'})
        ctx.netascore_nodes_gdf['node_id'] = ctx.netascore_nodes_gdf['node_id'] + 1

        logger.info("- build graph")
        G = build_graph(ctx.netascore_edges_gdf, ctx.netascore_nodes_gdf)
        G = keep_largest_component(G)

        logger.info(f"- make base subgraph ({ctx.travel_mode})")
        ctx.G_base = make_subgraph(G, ctx.travel_mode, walk_segments_for_bike=False)
        ctx.G_base = remove_small_components(ctx.G_base, 10)

        logger.info(f"- make quality subgraph ({ctx.travel_mode}) with index >= {ctx.index_threshold} or length <= {ctx.length_minimum} m")
        ctx.G_quality = make_subgraph(G, ctx.travel_mode, ctx.index_threshold, ctx.length_minimum, walk_segments_for_bike=False)
        ctx.G_quality = remove_small_components(ctx.G_quality, 10)


class SnapPointsStep(PipelineStep):
    def run(self, ctx):
        logger.info("– build spatial index")
        edge_index_base, edge_map_base = build_strtree(ctx.G_base)
        edge_index_quality, edge_map_quality = build_strtree(ctx.G_quality)

        logger.info("– snap points to nearest edge nodes")
        ctx.od_points_a_gdf = snap_with_strtree(ctx.od_points_a_gdf, ctx.G_base, edge_index_base, edge_map_base)
        ctx.od_points_b_gdf = snap_with_strtree(ctx.od_points_b_gdf, ctx.G_base, edge_index_base, edge_map_base)
        ctx.pois_gdf = snap_with_strtree(ctx.pois_gdf, ctx.G_quality, edge_index_quality, edge_map_quality)


class SnapPointsSimpleStep(PipelineStep):
    def run(self, ctx):
        logger.info("– build spatial index")
        edge_index_base, edge_map_base = build_strtree(ctx.G_base)
        edge_index_quality, edge_map_quality = build_strtree(ctx.G_quality)

        logger.info("– snap points to nearest edge nodes")
        ctx.od_points_a_gdf = snap_with_strtree(ctx.od_points_a_gdf, ctx.G_base, edge_index_base, edge_map_base)
        ctx.pois_gdf = snap_with_strtree(ctx.pois_gdf, ctx.G_quality, edge_index_quality, edge_map_quality)


class FilterTripsStep(PipelineStep):
    def run(self, ctx):
        logger.info("– add network distance")
        ctx.od_edges_gdf = compute_network_distances_with_cutoff(ctx.od_edges_gdf, ctx.od_points_a_gdf, ctx.od_points_b_gdf, ctx.G_base, ctx.distance_threshold_m)

        logger.info(f"– remove edges and points with distance <= {ctx.distance_threshold_m} m")
        ctx.od_edges_gdf = ctx.od_edges_gdf[ctx.od_edges_gdf["distance"] > ctx.distance_threshold_m]
        ctx.od_points_a_gdf = ctx.od_points_a_gdf[ctx.od_points_a_gdf["point_id"].isin(ctx.od_edges_gdf["point_a_id"].unique())]
        ctx.od_points_b_gdf = ctx.od_points_b_gdf[ctx.od_points_b_gdf["point_id"].isin(ctx.od_edges_gdf["point_b_id"].unique())]


class EvaluatePOIsStep(PipelineStep):
    def __init__(self, pois_id_field):
        self.pois_id_field = pois_id_field

    def run(self, ctx):
        ctx.edges_base_gdf, ctx.edges_quality_gdf, ctx.routes_base_gdf, ctx.routes_quality_gdf, ctx.pois_gdf, ctx.residents_gdf = evaluate_access(
            ctx.netascore_edges_gdf, ctx.pois_gdf, ctx.od_points_a_gdf, self.pois_id_field,
            ctx.G_base, ctx.G_quality, ctx.travel_mode,
            ctx.distance_threshold_m, ctx.detour_threshold
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
        pois_output = ctx.job_dir / f"pois_output.{extension}"
        residents = ctx.job_dir / f"residents.{extension}"

        ctx.od_points_a_gdf.to_file(od_points_a, driver=driver)
        ctx.od_points_b_gdf.to_file(od_points_b, driver=driver)
        ctx.od_edges_gdf.to_file(od_edges, driver=driver)
        ctx.edges_base_gdf.to_file(edges_base, driver=driver)
        ctx.edges_quality_gdf.to_file(edges_quality, driver=driver)
        ctx.routes_base_gdf.to_file(routes_base, driver=driver)
        ctx.routes_quality_gdf.to_file(routes_quality, driver=driver)
        ctx.pois_gdf.to_file(pois_output, driver=driver)
        ctx.residents_gdf.to_file(residents, driver=driver)

        outputs = {
            "pois_output": pois_output,
            "residents": residents
        }

        if ctx.generated_netascore:
            if ctx.output_format == "GPKG":
                outputs["netascore"] = ctx.netascore_gpkg
            elif ctx.output_format == "GeoJSON":
                outputs["netascore"] = ctx.netascore_gpkg

                netascore_edges = ctx.job_dir / f"netascore_edges.{extension}"
                netascore_nodes = ctx.job_dir / f"netascore_nodes.{extension}"

                netascore_edges_gdf = ensure_wgs84(gpd.read_file(ctx.netascore_gpkg, layer="edge"))
                netascore_nodes_gdf = ensure_wgs84(gpd.read_file(ctx.netascore_gpkg, layer="node"))

                netascore_edges_gdf.to_file(netascore_edges, driver=driver)
                netascore_nodes_gdf.to_file(netascore_nodes, driver=driver)

                outputs["netascore_edges"] = netascore_edges
                outputs["netascore_nodes"] = netascore_nodes

        ctx.outputs = outputs


class ExportResultsSimpleStep(PipelineStep):
    def run(self, ctx):
        extension = {"GeoJSON": "geojson", "GPKG": "gpkg"}[ctx.output_format]
        driver = {"GeoJSON": "GeoJSON", "GPKG": "GPKG"}[ctx.output_format]

        od_points_a = ctx.job_dir / f"od_points_a.{extension}"
        edges_base = ctx.job_dir / f"edges_base.{extension}"
        edges_quality = ctx.job_dir / f"edges_quality.{extension}"
        routes_base = ctx.job_dir / f"routes_base.{extension}"
        routes_quality = ctx.job_dir / f"routes_quality.{extension}"
        pois_output = ctx.job_dir / f"pois_output.{extension}"
        residents = ctx.job_dir / f"residents.{extension}"

        ctx.od_points_a_gdf.to_file(od_points_a, driver=driver)
        ctx.edges_base_gdf.to_file(edges_base, driver=driver)
        ctx.edges_quality_gdf.to_file(edges_quality, driver=driver)
        ctx.routes_base_gdf.to_file(routes_base, driver=driver)
        ctx.routes_quality_gdf.to_file(routes_quality, driver=driver)
        ctx.pois_gdf.to_file(pois_output, driver=driver)
        ctx.residents_gdf.to_file(residents, driver=driver)

        outputs = {
            "pois_output": pois_output,
            "residents": residents
        }

        if ctx.generated_netascore:
            if ctx.output_format == "GPKG":
                outputs["netascore"] = ctx.netascore_gpkg
            elif ctx.output_format == "GeoJSON":
                outputs["netascore"] = ctx.netascore_gpkg

                netascore_edges = ctx.job_dir / f"netascore_edges.{extension}"
                netascore_nodes = ctx.job_dir / f"netascore_nodes.{extension}"

                netascore_edges_gdf = ensure_wgs84(gpd.read_file(ctx.netascore_gpkg, layer="edge"))
                netascore_nodes_gdf = ensure_wgs84(gpd.read_file(ctx.netascore_gpkg, layer="node"))

                netascore_edges_gdf.to_file(netascore_edges, driver=driver)
                netascore_nodes_gdf.to_file(netascore_nodes, driver=driver)

                outputs["netascore_edges"] = netascore_edges
                outputs["netascore_nodes"] = netascore_nodes

        ctx.outputs = outputs


class ExportResultsNetascoreStep(PipelineStep):
    def run(self, ctx):
        extension = {"GeoJSON": "geojson", "GPKG": "gpkg"}[ctx.output_format]
        driver = {"GeoJSON": "GeoJSON", "GPKG": "GPKG"}[ctx.output_format]

        outputs = {}

        if ctx.output_format == "GPKG":
            outputs["netascore"] = ctx.netascore_gpkg
        elif ctx.output_format == "GeoJSON":
            outputs["netascore"] = ctx.netascore_gpkg

            netascore_edges = ctx.job_dir / f"netascore_edges.{extension}"
            netascore_nodes = ctx.job_dir / f"netascore_nodes.{extension}"

            netascore_edges_gdf = ensure_wgs84(gpd.read_file(ctx.netascore_gpkg, layer="edge"))
            netascore_nodes_gdf = ensure_wgs84(gpd.read_file(ctx.netascore_gpkg, layer="node"))

            netascore_edges_gdf.to_file(netascore_edges, driver=driver)
            netascore_nodes_gdf.to_file(netascore_nodes, driver=driver)

            outputs["netascore_edges"] = netascore_edges
            outputs["netascore_nodes"] = netascore_nodes

        ctx.outputs = outputs

# ----------------------------------------------------------------------------------------------------------------------
# main orchestrator
# ----------------------------------------------------------------------------------------------------------------------

def run_pipeline_access(
        od_clusters_a: Path,
        od_clusters_b: Path,
        od_table: Path,
        pois: Path,

        od_clusters_a_id_field: str,
        od_clusters_a_count_field: str,
        od_clusters_b_id_field: str,
        od_clusters_b_count_field: str,
        od_table_a_id_field: str,
        od_table_b_id_field: str,
        od_table_trips_field: str,
        pois_id_field: str,

        travel_mode: str,
        travel_time_min: Optional[float] = None,
        travel_speed_kmh: Optional[float] = None,
        detour_threshold: Optional[float] = None,
        index_threshold: Optional[float] = None,
        length_minimum: Optional[float] = None,

        use_cached_netascore: bool = True,
        netascore_gpkg: Optional[Path] = None,
        pois_id_list: Optional[List] = None,
        output_format: str = "GeoJSON",
        seed: Optional[int] = None,
        job_dir: Optional[Path] = None,
        progress_callback = None
) -> Dict[str, Path]:
    if output_format not in {"GeoJSON", "GPKG"}:
        raise ValueError(f"Unsupported output format: {output_format}")

    if travel_mode not in TRAVEL_MODE_DEFAULTS:
        raise ValueError(f"Unsupported travel mode: {travel_mode}")

    if travel_time_min is None:
        travel_time_min = TRAVEL_MODE_DEFAULTS[travel_mode]["travel_time_min"]

    if travel_speed_kmh is None:
        travel_speed_kmh = TRAVEL_MODE_DEFAULTS[travel_mode]["travel_speed_kmh"]

    if detour_threshold is None:
        detour_threshold = TRAVEL_MODE_DEFAULTS[travel_mode]["detour_threshold"]

    if index_threshold is None:
        index_threshold = TRAVEL_MODE_DEFAULTS[travel_mode]["index_threshold"]

    if length_minimum is None:
        length_minimum = TRAVEL_MODE_DEFAULTS[travel_mode]["length_minimum"]

    if job_dir is None:
        job_id = str(uuid.uuid4())
        job_dir = JOBS_DIR / job_id
    else:
        job_id = job_dir.name

    job_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"□ job_id: {job_id}")
    t0 = time.time()

    distance_threshold_m = calculate_distance(travel_speed_kmh, travel_time_min)

    ctx = PipelineAccessContext(
        job_id=job_id,
        job_dir=job_dir,
        output_format=output_format,

        travel_mode=travel_mode,
        travel_time_min=travel_time_min,
        travel_speed_kmh=travel_speed_kmh,
        distance_threshold_m=distance_threshold_m,
        detour_threshold=detour_threshold,
        index_threshold=index_threshold,
        length_minimum=length_minimum,

        seed=seed,

        use_cached_netascore=use_cached_netascore,
        netascore_gpkg=netascore_gpkg,
    )

    fields = (
        od_clusters_a_id_field, od_clusters_a_count_field,
        od_clusters_b_id_field, od_clusters_b_count_field,
        od_table_a_id_field, od_table_b_id_field, od_table_trips_field
    )

    steps = [
        HandleDataStep(od_clusters_a, od_clusters_b, od_table, pois, pois_id_field, pois_id_list),
        SaveParametersStep(),
        DisaggregateDataStep(fields),
        GenerateNetascoreStep(),
        BuildGraphsStep(),
        SnapPointsStep(),
        FilterTripsStep(),
        EvaluatePOIsStep(pois_id_field),
        ExportResultsStep()
    ]

    for i, step in enumerate(steps, 1):
        if progress_callback:
            progress_callback(f"{i}/{len(steps)}")
        step(ctx, idx=i, total=len(steps))

    t1 = time.time()
    logger.info(f"■ job_id: {job_id} ({t1 - t0:.1f} s)")

    return ctx.outputs


def run_pipeline_access_simple(
        od_clusters_a: Path,
        pois: Path,

        od_clusters_a_id_field: str,
        od_clusters_a_count_field: str,
        pois_id_field: str,

        travel_mode: str,
        travel_time_min: Optional[float] = None,
        travel_speed_kmh: Optional[float] = None,
        detour_threshold: Optional[float] = None,
        index_threshold: Optional[float] = None,
        length_minimum: Optional[float] = None,

        use_cached_netascore: bool = True,
        netascore_gpkg: Optional[Path] = None,
        pois_id_list: Optional[List] = None,
        output_format: str = "GeoJSON",
        seed: Optional[int] = None,
        job_dir: Optional[Path] = None,
        progress_callback = None
) -> Dict[str, Path]:
    if output_format not in {"GeoJSON", "GPKG"}:
        raise ValueError(f"Unsupported output format: {output_format}")

    if travel_mode not in TRAVEL_MODE_DEFAULTS:
        raise ValueError(f"Unsupported travel mode: {travel_mode}")

    if travel_time_min is None:
        travel_time_min = TRAVEL_MODE_DEFAULTS[travel_mode]["travel_time_min"]

    if travel_speed_kmh is None:
        travel_speed_kmh = TRAVEL_MODE_DEFAULTS[travel_mode]["travel_speed_kmh"]

    if detour_threshold is None:
        detour_threshold = TRAVEL_MODE_DEFAULTS[travel_mode]["detour_threshold"]

    if index_threshold is None:
        index_threshold = TRAVEL_MODE_DEFAULTS[travel_mode]["index_threshold"]

    if length_minimum is None:
        length_minimum = TRAVEL_MODE_DEFAULTS[travel_mode]["length_minimum"]

    if job_dir is None:
        job_id = str(uuid.uuid4())
        job_dir = JOBS_DIR / job_id
    else:
        job_id = job_dir.name

    job_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"□ job_id: {job_id}")
    t0 = time.time()

    distance_threshold_m = calculate_distance(travel_speed_kmh, travel_time_min)

    ctx = PipelineAccessContext(
        job_id=job_id,
        job_dir=job_dir,
        output_format=output_format,

        travel_mode=travel_mode,
        travel_time_min=travel_time_min,
        travel_speed_kmh=travel_speed_kmh,
        distance_threshold_m=distance_threshold_m,
        detour_threshold=detour_threshold,
        index_threshold=index_threshold,
        length_minimum=length_minimum,

        seed=seed,

        use_cached_netascore=use_cached_netascore,
        netascore_gpkg=netascore_gpkg,
    )

    fields = (od_clusters_a_id_field, od_clusters_a_count_field)

    steps = [
        HandleDataSimpleStep(od_clusters_a, pois, pois_id_field, pois_id_list),
        SaveParametersStep(),
        DisaggregateDataSimpleStep(fields),
        GenerateNetascoreStep(),
        BuildGraphsStep(),
        SnapPointsSimpleStep(),
        EvaluatePOIsStep(pois_id_field),
        ExportResultsSimpleStep()
    ]

    for i, step in enumerate(steps, 1):
        if progress_callback:
            progress_callback(f"{i}/{len(steps)}")
        step(ctx, idx=i, total=len(steps))

    t1 = time.time()
    logger.info(f"■ job_id: {job_id} ({t1 - t0:.1f} s)")

    return ctx.outputs


def run_pipeline_netascore(
        target_srid: int,
        bbox_str: str,

        output_format: str = "GeoJSON",
        job_dir: Optional[Path] = None,
        progress_callback=None
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

    ctx = PipelineNetascoreContext(
        job_id=job_id,
        job_dir=job_dir,
        output_format=output_format,

        target_srid=target_srid,
        bbox_str=bbox_str,
    )

    steps = [
        SaveParametersStep(),
        GenerateNetascoreStep(),
        ExportResultsNetascoreStep()
    ]
    for i, step in enumerate(steps, 1):
        if progress_callback:
            progress_callback(f"{i}/{len(steps)}")
        step(ctx, idx=i, total=len(steps))

    t1 = time.time()
    logger.info(f"■ job_id: {job_id} ({t1 - t0:.1f} s)")

    return ctx.outputs
