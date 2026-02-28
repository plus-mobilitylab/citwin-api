import geopandas as gpd
import networkx as nx
from shapely.geometry import LineString


def build_graph(edges_gdf: gpd.GeoDataFrame, nodes_gdf: gpd.GeoDataFrame) -> nx.DiGraph:
    G = nx.DiGraph()
    node_ids = set()

    for _, row in edges_gdf.iterrows():
        u = row['from_node']
        v = row['to_node']
        geom = row.geometry
        attrs = row.drop(labels=['geometry']).to_dict()

        if row.get('access_bicycle_ft', False):
            G.add_edge(u, v, geometry=geom, **attrs)
            node_ids.update([u, v])

        if row.get('access_bicycle_tf', False):
            rev_geom = LineString(geom.coords[::-1])
            G.add_edge(v, u, geometry=rev_geom, **attrs)
            node_ids.update([u, v])

    for _, row in nodes_gdf.iterrows():
        node_id = row['node_id']
        if node_id in node_ids:
            G.add_node(node_id, x=row.geometry.x, y=row.geometry.y)

    return G


def build_graph_quality(edges_gdf: gpd.GeoDataFrame, nodes_gdf: gpd.GeoDataFrame, index_threshold: float) -> nx.DiGraph:
    G = nx.DiGraph()
    node_ids = set()

    for _, row in edges_gdf.iterrows():
        u = row['from_node']
        v = row['to_node']
        geom = row.geometry
        attrs = row.drop(labels=['geometry']).to_dict()

        if row.get('access_bicycle_ft', False) and row['index_bike_ft'] >= index_threshold:
            G.add_edge(u, v, geometry=geom, **attrs)
            node_ids.update([u, v])

        if row.get('access_bicycle_tf', False) and row['index_bike_tf'] >= index_threshold:
            rev_geom = LineString(geom.coords[::-1])
            G.add_edge(v, u, geometry=rev_geom, **attrs)
            node_ids.update([u, v])

    for _, row in nodes_gdf.iterrows():
        node_id = row['node_id']
        if node_id in node_ids:
            G.add_node(node_id, x=row.geometry.x, y=row.geometry.y)

    return G
