# User Guide (API Usage)

This guide explains how to call the CITWIN API, what each endpoint does, and what every request parameter means.

---

## Endpoint map

- `GET /health` – health check
- `POST /jobs/access` – start full accessibility pipeline
- `POST /jobs/access_simple` – start simplified accessibility pipeline
- `POST /jobs/netascore` – start NetAScore generation job
- `GET /jobs/{job_id}` – job status (`queued`, `running`, `done`, `failed`)
- `GET /jobs/{job_id}/downloads` – list downloadable files for a finished job
- `GET /jobs/{job_id}/download/{key}` – download a specific artifact
- `WS /ws/{job_id}` – waits until job completes (done/failed) then returns final status JSON

> **Auth:** All `/jobs/*` endpoints require an API key via the header:  
> `x-api-key: <API_KEY>`

---

## Job lifecycle

1. **Create a job** using one of the `POST /jobs/*` endpoints.
2. The API returns:
   - `job_id`
   - `status` (initially `queued`)
   - `websocket_url` (optional way to wait for completion)
3. **Track progress**:
   - `GET /jobs/{job_id}` (polling), or
   - `WS /ws/{job_id}` (wait until `done`/`failed`)
4. When status becomes **`done`**, list outputs:
   - `GET /jobs/{job_id}/downloads`
5. Download outputs:
   - `GET /jobs/{job_id}/download/{key}`

Job statuses:
- `queued` – waiting to be processed
- `running` – worker is executing the pipeline
- `done` – outputs are ready to download
- `failed` – job failed; `error` contains a message (and server logs contain traceback)

---

## Pipeline steps (what actually happens)

All job types follow a deterministic sequence of processing steps. The names below match the implementation in `pipeline/run.py`.

### Accessibility (full) — `POST /jobs/access`

1. **HandleDataStep**
   - Reads your input files (clusters A/B, OD table, POIs, optionally Global Streetscapes perception scores).
   - Converts everything to WGS84 and picks an appropriate **UTM SRID** for metric work.
   - Builds a **buffer** around POIs (2× the travel distance threshold) and derives a **bounding box** (`bbox_str`) from it.
   - Drops clusters that are far outside this POI buffer (keeps the analysis area small).
   - If a Global Streetscapes input file is provided: generates a single composite perception score for each street segment in the data.

2. **SaveParametersStep**
   - Writes `job.json` (job_id, target_srid, bbox_str, timestamp) into the job folder (used for caching).

3. **DisaggregateDataStep**
   - For each cluster polygon, randomly distributes `count_field` points inside its geometry.
   - Turns the OD trip table into **point-to-point OD edges** by randomly pairing origin points with destination points.
   - If a table row requests more trips than there are available points in either cluster, trips are reduced (with a log warning).

4. **GenerateNetascoreStep**
   - Either **reuses a cached** `netascore.gpkg` from a recent job with the same bbox (≤ 1 day old), or
   - Runs **NetAScore** (external pipeline) to generate a fresh network dataset for the bbox.

5. **BuildGraphsStep**
   - Loads NetAScore layers and builds a directed NetworkX graph.
   - If a Global Streetscapes input file is provided: joins perception scores into the edges data.
   - Creates two subgraphs for the chosen travel mode:
     - **Base graph**: all edges that are accessible for the mode.
     - **Quality graph**: only edges with `index_{mode} >= index_threshold` *or* `length <= length_minimum`.
   - Removes tiny disconnected components to improve routing robustness.

6. **SnapPointsStep**
   - Snaps all disaggregated origin/destination points to their nearest **base graph** and **quality graph** node.
   - Snaps POIs to their nearest **quality graph** node.

7. **FilterTripsStep**
   - Computes network distances for each OD edge on the base graph (Dijkstra with a cutoff).
   - Removes OD edges with `distance <= distance_threshold_m` (i.e. trips that are already within the reachable range).

