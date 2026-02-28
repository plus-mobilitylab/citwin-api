from typing import Optional

import geopandas as gpd
import networkx as nx


def build_graph(
        edges_gdf: gpd.GeoDataFrame,
        nodes_gdf: gpd.GeoDataFrame,
        from_node_field: str = "from_node",
        to_node_field: str = "to_node",
        node_id_field: str = "node_id"
) -> nx.DiGraph:
    G = nx.DiGraph()

    # add edges
    for _, row in edges_gdf.iterrows():
        u = row[from_node_field]
        v = row[to_node_field]
        geom = row.geometry

        attrs_ft = {
            "edge_id": row.get("edge_id"),
            "length": row.get("length"),
            "access_bicycle": row.get("access_bicycle_ft"),
            "access_pedestrian": row.get("access_pedestrian_ft"),
            "index_bike": row.get("index_bike_ft"),
            "index_walk": row.get("index_walk_ft"),
        }

        attrs_tf = {
            "edge_id": row.get("edge_id"),
            "length": row.get("length"),
            "access_bicycle": row.get("access_bicycle_tf"),
            "access_pedestrian": row.get("access_pedestrian_tf"),
            "index_bike": row.get("index_bike_tf"),
            "index_walk": row.get("index_walk_tf"),
        }

        # forward edge: u -> v
        G.add_edge(u, v, geometry=geom, **attrs_ft)

        # backward edge: v -> u
        G.add_edge(v, u, geometry=geom.reverse() , **attrs_tf)

    # add nodes
    for _, row in nodes_gdf.iterrows():
        node_id = row[node_id_field]
        G.add_node(node_id, x=row.geometry.x, y=row.geometry.y)

    return G


def make_subgraph(
        G: nx.DiGraph,
        mode: str,
        index_threshold: Optional[float] = None,
        length_minimum: Optional[float] = None,
        walk_segments_for_bike: Optional[bool] = False,
) -> nx.DiGraph:
    access_field = {"bike": "access_bicycle", "walk": "access_pedestrian"}[mode]
    index_field = {"bike": "index_bike", "walk": "index_walk"}[mode]

    keep_edges = []

    for u, v, d in G.edges(data=True):
        # allow walk segments in bike mode
        if mode == "bike" and walk_segments_for_bike and not d.get("access_bicycle", False) and d.get("access_pedestrian", False):
            keep_edges.append((u, v))
            continue

        # no access in direction
        if not d.get(access_field, False):
            continue

        # no index threshold -> base graph
        if index_threshold is None:
            keep_edges.append((u, v))
            continue

        # index threshold / length minimum -> quality graph
        index = d.get(index_field)
        length = d.get("length")

        ok_index = index is not None and index >= index_threshold
        ok_length = length_minimum is not None and length is not None and length <= length_minimum

        if ok_index or ok_length:
            keep_edges.append((u, v))

    return G.edge_subgraph(keep_edges).copy()


def keep_largest_component(G: nx.DiGraph) -> nx.DiGraph:
    largest_component = max(nx.weakly_connected_components(G), key=len)
    return G.subgraph(largest_component).copy()


def remove_small_components(G: nx.DiGraph, min_size: int = 10) -> nx.DiGraph:
    if min_size < 1:
        return G.copy()

    keep_nodes = set()
    for component in nx.weakly_connected_components(G):
        if len(component) >= min_size:
            keep_nodes.update(component)

    return G.subgraph(keep_nodes).copy()


def graph_to_gdf(G: nx.DiGraph, crs=None) -> gpd.GeoDataFrame:
    records = []
    for u, v, d in G.edges(data=True):
        geom = d.get("geometry")
        if geom:
            record = dict(d)  # copy all edge attributes
            record["from_node"] = u
            record["to_node"] = v
            record["geometry"] = geom
            records.append(record)

    return gpd.GeoDataFrame(records, geometry="geometry", crs=crs)
