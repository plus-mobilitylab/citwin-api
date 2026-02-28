# CITWIN API

![Python](https://img.shields.io/badge/Python-3.13%2B-blue.svg?logo=python)
![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED.svg?logo=docker)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Status](https://img.shields.io/badge/Status-Active-success.svg)

> Developed as part of the **CITWIN** research project, this Python-based API implements a computational pipeline for the **accessibility analysis** of **public transport stops**. The framework combines **origin–destination data** with NetAScore **bikeability** and **walkability** indices to assess and quantify active mobility accessibility in urban environments.

---

## Development

Run the API locally (`.env.local`)

```bash
python main.py
```

Run the API with Docker (`.env.docker`)

```bash
docker compose up --build
```

```bash
docker compose down --volumes
```

---

## Deployment

Deploy: clone / pull repository to project directory, configure nginx, start the API in a Docker container (`.env.deploy.*`)

```bash
sh deploy.sh prod
```

```bash
sh deploy.sh staging
```

```bash
sh deploy.sh dev
```

Undeploy: stop and remove containers, delete project directory, unconfigure nginx

```bash
sh undeploy.sh prod
```

```bash
sh undeploy.sh staging
```

```bash
sh undeploy.sh dev
```

---

## Testing

### Test the pipeline

Local (`.env.local`)

```bash
python tests/test_run.py
```

```bash
python tests/test_run.py --upload-netascore
```

---

### Test the API

Local (`.env.local`)

```bash
python test/test_api.py --base-url http://localhost:8000 --no-download
```

```bash
python test/test_api.py --base-url http://localhost:8000 --no-download --upload-netascore
```

Remote – Production (`.env.local`)

```bash
python test/test_api.py --base-url http://zgis228.geo.sbg.ac.at/api/citwin-prod --no-download
```

```bash
python test/test_api.py --base-url http://zgis228.geo.sbg.ac.at/api/citwin-prod --no-download --upload-netascore
```

Remote – Staging (`.env.local`)

```bash
python test/test_api.py --base-url http://zgis228.geo.sbg.ac.at/api/citwin-staging --no-download
```

```bash
python test/test_api.py --base-url http://zgis228.geo.sbg.ac.at/api/citwin-staging --no-download --upload-netascore
```

Remote – Development (`.env.local`)

```bash
python test/test_api.py --base-url http://zgis228.geo.sbg.ac.at/api/citwin-dev --no-download
```

```bash
python test/test_api.py --base-url http://zgis228.geo.sbg.ac.at/api/citwin-dev --no-download --upload-netascore
```
