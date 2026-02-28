import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    api_key: str
    db_host: str
    db_port: int
    db_name: str
    db_username: str
    db_password: str

    api_root_path: str = "/"

    class Config:
        env_file = [
            Path(__file__).resolve().parents[1] / ".env",
            Path(__file__).resolve().parents[1] / ".env.local",
        ] if not os.getenv("DOCKER_ENV") else []


settings = Settings()
