import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.ops import linemerge

def compute_path_geometry(G, path):
    lines = []
    for u, v in zip(path[:-1], path[1:]):
        if G.has_edge(u, v):
            lines.append(G[u][v]['geometry'])
    if lines:
        return linemerge(lines) if len(lines) > 1 else lines[0]
    return None


def compute_path_index_average(G, path, index_ft='index_bike_ft', index_tf='index_bike_tf'):
    index_sum = 0
    length_sum = 0
    for u, v in zip(path[:-1], path[1:]):
        if G.has_edge(u, v):
            d = G[u][v]
            length = d.get('length', 0)
            index_value = d.get(index_ft)
        elif G.has_edge(v, u):
            d = G[v][u]
            length = d.get('length', 0)
            index_value = d.get(index_tf)
        else:
            print("warning: no edge between {} and {}".format(u, v))
            continue

        if index_value is not None:
            index_sum += index_value * length
            length_sum += length

    return round(index_sum / length_sum, 2) if length_sum > 0 else None


def compute_edges_index_average(G, reachable_edges, index_ft='index_bike_ft', index_tf='index_bike_tf'):
    index_sum = 0
    length_sum = 0
    for u, v, d in G.edges(data=True):
        if d.get('osm_id') in reachable_edges:
            length = d.get('length', 0)
            if length <= 0:
                continue

            index_ft = d.get(index_ft)
            index_tf = d.get(index_tf)

            index_values = [i for i in [index_ft, index_tf] if i is not None]
            if index_values:
                mean_index = sum(index_values) / len(index_values)
                index_sum += mean_index * length
                length_sum += length

    return round(index_sum / length_sum, 2) if length_sum > 0 else None


