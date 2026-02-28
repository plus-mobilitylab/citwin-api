import geopandas as gpd
import networkx as nx
import numpy as np
from shapely.geometry import Point
from shapely.strtree import STRtree
from sklearn.neighbors import BallTree


def build_balltree(G: nx.DiGraph) -> tuple[BallTree, list]:
    node_coords = np.array([(data['x'], data['y']) for n, data in G.nodes(data=True)])
    node_ids = [n for n, data in G.nodes(data=True)]
    return BallTree(node_coords), node_ids


def snap_with_balltree(gdf: gpd.GeoDataFrame, balltree: BallTree, node_ids: list, node_id_field: str = "node_id") -> gpd.GeoDataFrame:
    points_array = np.array([[geom.x, geom.y] for geom in gdf.geometry])
    _, indices = balltree.query(points_array, k=1)
    gdf[node_id_field] = [node_ids[i[0]] for i in indices]
    return gdf


def build_strtree(G: nx.DiGraph) -> tuple[STRtree, dict]:
    geom_list = []
    edge_map = {}

    for u, v, data in G.edges(data=True):
        geom = data["geometry"]
        index = len(geom_list)
        edge_map[index] = (u, v)
        geom_list.append(geom)

    edge_index = STRtree(geom_list)

    return edge_index, edge_map


def snap_with_strtree(
    gdf: gpd.GeoDataFrame,
    G: nx.DiGraph,
    edge_index: STRtree,
    edge_map: dict,
    node_id_field: str = "node_id"
) -> gpd.GeoDataFrame:
    node_points = {n: Point(d["x"], d["y"]) for n, d in G.nodes(data=True)}
    snapped_ids = []

    for pt in gdf["geometry"]:
        nearest_index = edge_index.nearest(pt)
        u, v = edge_map[nearest_index]

        dist_u = pt.distance(node_points[u])
        dist_v = pt.distance(node_points[u])

        snapped_ids.append(u if dist_u < dist_v else v)

    gdf[node_id_field] = snapped_ids

    return gdf
