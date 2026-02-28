import pickle
from pathlib import Path
from typing import Optional, Tuple

import geopandas as gpd
import networkx as nx
from geopandas import GeoDataFrame
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


def load_cached_graphs(cache_dir: Path, *graph_names) -> Optional[Tuple]:
    cache_files = {name: cache_dir / f"{name}.pkl" for name in graph_names}

    if all(file.exists() for file in cache_files.values()):
        return tuple(pickle.load(open(file, "rb")) for file in cache_files.values())

    return None


def save_cached_graphs(cache_dir: Path, **graphs) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)

    for name, graph in graphs.items():
        file_path = cache_dir / f"{name}.pkl"
        with open(file_path, "wb") as f:
            pickle.dump(graph, f)  # type: ignore[arg-type]


def build_graphs(
        graph_edges_gdf: GeoDataFrame,
        graph_nodes_gdf: GeoDataFrame,
        cache_dir: Optional[Path] = None
) -> Tuple:
    if cache_dir:
        print("  loading graphs from cache")
        cached_graphs = load_cached_graphs(cache_dir, "G_base", "G_base_reversed", "G_quality", "G_quality_reversed")
        if cached_graphs:
            return cached_graphs

    graph_nodes_gdf = graph_nodes_gdf.reset_index().rename(columns={'index': 'node_id'})
    graph_nodes_gdf['node_id'] = graph_nodes_gdf['node_id'] + 1

    print("  building base graph")
    G_base = build_graph(graph_edges_gdf, graph_nodes_gdf)
    G_base_reversed = G_base.reverse(copy=True)

    print("  building quality graph")
    G_quality = build_graph_quality(graph_edges_gdf, graph_nodes_gdf, 0.5)
    G_quality_reversed = G_quality.reverse(copy=True)

    if cache_dir:
        print("  saving graphs to cache")
        save_cached_graphs(cache_dir, G_base=G_base, G_base_reversed=G_base_reversed, G_quality=G_quality, G_quality_reversed=G_quality_reversed)

    return G_base, G_base_reversed, G_quality, G_quality_reversed
