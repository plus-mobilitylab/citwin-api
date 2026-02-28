# CITWIN API Deployment

## 1. Overview

| Deployment  | Git Branch | Folder                     | Conda Environment | Service        | Port | Web Route       | Environment File  |
|-------------|------------|----------------------------|-------------------|----------------|------|-----------------|-------------------|
| Production  | main       | C:\services\citwin-api     | citwin-api        | citwin-api     | 8002 | /api/citwin     | .env.prod.example |
| Development | dev        | C:\services\citwin-api-dev | citwin-api-dev    | citwin-api-dev | 9002 | /api/citwin/dev | .env.dev.example  |

## 2. Prerequisites

- Install NSSM: https://nssm.cc/download, install to C:\nssm, add to Path
- Install osm2pgsql: https://osm2pgsql.org, install to C:\osm2pgsql, add to Path

## 3. Deploy CITWIN API: Production

```bash
ssh b1003527@zgis244.geo.sbg.ac.at 'powershell -Command "git clone --branch main https://github.com/robin-wendel/citwin-api.git C:/services/citwin-api"'
scp .env.prod b1003527@zgis244.geo.sbg.ac.at:C:/services/citwin-api/.env
```

```bash
ssh b1003527@zgis244.geo.sbg.ac.at 'powershell -Command "git -C C:/services/citwin-api fetch origin; git -C C:/services/citwin-api reset --hard origin/main"'
ssh b1003527@zgis244.geo.sbg.ac.at 'powershell -File C:/services/citwin-api/deploy.ps1 -CondaEnv "citwin-api" -Database "citwin_api_netascore" -Password "<password>" -NssmService "citwin-api" -ApiPort "8002" -ApiRootPath "/api/citwin"'
```

```bash
ssh b1003527@zgis244.geo.sbg.ac.at 'powershell -Command "nssm stop citwin-api; nssm remove citwin-api confirm"'
ssh b1003527@zgis244.geo.sbg.ac.at 'powershell -Command "conda env remove -n citwin-api -y"'
ssh b1003527@zgis244.geo.sbg.ac.at 'powershell -Command "Remove-Item -Path 'C:/ProgramData/miniconda3/envs/citwin-api' -Recurse -Force"'
ssh b1003527@zgis244.geo.sbg.ac.at 'powershell -Command "Remove-Item -Path 'C:/services/citwin-api' -Recurse -Force"'
```

## 4. Deploy CITWIN API: Development

```bash
ssh b1003527@zgis244.geo.sbg.ac.at 'powershell -Command "git clone --branch main https://github.com/robin-wendel/citwin-api.git C:/services/citwin-api-dev"'
scp .env.dev b1003527@zgis244.geo.sbg.ac.at:C:/services/citwin-api-dev/.env
```

```bash
ssh b1003527@zgis244.geo.sbg.ac.at 'powershell -Command "git -C C:/services/citwin-api-dev fetch origin; git -C C:/services/citwin-api-dev reset --hard origin/main"'
ssh b1003527@zgis244.geo.sbg.ac.at 'powershell -File C:/services/citwin-api-dev/deploy.ps1 -CondaEnv "citwin-api-dev" -Database "citwin_api_netascore_dev" -Password "<password>" -NssmService "citwin-api-dev" -ApiPort "9002" -ApiRootPath "/api/citwin-dev"'
```

```bash
ssh b1003527@zgis244.geo.sbg.ac.at 'powershell -Command "nssm stop citwin-api-dev; nssm remove citwin-api-dev confirm"'
ssh b1003527@zgis244.geo.sbg.ac.at 'powershell -Command "conda env remove -n citwin-api-dev -y"'
ssh b1003527@zgis244.geo.sbg.ac.at 'powershell -Command "Remove-Item -Path 'C:/ProgramData/miniconda3/envs/citwin-api-dev' -Recurse -Force"'
ssh b1003527@zgis244.geo.sbg.ac.at 'powershell -Command "Remove-Item -Path 'C:/services/citwin-api-dev' -Recurse -Force"'
```
