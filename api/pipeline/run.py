import shutil
import uuid
from pathlib import Path
from typing import Optional, Dict

import geopandas as gpd
import pandas as pd

from api.paths import BASE_JOBS_DIR, NETASCORE_DIR, NETASCORE_SETTINGS_TEMPLATE
from api.pipeline.steps.build_graphs import build_graphs
from api.pipeline.steps.disaggregate_data import distribute_points_in_raster, disaggregate_table_to_edges
from api.pipeline.steps.evaluate_stops import evaluate_stops
from api.pipeline.steps.filter_network import add_network_distance
from api.pipeline.steps.handle_data import ensure_wgs84, compute_bbox_str, get_utm_srid
from api.pipeline.steps.netascore import update_settings, run_netascore
from api.pipeline.steps.snap_points import build_balltree, snap_with_balltree


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

        netascore_gpkg: Optional[Path] = None,
        output_format: Optional[str] = "GeoJSON",
        seed: Optional[int] = None,

        job_dir: Optional[Path] = None,
) -> Dict[str, Path]:
    if job_dir is None:
        job_id = str(uuid.uuid4())
        job_dir = (BASE_JOBS_DIR / job_id)
    else:
        job_id = job_dir.name
    print("job_id:", job_id)
    job_dir.mkdir(parents=True, exist_ok=True)

    if output_format not in {"GPKG", "GeoJSON"}:
        raise ValueError(f"Unsupported output format: {output_format}. Choose 'GPKG' or 'GeoJSON'.")

    # ==================================================================================================================
    # import data
    # ==================================================================================================================

    print("import data")
    od_clusters_a_gdf = ensure_wgs84(gpd.read_file(od_clusters_a))
    od_clusters_b_gdf = ensure_wgs84(gpd.read_file(od_clusters_b))
    od_table_df = pd.read_csv(od_table, delimiter=';')
    stops_gdf = ensure_wgs84(gpd.read_file(stops))

    target_srid = get_utm_srid(stops_gdf)
    print("  target_srid:", target_srid)
    stops_buffer_gdf = stops_gdf.to_crs(epsg=target_srid).geometry.buffer(7500).to_crs(epsg=4326)
    bbox_str = compute_bbox_str(stops_buffer_gdf)
    print("  bbox_str:", bbox_str)

    # ==================================================================================================================
    # filter data
    # ==================================================================================================================

    print("filter data")
    print("  filter clusters by stops buffer")
    mask_a = od_clusters_a_gdf.geometry.intersects(stops_buffer_gdf.union_all())
    od_clusters_a_gdf = od_clusters_a_gdf[mask_a]
    mask_b = od_clusters_b_gdf.geometry.intersects(stops_buffer_gdf.union_all())
    od_clusters_b_gdf = od_clusters_b_gdf[mask_b]

    # ==================================================================================================================
    # disaggregate data
    # ==================================================================================================================

    print("disaggregate data")
    print("  distribute points in clusters")
    od_points_a_gdf = distribute_points_in_raster(od_clusters_a_gdf, od_clusters_a_id_field, od_clusters_a_count_field, seed)
    od_points_b_gdf = distribute_points_in_raster(od_clusters_b_gdf, od_clusters_b_id_field, od_clusters_b_count_field, seed)
    print("  disaggregate table to edges")
    od_edges_gdf = disaggregate_table_to_edges(od_points_a_gdf, od_points_b_gdf, od_table_df, od_table_a_id_field, od_table_b_id_field, od_table_trips_field, seed)

    # ==================================================================================================================
    # netascore
    # ==================================================================================================================

    generated_netascore = False

    if netascore_gpkg is None:
        print("netascore")
        print("  update settings")
        netascore_data_dir = NETASCORE_DIR / "data"
        netascore_data_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy(NETASCORE_DIR / "examples" / "profile_bike.yml", netascore_data_dir / "profile_bike.yml")
        shutil.copy(NETASCORE_DIR / "examples" / "profile_walk.yml", netascore_data_dir / "profile_walk.yml")

        case_id = "default_case"
        netascore_settings = netascore_data_dir / "settings.yml"
        update_settings(NETASCORE_SETTINGS_TEMPLATE, netascore_settings, target_srid, bbox_str, case_id)

        print("  run netascore")
        run_netascore(NETASCORE_DIR, netascore_settings)
        netascore_gpkg_tmp = netascore_data_dir / f"netascore_{case_id}.gpkg"
        netascore_gpkg = job_dir / "netascore.gpkg"
        shutil.copy(netascore_gpkg_tmp, netascore_gpkg)
        shutil.rmtree(netascore_data_dir, ignore_errors=True)

        generated_netascore = True

    netascore_edges_gdf = ensure_wgs84(gpd.read_file(netascore_gpkg, layer="edge"))
    netascore_nodes_gdf = ensure_wgs84(gpd.read_file(netascore_gpkg, layer="node"))

    # ==================================================================================================================
    # build graphs
    # ==================================================================================================================

    print("build graphs")
    # cache_dir = Path(__file__).resolve().parents[1] / "jobs" / "cache"
    G_base, G_base_reversed, G_quality, G_quality_reversed = build_graphs(netascore_edges_gdf, netascore_nodes_gdf)

    # ==================================================================================================================
    # snap points
    # ==================================================================================================================

    print("snap points")
    print("  building balltree on graph nodes")
    balltree_base, node_ids_base = build_balltree(G_base)
    balltree_quality, node_ids_quality = build_balltree(G_quality)

    print("  snapping points to graph nodes")
    od_points_a_gdf = snap_with_balltree(od_points_a_gdf, balltree_base, node_ids_base)
    od_points_b_gdf = snap_with_balltree(od_points_b_gdf, balltree_base, node_ids_base)
    stops_gdf = snap_with_balltree(stops_gdf, balltree_base, node_ids_base, node_id_field="node_id_base")
    stops_gdf = snap_with_balltree(stops_gdf, balltree_quality, node_ids_quality, node_id_field="node_id_quality")

    # ==================================================================================================================
    # filter network
    # ==================================================================================================================

    print("filter network")
    print("  add network distance")
    od_edges_gdf = add_network_distance(od_edges_gdf, od_points_a_gdf, od_points_b_gdf, G_base)

    print("  remove edges and points with distance <= 3250 m")
    od_edges_gdf = od_edges_gdf[od_edges_gdf['distance'] > 3250]

    valid_a_ids = od_edges_gdf['point_a_id'].unique()
    valid_b_ids = od_edges_gdf['point_b_id'].unique()

    od_points_a_gdf = od_points_a_gdf[od_points_a_gdf['point_id'].isin(valid_a_ids)]
    od_points_b_gdf = od_points_b_gdf[od_points_b_gdf['point_id'].isin(valid_b_ids)]

    # ==================================================================================================================
    # evaluate stops
    # ==================================================================================================================

    print("evaluate stops")
    edges_base_gdf, edges_quality_gdf, routes_base_gdf, routes_quality_gdf, stops_gdf, households_gdf = evaluate_stops(netascore_edges_gdf, stops_gdf, od_points_a_gdf, G_base, G_quality, G_base_reversed, G_quality_reversed)

    # ==================================================================================================================
    # export data
    # ==================================================================================================================

    file_extension = "gpkg" if output_format == "GPKG" else "geojson"
    driver = "GPKG" if output_format == "GPKG" else "GeoJSON"

    print("export data")
    od_points_a = job_dir / f"od_points_a.{file_extension}"
    od_points_b = job_dir / f"od_points_b.{file_extension}"
    od_edges = job_dir / f"od_edges.{file_extension}"
    edges_base = job_dir / f"edges_base.{file_extension}"
    edges_quality = job_dir / f"edges_quality.{file_extension}"
    routes_base = job_dir / f"routes_base.{file_extension}"
    routes_quality = job_dir / f"routes_quality.{file_extension}"
    stops_updated = job_dir / f"stops_updated.{file_extension}"
    households = job_dir / f"households.{file_extension}"

    od_points_a_gdf.to_file(od_points_a, driver=driver)
    od_points_b_gdf.to_file(od_points_b, driver=driver)
    od_edges_gdf.to_file(od_edges, driver=driver)
    edges_base_gdf.to_file(edges_base, driver=driver)
    edges_quality_gdf.to_file(edges_quality, driver=driver)
    routes_base_gdf.to_file(routes_base, driver=driver)
    routes_quality_gdf.to_file(routes_quality, driver=driver)
    stops_gdf.to_file(stops_updated, driver=driver)
    households_gdf.to_file(households, driver=driver)

    outputs = {
        "stops_updated": stops_updated,
        "households": households
    }

    if generated_netascore:
        outputs["netascore_gpkg"] = netascore_gpkg

    print("done")

    return outputs


def main():
    run_pipeline(
        od_clusters_a=Path("../../data/b_klynger.gpkg"),
        od_clusters_b=Path("../../data/a_klynger.gpkg"),
        od_table=Path("../../data/Data_2023_0099_Tabel_1.csv"),
        stops=Path("../../data/dynlayer.gpkg"),
        od_clusters_a_id_field="klynge_id",
        od_clusters_a_count_field="Beboere",
        od_clusters_b_id_field="klynge_id",
        od_clusters_b_count_field="Arbejdere",
        od_table_a_id_field="Bopael_klynge_id",
        od_table_b_id_field="Arbejssted_klynge_id",
        od_table_trips_field="Antal",
        # netascore_gpkg=Path("../../data/netascore_20250908_181654.gpkg"),
        output_format="GPKG",
        seed=None,
    )


if __name__ == "__main__":
    main()
