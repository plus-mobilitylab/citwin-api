# CITWIN API

![Python](https://img.shields.io/badge/Python-3.13%2B-blue.svg?logo=python)
![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED.svg?logo=docker)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Status](https://img.shields.io/badge/Status-Active-success.svg)

This Python-based API implements a computational workflow for the analysis of active transport accessibility in urban environments. The workflow extends traditional time-based or distance-based accessibility analyses by incorporating estimations of perceived safety, comfort, and enjoyment.

The following pages describe the software in more detail:

- For a summary of the theoretical underpinning, see **[THEORY.md](docs/THEORY.md)**
- For explanations on using the API (endpoints, parameters, examples), see **[USER.md](docs/USER.md)**
- For explanations on running the API on a server (Docker, environment variables, deployment), see **[DEVELOPER.md](docs/DEVELOPER.md)**

Note that the enjoyment extension is still experimental and only integrated into the development branch [perception](https://github.com/plus-mobilitylab/citwin-api/tree/perception). The main branch can be considered stable.

## Quick overview

### What the API does

- **Generates or re-uses a NetAScore network dataset** for a bounding box inferred from your input POIs.
- **Builds travel-mode graphs** (walk/bike) and a *quality-filtered* subgraph using a configurable index threshold.
- **Snaps your input points** (origins, destinations, POIs) to the network.
- **Computes accessibility outputs** (e.g. reachable origins relative to POIs, network/route layers used for evaluation).
- Exposes results as downloadable files once a job is complete.

The API is implemented with **FastAPI** and runs the heavy work asynchronously via an **in-process job queue**. You submit a job, poll its status (or watch a WebSocket), and then download the resulting files.

### How you can interact with it

The API exposes three main job types:

- **Accessibility (full)**: `/jobs/access`
  Uses *origin clusters*, *destination clusters*, and an *origin–destination trip table* to evaluate accessibility of POIs.

- **Accessibility (simple)**: `/jobs/access_simple`
  Uses *origin clusters only* (no OD table and no destination clusters) to evaluate accessibility of POIs.

- **NetAScore generation**: `/jobs/netascore`
  Generates a NetAScore dataset for a specified bounding box and target SRID.

All accessibility jobs support:

- travel mode: `walk` or `bike`
- optional tuning parameters (travel time, speed, detour threshold, quality index threshold, etc.)
- output format: `GeoJSON` or `GPKG`

## Licensing

This software is licensed under the **[MIT License](LICENSE)**
  > © 2026 University of Salzburg, Department of Geoinformatics

## Funding

This work was supported through the Driving Urban Transitions (DUT) partnership by the European Commission and Österreichische Forschungsförderungsgesellschaft (FFG) under Grant **FO999905451**, project name **CITWIN**.
