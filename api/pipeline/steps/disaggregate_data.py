import random
from typing import Dict, Optional

import geopandas as gpd
import pandas as pd
from geopandas import GeoDataFrame
from shapely.geometry import Polygon, MultiPolygon, Point, LineString


def random_points_in_polygon(geom: Polygon, count: int, seed: Optional[int] = None) -> list[Point]:
    rng = random.Random(seed) if seed is not None else random
    points = []
    minx, miny, maxx, maxy = geom.bounds
    while len(points) < count:
        x = rng.uniform(minx, maxx)
        y = rng.uniform(miny, maxy)
        point = Point(x, y)
        if geom.contains(point):
            points.append(point)
    return points


def distribute_points_in_raster(
        polygon_gdf: GeoDataFrame,
        id_field: str,
        count_field: str,
        seed: Optional[int] = None,
) -> gpd.GeoDataFrame:
    # clean geometries
    polygon_gdf = polygon_gdf[polygon_gdf.geometry.notna() & ~polygon_gdf.geometry.is_empty]
    polygon_gdf = polygon_gdf[polygon_gdf.is_valid]

    output_records = []
    point_id = 1

    for _, cell in polygon_gdf.iterrows():
        count = cell.get(count_field)
        if count is None or pd.isna(count) or count <= 0:
            continue
        cell_count = int(count)
        cell_geom = cell.geometry

        # distribute points in single polygons
        if isinstance(cell_geom, Polygon):
            points = random_points_in_polygon(cell_geom, cell_count, seed)
            for point in points:
                output_records.append({
                    "point_id": point_id,
                    "cluster_id": cell.get(id_field),
                    "geometry": point
                })
                point_id += 1

        # distribute points proportionally in multipolygons
        elif isinstance(cell_geom, MultiPolygon):
            parts = [part for part in cell_geom.geoms if part.is_valid and part.area > 0]
            areas = [part.area for part in parts]
            total_area = sum(areas)

            if total_area == 0:
                continue

            # distribute people per part
            distribution = [cell_count * (area / total_area) for area in areas]
            parts_count = [int(round(x)) for x in distribution]

            # adjust rounding drift
            diff = cell_count - sum(parts_count)
            if diff != 0 and len(parts_count) > 0:
                for i in range(abs(diff)):
                    idx = i % len(parts_count)
                    parts_count[idx] += 1 if diff > 0 else -1

            for part_geom, part_count in zip(parts, parts_count):
                if part_count > 0:
                    points = random_points_in_polygon(part_geom, part_count, seed)
                    for point in points:
                        output_records.append({
                            "point_id": point_id,
                            "cluster_id": cell.get(id_field),
                            "geometry": point
                        })
                        point_id += 1

    points_gdf = gpd.GeoDataFrame(output_records, crs=polygon_gdf.crs)

    return points_gdf


def disaggregate_table_to_edges(
        od_points_a_gdf: gpd.GeoDataFrame,
        od_points_b_gdf: gpd.GeoDataFrame,
        od_table_df: pd.DataFrame,
        od_table_a_id_field: str,
        od_table_b_id_field: str,
        od_table_trips_field: str,
        seed: Optional[int] = None,
) -> gpd.GeoDataFrame:
    rng = random.Random(seed) if seed is not None else random

    # build cluster pools and shuffle
    pools_a: Dict = (od_points_a_gdf.groupby("cluster_id")["point_id"].apply(list).to_dict())  # {1: [101, 102], 2: [201]}
    pools_b: Dict = (od_points_b_gdf.groupby("cluster_id")["point_id"].apply(list).to_dict())

    for pool in pools_a.values():
        rng.shuffle(pool)  # {1: [102, 101], 2: [201]}
    for pool in pools_b.values():
        rng.shuffle(pool)

    # randomize table rows to avoid starving later pairs
    table_rows = list(od_table_df.itertuples(index=False))
    rng.shuffle(table_rows)

    edges = []

    for row in table_rows:
        cluster_a_id = getattr(row, od_table_a_id_field)
        cluster_b_id = getattr(row, od_table_b_id_field)
        trips_value = getattr(row, od_table_trips_field)
        trips = int(trips_value) if pd.notnull(trips_value) else 0
        if trips <= 0:
            continue

        pool_a = pools_a.get(cluster_a_id, [])  # [102, 101]
        pool_b = pools_b.get(cluster_b_id, [])
        if not pool_a or not pool_b:
            continue

        # cap by remaining availability in both pools
        k = min(trips, len(pool_a), len(pool_b))
        if k < trips:
            print(f"reducing trips {trips}->{k} for {cluster_a_id}->{cluster_b_id} due to remaining availability")
        if k == 0:
            continue

        # take k points from both pools
        points_a = [pool_a.pop() for _ in range(k)]
        points_b = [pool_b.pop() for _ in range(k)]

        # create edges
        edges.extend(
            {
                "point_a_id": point_a_id,
                "point_b_id": point_b_id,
                od_table_a_id_field: cluster_a_id,
                od_table_b_id_field: cluster_b_id,
            }
            for point_a_id, point_b_id in zip(points_a, points_b)
        )

    edges_df = pd.DataFrame(edges)
    if edges_df.empty:
        return gpd.GeoDataFrame(edges_df, geometry=[], crs=od_points_a_gdf.crs)

    # map geometries
    geom_a_map = od_points_a_gdf.set_index("point_id").geometry  # {101: POINT (10.0 20.0), 102: POINT (15.0 25.0)}
    geom_b_map = od_points_b_gdf.set_index("point_id").geometry
    geom_a = edges_df["point_a_id"].map(geom_a_map)
    geom_b = edges_df["point_b_id"].map(geom_b_map)

    # make lines
    def _make_line(pa: Point, pb: Point) -> LineString:
        return LineString([pa.coords[0], pb.coords[0]])

    line_geoms = [_make_line(pa, pb) if isinstance(pa, Point) and isinstance(pb, Point) else None for pa, pb in zip(geom_a, geom_b)]

    return gpd.GeoDataFrame(edges_df, geometry=line_geoms, crs=od_points_a_gdf.crs)
