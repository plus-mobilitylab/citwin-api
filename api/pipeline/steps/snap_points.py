import networkx as nx
import numpy as np
from geopandas import GeoDataFrame
from sklearn.neighbors import BallTree


def build_balltree(G: nx.DiGraph) -> tuple[BallTree, list]:
    node_coords = np.array([(data['x'], data['y']) for n, data in G.nodes(data=True)])
    node_ids = [n for n, data in G.nodes(data=True)]
    return BallTree(node_coords), node_ids


def snap_with_balltree(gdf: GeoDataFrame, balltree: BallTree, node_ids: list, node_id_field: str = "node_id") -> GeoDataFrame:
    points_array = np.array([[geom.x, geom.y] for geom in gdf.geometry])
    _, indices = balltree.query(points_array, k=1)
    gdf[node_id_field] = [node_ids[i[0]] for i in indices]
    return gdf
