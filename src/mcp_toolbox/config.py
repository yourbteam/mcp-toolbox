"""Configuration management for MCP Toolbox."""

import os
from pathlib import Path
from typing import Literal, cast

from dotenv import load_dotenv

# Load .env for local development; in production, env vars come from host config
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

LOG_LEVEL: LogLevel = cast(LogLevel, os.getenv("LOG_LEVEL", "INFO"))
