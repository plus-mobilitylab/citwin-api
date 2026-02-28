FROM python:3.13.7-trixie

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gdal-bin=3.10.3* \
        libgdal-dev=3.10.3* \
        osm2pgsql \
        postgresql-client-17 \
        python3-dev && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "api.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
