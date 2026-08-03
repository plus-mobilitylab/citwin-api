import logging
import math

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely import MultiLineString
from shapely.ops import linemerge
from tqdm import tqdm

logger = logging.getLogger(__name__)


def get_path_geometry_linestring(G, path):
    lines = []
    for u, v in zip(path[:-1], path[1:]):
        if G.has_edge(u, v):
            lines.append(G[u][v]["geometry"])
    if lines:
        return linemerge(lines) if len(lines) > 1 else lines[0]

    return None


def get_path_geometry_multilinestring(G, path):
    lines = [G[u][v]["geometry"] for u, v in zip(path[:-1], path[1:])]

    return MultiLineString(lines)


def compute_path_index_average(G, path, index_field):
    index_sum = 0.0
    length_sum = 0.0

    for u, v in zip(path[:-1], path[1:]):
        if not G.has_edge(u, v):
            logger.warning(f"– no edge between {u} and {v}")
            continue

        d = G[u][v]

        length = d.get("length", 0.0)
        index = d.get(index_field)

        if index is not None and not math.isnan(index):
            index_sum += index * length
            length_sum += length

    return round(index_sum / length_sum, 2) if length_sum > 0 else None


def compute_edges_index_average(G, reachable_edges, index_field):
    index_sum = 0.0
    length_sum = 0.0

    for u, v, d in G.edges(data=True):
        if d.get("edge_id") not in reachable_edges:
            continue

        length = d.get("length", 0.0)
        index = d.get(index_field)

        if index is not None and not math.isnan(index):
            index_sum += index * length
            length_sum += length

    return round(index_sum / length_sum, 2) if length_sum > 0 else None