def evaluate_stops(edges_gdf, stops_gdf, households_gdf, G_base, G_quality, G_base_reversed, G_quality_reversed, generate_graphs=True, generate_routes=True):
    households = []
    stops = []
    routes_base = []
    routes_quality = []
    edges_base = []
    edges_quality = []

    for _, stop in stops_gdf.iterrows():
        stop_node_base = stop['node_id_base']
        stop_node_quality = stop['node_id_quality']

        lengths_base, paths_base = nx.single_source_dijkstra(G_base_reversed, stop_node_base, cutoff=3250, weight='length')
        lengths_quality, paths_quality = nx.single_source_dijkstra(G_quality_reversed, stop_node_quality, cutoff=3250, weight='length')

        households_in_proximity = households_gdf[households_gdf['node_id'].isin(lengths_base.keys())].copy()

        households_quality = 0
        base_routes = []
        quality_routes = []

        for _, household in households_in_proximity.iterrows():
            household_node = household['node_id']

            if household_node == stop_node_base:
                households.append({
                    'household_id': household['point_id'],
                    'stop_id': stop['stopnummer'],
                    'from_node': household_node,
                    'to_node': stop_node_base,
                    'length_base': 0,
                    'length_quality': 0,
                    'length_ratio': 1,
                    'index_base': None,
                    'index_quality': None,
                    'access': True,
                    'geometry': household['geometry'],
                })
                households_quality += 1
                continue

            length_base = lengths_base.get(household_node)
            length_quality = lengths_quality.get(household_node)

            path_index_average_base = None
            path_index_average_quality = None

            if generate_routes:
                path_base = paths_base.get(household_node)
                path_quality = paths_quality.get(household_node)

                if path_base:
                    path_base = list(reversed(path_base))
                    path_geom_base = compute_path_geometry(G_base, path_base)
                    path_index_average_base = compute_path_index_average(G_base, path_base)
                    if path_geom_base:
                        base_routes.append({
                            'household_id': household['point_id'],
                            'stop_id': stop['stopnummer'],
                            'from_node': household_node,
                            'to_node': stop_node_base,
                            'length': round(length_base, 2) if length_base else None,
                            'index_average': path_index_average_base,
                            'geometry': path_geom_base,
                        })

                if path_quality:
                    path_quality = list(reversed(path_quality))
                    path_geom_quality = compute_path_geometry(G_quality, path_quality)
                    path_index_average_quality  = compute_path_index_average(G_quality, path_quality)
                    if path_geom_quality:
                        quality_routes.append({
                            'household_id': household['point_id'],
                            'stop_id': stop['stopnummer'],
                            'from_node': household_node,
                            'to_node': stop_node_base,
                            'length': round(length_quality, 2) if length_quality else None,
                            'index_average': path_index_average_quality,
                            'geometry': path_geom_quality,
                        })

            access = False
            edges_length_ratio = None
            if length_base and length_quality:
                edges_length_ratio = round(length_quality / length_base, 2)
                if edges_length_ratio <= 1.5:
                    access = True
                    households_quality += 1

            households.append({
                'household_id': household['point_id'],
                'stop_id': stop['stopnummer'],
                'from_node': household_node,
                'to_node': stop_node_base,
                'length_base': round(length_base, 2) if length_base else None,
                'length_quality': round(length_quality, 2) if length_quality else None,
                'length_ratio': edges_length_ratio,
                'index_base': path_index_average_base,
                'index_quality': path_index_average_quality,
                'access': access,
                'geometry': household['geometry'],
            })

        if generate_routes:
            routes_base.extend(base_routes)
            routes_quality.extend(quality_routes)

        reachable_edges_base = {d['osm_id'] for u, v, d in G_base.edges(data=True) if u in lengths_base and v in lengths_base}
        reachable_edges_quality = {d['osm_id'] for u, v, d in G_quality.edges(data=True) if u in lengths_quality and v in lengths_quality}

        if generate_graphs:
            edges_base.append(pd.DataFrame({'stop_id': stop['stopnummer'], 'osm_id': list(reachable_edges_base)}))
            edges_quality.append(pd.DataFrame({'stop_id': stop['stopnummer'], 'osm_id': list(reachable_edges_quality)}))

        edges_length_base = sum(d['length'] for _, _, d in G_base.edges(data=True) if d.get('osm_id') in reachable_edges_base)
        edges_length_quality = sum(d['length'] for _, _, d in G_quality.edges(data=True) if d.get('osm_id') in reachable_edges_quality)
        edges_length_ratio = edges_length_quality / edges_length_base if edges_length_base > 0 else 0

        edges_index_average_base = compute_edges_index_average(G_base, reachable_edges_base)
        edges_index_average_quality = compute_edges_index_average(G_quality, reachable_edges_quality)

        households_base = len(households_in_proximity)
        households_ratio = households_quality / households_base if households_base > 0 else 0

        stops.append({
            'stop_id': stop['stopnummer'],
            'node_id': stop_node_base,
            'length_base': round(edges_length_base, 2),
            'length_quality': round(edges_length_quality, 2),
            'length_ratio': round(edges_length_ratio, 2),
            'households_base': households_base,
            'households_quality': households_quality,
            'households_ratio': round(households_ratio, 2),
            'index_average_base': edges_index_average_base,
            'index_average_quality': edges_index_average_quality,
            'geometry': stop['geometry'],
        })

    if generate_graphs:
        edges_base = edges_gdf.merge(pd.concat(edges_base).drop_duplicates(), on='osm_id')
        edges_quality = edges_gdf.merge(pd.concat(edges_quality).drop_duplicates(), on='osm_id')

    if generate_routes:
        routes_base = gpd.GeoDataFrame(routes_base, geometry='geometry', crs=edges_gdf.crs)
        routes_quality = gpd.GeoDataFrame(routes_quality, geometry='geometry', crs=edges_gdf.crs)

    stops = gpd.GeoDataFrame(stops, geometry='geometry', crs=edges_gdf.crs)
    households = gpd.GeoDataFrame(households, geometry='geometry', crs=edges_gdf.crs)

    return edges_base, edges_quality, routes_base, routes_quality, stops, households