8. **EvaluatePOIsStep**
   - For each POI, runs Dijkstra on the **reversed** graphs to find all reachable residents within the distance threshold.
   - Computes for each resident:
     - `index_average_base`: average NetAScore index of the shortest path to the POI on the base graph
     - `index_average_quality`: average NetAScore index of the shortest path to the POI on the quality graph
     - `length_base`: length of the shortest path to the POI on the base graph
     - `length_quality`: length of the shortest path to the POI on the quality graph
     - `length_ratio = length_quality / length_base`
     - `access = (length_ratio <= detour_threshold)`
   - If a Global Streetscapes input file is provided, also computes for each resident:
     - `perception_average`: average perception score of the optimal path to the POI on the quality graph, with the optimal path being the path that maximizes the average perception score but does not exceed the travel time and detour thresholds.
     - `enhanced_access = (perception_average => perception_threshold)`
   - Aggregates POI stats like reachable network length and average index values.
   - Computes for each POI the number of residents that have potential access (access on the base graph) and actual access (access on the quality graph).
   - If a Global Streetscapes input file is provided: computes for each POI the number of residents that have enhanced access (access on the quality graph through beautiful or lively streets).

9. **ExportResultsStep**
   - Writes outputs as GeoJSON or GPKG (depending on `output_format`).

### Accessibility (simple) — `POST /jobs/access_simple`

Same idea, but:
- Only distributes **origin** points (no OD table / destinations),
- Skips the trip-filtering step,
- Evaluates access of origins to POIs in the same way as above.

### NetAScore only — `POST /jobs/netascore`

Only runs steps 1, 2 and 4, then exports the NetAScore layers (useful for debugging / pre-warming caches).

---

## Output layers (what the downloads mean)

All job types return a list of downloadable files via `GET /jobs/{job_id}/downloads`.

Common outputs:

- `pois_output`  
  One feature per POI with summary metrics, including:
  - `length_base`, `length_quality`, `length_ratio`: total length of edges within the travel time threshold
  - `index_average_base`, `index_average_quality`: average NetAScore index values of edges within the travel time threshold
  - `residents_base`: number of residents with potential access, i.e. residents that can reach the POI on the base graph without exceeding the travel time threshold
  - `residents_quality`: number of residents with actual access, i.e. residents that can reach the POI on the quality graph without exceeding the travel time and detour thresholds
  - `residents_ratio`: number of residents with actual access vs. potential access
  If a Global Streetscapes input file is provided, it also includes:
  - `perception_average`: average perception scores of edges within the travel time threshold on the quality graph
  - `residents_enhanced`: number of residents with enhanced access, i.e. residents with actual access that can reach the POI on a path with an average perception score higher than the perception threshold, without exceeding the detour threshold
  - `residents_enhanced_ratio`: number of residents with enhanced access vs. basic access
- `residents`  
  One feature per origin point *per POI*, including:
  - `poi_id`, `point_id`
  - `length_base`, `length_quality`, `length_ratio`: total length of the shortest path between origin and destination
  - `index_average_base`, `index_average_quality`: average NetAScore index value of the shortest path between origin and destination
  - `access` (boolean): whether the origin has actual access to the destination
  If a Global Streetscapes input file is provided, it also includes:
  - `perception_average`: average perception score of the optimal path between origin and destination, with the optimal path being the path on the quality graph that maximizes the average perception score but does not exceed the travel time and detour thresholds.
  - `enhanced_access` (boolean): whether the origin has enhanced access to the destination

Additional outputs:

- `od_points_a`, `od_points_b`  
  The disaggregated origin/destination points (random points inside cluster polygons) with snapped `node_id`.

- `od_edges`  
  Disaggregated OD edges with computed `distance` (base-network distance).  
  Note: edges with `distance <= distance_threshold_m` are removed before export.

Network outputs:

- `edges_base`, `edges_quality`  
  Subsets of the NetAScore edge layer: edges that fall inside at least one POI's reachable subgraph (base/quality).

- `routes_base`, `routes_quality`  
  Present but currently empty by default (route geometry generation is disabled in the evaluator unless enabled server-side).

Optional (depending on caching / settings):

- `netascore` (and possibly `netascore_edges` / `netascore_nodes`)  
  The underlying NetAScore network used for the job.

---

## Create an accessibility job (full)

### `POST /jobs/access`

