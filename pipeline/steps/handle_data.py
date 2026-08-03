import pandas as pd
import geopandas as gpd

def generate_perception_score(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({"osmid": df["osmid"]})
    for x in ["Safe", "Lively", "Beautiful", "Wealthy", "Boring", "Depressing"]:
        out[x.lower() + "_score"] = df[x] / 10
    out["perception_score"] = out[["beauty_score", "liveliness_score"]].max(axis=1)
    out = out.sort_values("perception_score", ascending = False).drop_duplicates(["osmid"]).reset_index(drop = True)
    # TODO: Do not just select maximum score per OSM way, but use metadata such as image quality or direction.
    return out

def calculate_distance(speed_kmh, time_min) -> int:
    time_h = time_min / 60
    distance_m = speed_kmh * time_h * 1000
    return int(round(distance_m))


def ensure_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        return gdf.set_crs(4326)  # type: ignore[return-value]
    if gdf.crs.to_epsg() != 4326:
        return gdf.to_crs(4326)
    return gdf


def get_utm_srid(gdf: gpd.GeoDataFrame) -> int:
    minx, miny, maxx, maxy = gdf.total_bounds
    center_lon = (minx + maxx) / 2
    center_lat = (miny + maxy) / 2
    zone = int((center_lon + 180) / 6) + 1
    return 32600 + zone if center_lat >= 0 else 32700 + zone


def compute_bbox_str(gdf: gpd.GeoDataFrame) -> str:
    minx, miny, maxx, maxy = gdf.total_bounds
    return f"{miny:.4f},{minx:.4f},{maxy:.4f},{maxx:.4f}"


def filter_gdf(gdf: gpd.GeoDataFrame, buffer_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    mask = gdf.geometry.intersects(buffer_gdf.union_all())
    return gdf[mask]
