# Docker

```bash
docker build -t citwin-api .
```

```bash
docker run -d -p 8000:8000 --name citwin-api citwin-api
```

```bash
docker stop citwin-api
docker rm citwin-api
```

# Docker Compose

```bash
docker compose up --build api
```

```bash
docker compose down
```

# Cleanup

```bash
docker builder prune -a -f
```

```bash
docker system prune -a --volumes -f
```