Runs the full accessibility pipeline, differentiating between:

- **Potential access:** The number of people that can reach a POI within the travel time threshold, using the full street network without considering the quality of street design for the specified travel mode.
- **Actual access:** The number of people that can reach a POI within the travel time threshold exclusively on streets that are sufficiently safe and comfortable, and within an acceptable detour from the shortest path on the full street network.
- **Enhanced access (optional):** The number of people that have actual access *and* can reach a destination on a path that goes through beautiful or lively streets.

### Required file fields

- `od_clusters_a` (`.gpkg` or `.geojson`)  
  Origin clusters (e.g. residential clusters).
- `od_clusters_b` (`.gpkg` or `.geojson`)  
  Destination clusters (e.g. workplace clusters).
- `od_table` (`.csv`)
  Origin–destination table. The API reads it with `;` as delimiter.
- `pois` (`.gpkg` or `.geojson`)  
  Points of interest (e.g. transport stops) to which accessibility should be computed. The POIs are snapped to the quality graph.

### Conditionally required file fields

- `streetscapes` (`.csv`)
  Global Streetscapes data export containing the six human perception scores (beautiful, boring, depressing, lively, safe, wealthy) paired to a specific OpenStreetMap way index. This is required when enhanced accessibility should be computed in addition to potential and actual accessibility.

### Required schema fields (strings)

These tell the API how to read your input attributes:

- `od_clusters_a_id_field` – unique cluster ID in `od_clusters_a` (example: `klynge_id`)
- `od_clusters_a_count_field` – number (e.g. residents) in `od_clusters_a` (example: `Beboere`)
- `od_clusters_b_id_field` – unique cluster ID in `od_clusters_b` (example: `klynge_id`)
- `od_clusters_b_count_field` – number (e.g. workplaces) in `od_clusters_b` (example: `Arbejdere`)
- `od_table_a_id_field` – origin cluster ID column in OD table (example: `Bopael_klynge_id`)
- `od_table_b_id_field` – destination cluster ID column in OD table (example: `Arbejssted_klynge_id`)
- `od_table_trips_field` – trip count column in OD table (example: `Antal`)
- `pois_id_field` – unique POI ID field (example: `stopnummer`)

### Required analysis settings

- `travel_mode` – `bike` or `walk`

### Optional analysis settings (defaults depend on mode)

All of these can be omitted to use mode-specific defaults.

- `travel_time_min` (float)  
  The travel time threshold (in minutes). A route that exceeds the travel time threshold does not provide accessibility to the destination.
- `travel_speed_kmh` (float)
  Travel speed in km/h. Used to convert `travel_time_min` to a distance threshold.
- `detour_threshold` (float)  
  Maximum detour ratio for an entire route to be considered acceptable. The detour ratio compares the length of a route to the shortest possible route on the entire network. A route that exceeds the detour threshold does not provide accessibility to the destination.
- `index_threshold` (float) 
  Minimum NetAScore index value for an individual street segment to be considered sufficiently safe and comfortable. Only street segments with a NetAscore index value higher than or equal to this threshold are contained in the quality graph.
- `perception_threshold` (float)  
  Minimum average perception score of an entire route to be considered sufficiently beautiful and lively. This value is only used to compute enhanced accessibility when a Global Streetscapes input file is provided, and ignored otherwise.
- `length_minimum` (float) 
  Minimum length (in meters) of a street segment to be evaluated by its NetAScore index. Any street segment with a shorter length will be contained in the quality graph irrespective of its NetAScore index. This allows to preserve short connectors even if its NetAScore index is low.

> **Defaults are defined in code** (see `pipeline/run.py` → `TRAVEL_MODE_DEFAULTS`):
> - bike: time 15 min, speed 12 km/h, detour 1.5, index 0.5, perception 0.5, length_minimum 0.0  
> - walk: time 15 min, speed 5 km/h, detour 1.5, index 0.35, perception 0.5, length_minimum 0.0

### Optional NetAScore controls

- `use_cached_netascore` (bool, default: `true`)  
  If enabled, the API tries to re-use a NetAScore dataset generated recently for the same bbox/SRID.