def evaluate_access(
        edges_gdf: gpd.GeoDataFrame,
        pois_gdf: gpd.GeoDataFrame,
        od_points_a_gdf: gpd.GeoDataFrame,
        pois_id_field: str,
        G_base: nx.DiGraph,
        G_quality: nx.DiGraph,
        mode: str,
        distance_threshold: float,
        detour_threshold: float,
        perception_threshold: float | None = None,
        compute_enhanced: bool = False,
        generate_routes: bool = False
):
    index_field = {"bike": "index_bike", "walk": "index_walk"}[mode]
    perception_field = "perception_score"
    
    residents = []
    pois = []
    edges_base = []
    edges_quality = []
    routes_base = []
    routes_quality = []

    G_base_rev = G_base.reverse(copy=True)
    G_quality_rev = G_quality.reverse(copy=True)

    for _, poi in tqdm(pois_gdf.iterrows(), total=len(pois_gdf)):
        poi_id = poi[pois_id_field]
        poi_node_id = poi["node_id"]
        poi_geom = poi["geometry"]

        lengths_base, paths_base = nx.single_source_dijkstra(G_base_rev, poi_node_id, cutoff=distance_threshold, weight="length")
        lengths_quality, paths_quality = nx.single_source_dijkstra(G_quality_rev, poi_node_id, cutoff=distance_threshold, weight="length")

        residents_in_proximity = od_points_a_gdf[od_points_a_gdf["node_id"].isin(lengths_base.keys())].copy()

        residents_quality = 0
        residents_enhanced = 0
        
        routes_base_poi = []
        routes_quality_poi = []

        for _, resident in residents_in_proximity.iterrows():
            resident_point_id = resident["point_id"]
            resident_node_id = resident["node_id"]
            resident_geom = resident["geometry"]

            # resident is exactly at the poi node
            if resident_node_id == poi_node_id:
                residents.append({
                    "point_id": resident_point_id,
                    "poi_id": poi_id,
                    "from_node": resident_node_id,
                    "to_node": poi_node_id,
                    "length_base": 0.0,
                    "length_quality": 0.0,
                    "length_ratio": None,
                    "index_base": None,
                    "index_quality": None,
                    "access": True,
                    "geometry": resident_geom,
                })
                residents_quality += 1
                if compute_enhanced:
                    residents.append({
                        "perception": None,
                        "enhanced_access": True,
                    })
                    residents_enhanced += 1
                continue

            # reconstruct geometry and index of the used path
            length_base = lengths_base.get(resident_node_id)
            length_quality = lengths_quality.get(resident_node_id)

            path_index_average_base = None
            path_index_average_quality = None

            path_base = paths_base.get(resident_node_id)
            if path_base:
                path_base = list(reversed(path_base))  # reverse path because Dijkstra ran on reversed graph
                path_geom_base = None
                if generate_routes:
                    path_geom_base = get_path_geometry_multilinestring(G_base, path_base)
                path_index_average_base = compute_path_index_average(G_base, path_base, index_field)

                if generate_routes and path_geom_base is not None:
                    routes_base_poi.append({
                        "point_id": resident_point_id,
                        "poi_id": poi_id,
                        "from_node": resident_node_id,
                        "to_node": poi_node_id,
                        "length": round(length_base, 2) if length_base is not None else None,
                        "index_average": path_index_average_base,
                        "geometry": path_geom_base,
                    })

            path_quality = paths_quality.get(resident_node_id)
            if path_quality:
                path_quality = list(reversed(path_quality))  # reverse path because Dijkstra ran on reversed graph
                path_geom_quality = None
                if generate_routes:
                    path_geom_quality = get_path_geometry_multilinestring(G_quality, path_quality)
                path_index_average_quality = compute_path_index_average(G_quality, path_quality, index_field)

                if generate_routes and path_geom_quality is not None:
                    routes_quality_poi.append({
                        "point_id": resident_point_id,
                        "poi_id": poi_id,
                        "from_node": resident_node_id,
                        "to_node": poi_node_id,
                        "length": round(length_quality, 2) if length_quality is not None else None,
                        "index_average": path_index_average_quality,
                        "geometry": path_geom_quality,
                    })
                    
            # determine whether bikeable access is acceptable (detour threshold)
            access = False
            edges_length_ratio = None
            if length_base is not None and length_quality is not None:
                edges_length_ratio = round(length_quality / length_base, 2)
                if edges_length_ratio <= detour_threshold:
                    access = True
                    residents_quality += 1
            
            residents.append({
                "point_id": resident_point_id,
                "poi_id": poi_id,
                "from_node": resident_node_id,
                "to_node": poi_node_id,
                "length_base": round(length_base, 2) if length_base is not None else None,
                "length_quality": round(length_quality, 2) if length_quality is not None else None,
                "length_ratio": edges_length_ratio,
                "index_average_base": path_index_average_base,
                "index_average_quality": path_index_average_quality,
                "access": access,
                "geometry": resident_geom,
            })

            # determine enhanced access
            if compute_enhanced:
                if perception_threshold is None:
                    raise ValueError("Perception threshold cannot be None when computing enhanced accessibility")
                path_perception_average = None
                enhanced_access = False
                if access:
                    cutoff = min(length_base * detour_threshold, distance_threshold)
                    all_paths = nx.all_simple_paths(G_quality, resident_node_id, poi_node_id, cutoff = cutoff)
                    perception_averages = [compute_path_index_average(G_quality, x, perception_field) for x in all_paths]
                    path_perception_average = min((x for x in perception_averages if x is not None), default = None)
                    if path_perception_average is None:
                        enhanced_access = None
                    else if path_perception_average => perception_threshold:
                        enhanced_access = True
                        residents_enhanced += 1
                residents.append({
                    "perception_average": path_perception_average,
                    "enhanced_access": enhanced_access,
                })

        # collect routes for this poi
        if generate_routes:
            routes_base.extend(routes_base_poi)
            routes_quality.extend(routes_quality_poi)

        # subgraphs around this poi (reachable nodes)
        G_base_sub = G_base.subgraph(lengths_base.keys())
        G_quality_sub = G_quality.subgraph(lengths_quality.keys())

        edges_base_poi = {d["edge_id"] for _, _, d in G_base_sub.edges(data=True)}
        edges_quality_poi = {d["edge_id"] for _, _, d in G_quality_sub.edges(data=True)}

        edges_base.append(pd.DataFrame({"poi_id": poi_id, "edge_id": list(edges_base_poi)}))
        edges_quality.append(pd.DataFrame({"poi_id": poi_id, "edge_id": list(edges_quality_poi)}))

        # total reachable network length for index and ratio statistics
        edges_length_base = sum(d["length"] for _, _, d in G_base_sub.edges(data=True))
        edges_length_quality = sum(d["length"] for _, _, d in G_quality_sub.edges(data=True))
        edges_length_ratio = edges_length_quality / edges_length_base if edges_length_base > 0 else 0.0

        edges_index_average_base = compute_edges_index_average(G_base_sub, edges_base_poi, index_field)
        edges_index_average_quality = compute_edges_index_average(G_quality_sub, edges_quality_poi, index_field)

        residents_base = len(residents_in_proximity)
        residents_ratio = residents_quality / residents_base if residents_base > 0 else 0.0

        pois.append({
            "poi_id": poi_id,
            "node_id": poi_node_id,
            "length_base": round(edges_length_base, 2),
            "length_quality": round(edges_length_quality, 2),
            "length_ratio": round(edges_length_ratio, 2),
            "residents_base": residents_base,
            "residents_quality": residents_quality,
            "residents_ratio": round(residents_ratio, 2),
            "index_average_base": edges_index_average_base,
            "index_average_quality": edges_index_average_quality,
            "geometry": poi_geom,
        })

        if compute_enhanced:
            edges_perception_average = compute_edges_index_average(G_quality_sub, edges_quality_poi, perception_field)
            residents_enhanced_ratio = residents_enhanced / residents_quality if residents_quality > 0 else 0.0
            pois.append({
                "perception_average": edges_perception_average,
                "residents_enhanced": residents_enhanced,
                "residents_enhanced_ratio": residents_enhanced_ratio,
            })
    
    edges_base = edges_gdf.merge(pd.concat(edges_base).drop_duplicates(), on="edge_id")
    edges_quality = edges_gdf.merge(pd.concat(edges_quality).drop_duplicates(), on="edge_id")

    if generate_routes and routes_base:
        routes_base = gpd.GeoDataFrame(routes_base, geometry="geometry", crs=edges_gdf.crs)
    else:
        routes_base = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=edges_gdf.crs)

    if generate_routes and routes_quality:
        routes_quality = gpd.GeoDataFrame(routes_quality, geometry="geometry", crs=edges_gdf.crs)
    else:
        routes_quality = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=edges_gdf.crs)

    pois = gpd.GeoDataFrame(pois, geometry="geometry", crs=edges_gdf.crs)
    residents = gpd.GeoDataFrame(residents, geometry="geometry", crs=edges_gdf.crs)

    return edges_base, edges_quality, routes_base, routes_quality, pois, residents
