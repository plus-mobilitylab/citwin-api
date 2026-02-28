import geopandas as gpd
import networkx as nx
import pandas as pd
from tqdm import tqdm


def compute_network_distances(od_edges_gdf, od_points_a_gdf, od_points_b_gdf, G_base) -> gpd.GeoDataFrame:
    # map point_id -> node_id for origin and destination points
    points_a = od_points_a_gdf.set_index('point_id')['node_id'].to_dict()
    points_b = od_points_b_gdf.set_index('point_id')['node_id'].to_dict()

    def get_network_distance(row):
        node_a_id = points_a.get(row.point_a_id)
        node_b_id = points_b.get(row.point_b_id)
        if pd.notnull(node_a_id) and pd.notnull(node_b_id):
            try:
                return round(nx.shortest_path_length(G_base, source=node_a_id, target=node_b_id, weight='length'), 2)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                return None
        return None

    od_edges_gdf['distance'] = [get_network_distance(row) for row in tqdm(od_edges_gdf.itertuples(index=False), total=len(od_edges_gdf))]

    return od_edges_gdf


def compute_network_distances_with_cutoff(
    od_edges_gdf: gpd.GeoDataFrame,
    od_points_a_gdf: gpd.GeoDataFrame,
    od_points_b_gdf: gpd.GeoDataFrame,
    G_base: nx.DiGraph,
    distance_threshold_m: float,
) -> gpd.GeoDataFrame:
    # map point_id to corresponding node_id using precomputed lookup dict
    point_a_to_node = od_points_a_gdf.set_index("point_id")["node_id"].to_dict()
    point_b_to_node = od_points_b_gdf.set_index("point_id")["node_id"].to_dict()

    edges = od_edges_gdf.copy()

    edges["node_a_id"] = edges["point_a_id"].map(point_a_to_node)
    edges["node_b_id"] = edges["point_b_id"].map(point_b_to_node)

    # precompute distances: (node_a, node_b) -> distance
    distance_map = {}
    unique_nodes_a = edges["node_a_id"].dropna().unique()
    for node_a in tqdm(unique_nodes_a):
        lengths = nx.single_source_dijkstra_path_length(G_base, node_a, cutoff=distance_threshold_m, weight="length")

        for node_b, distance in lengths.items():
            distance_map[(node_a, node_b)] = round(distance, 2)

    # look up (or derive) distance for each OD edge
    def lookup_distance(row):
        d = distance_map.get((row.node_a_id, row.node_b_id))
        # no distance < threshold is found
        if d is None:
            return distance_threshold_m + 1
        return d

    edges["distance"] = [lookup_distance(row) for row in edges.itertuples(index=False)]

    edges = edges.drop(columns=["node_a_id", "node_b_id"])

    return edges