- `netascore_gpkg` (file, optional, `.gpkg`)  
  Provide your own pre-generated NetAScore GPKG to skip generation.

### Output controls

- `output_format` – `GeoJSON` (default) or `GPKG`
- `seed` (int, optional) – makes random/disaggregation steps reproducible

### Example (curl)

```bash
curl -X POST "http://localhost:8000/jobs/access" \
  -H "x-api-key: $API_KEY" \
  -F "od_clusters_a=@b_klynger.gpkg" \
  -F "od_clusters_b=@a_klynger.gpkg" \
  -F "od_table=@Data_2023_0099_Tabel_1.csv" \
  -F "pois=@dynlayer.gpkg" \
  -F "od_clusters_a_id_field=klynge_id" \
  -F "od_clusters_a_count_field=Beboere" \
  -F "od_clusters_b_id_field=klynge_id" \
  -F "od_clusters_b_count_field=Arbejdere" \
  -F "od_table_a_id_field=Bopael_klynge_id" \
  -F "od_table_b_id_field=Arbejssted_klynge_id" \
  -F "od_table_trips_field=Antal" \
  -F "pois_id_field=stopnummer" \
  -F "travel_mode=bike" \
  -F "output_format=GeoJSON"
```

Response example:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "websocket_url": "ws://localhost:8000/ws/550e8400-e29b-41d4-a716-446655440000"
}
```

---

## Create an accessibility job (simple)

### `POST /jobs/access_simple`

Runs a simplified accessibility pipeline. Like `/jobs/access`, but requires only:
- `od_clusters_a` (origins)
- `pois`

Required fields:
- `od_clusters_a_id_field`
- `od_clusters_a_count_field`
- `pois_id_field`
- `travel_mode`

All optional tuning / output settings are the same as `/jobs/access`.

---

## Create a NetAScore job

### `POST /jobs/netascore`

Generates a NetAScore dataset for a bounding box and a target SRID.

Fields:
- `target_srid` (int, required)  
  EPSG code for the output projection.
- `bbox_str` (string, required)  
  Bounding box string passed to NetAScore.

Output controls:
- `output_format` – `GeoJSON` (default) or `GPKG`

> Note: The accessibility endpoints compute `target_srid` and `bbox_str` from your POIs automatically.

---

## Check job status

### `GET /jobs/{job_id}`

Returns:
- `job_id`
- `status`
- optional fields: `step`, `created_at`, `started_at`, `finished_at`, `error`

Example:
```bash
curl -H "x-api-key: $API_KEY" "http://localhost:8000/jobs/$JOB_ID"
```

---

## List downloadable outputs

### `GET /jobs/{job_id}/downloads`

Only works when a job is `done`.

Example response:
```json
[
  {"key":"pois_output","filename":"pois_output.geojson","download_url":"/jobs/<id>/download/pois_output"},
  {"key":"residents","filename":"residents.geojson","download_url":"/jobs/<id>/download/residents"}
]
```

---

## Download a specific output

### `GET /jobs/{job_id}/download/{key}`

Downloads the output file identified by `key` from the downloads list.

Example:
```bash
curl -L -H "x-api-key: $API_KEY" \
  "http://localhost:8000/jobs/$JOB_ID/download/pois_output" \
  -o pois_output.geojson
```

---

## WebSocket: wait for completion

### `WS /ws/{job_id}`

Connects and waits until the job finishes (`done` or `failed`) and then sends a final `JobStatusOut` JSON payload before closing.

This is useful if you don't want to poll.

---

## Output files (what you get)

The exact output keys depend on the job type and whether NetAScore was generated/cached.

Common outputs for accessibility jobs:
- `pois_output` – POIs annotated with results from evaluation (format depends on pipeline implementation)
- `residents` – origin-side results (e.g. distribution / aggregation of residents that can access POIs)

Additional files may be present (especially when NetAScore is generated and `output_format=GeoJSON`), such as:
- `netascore` (GPKG) and potentially `netascore_edges`, `netascore_nodes` (GeoJSON exports)
- intermediate layers like points/edges/routes used in the evaluation

Use the downloads endpoint to see what your specific job produced.
