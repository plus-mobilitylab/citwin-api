import geopandas as gpd
import networkx as nx
import pandas as pd


def add_network_distance(od_edges_gdf, od_points_a_gdf, od_points_b_gdf, G_base) -> gpd.GeoDataFrame:
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

    od_edges_gdf['distance'] = [get_network_distance(row) for row in od_edges_gdf.itertuples(index=False)]

    return od_edges_gdf
