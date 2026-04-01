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

# SendGrid
SENDGRID_API_KEY: str | None = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL: str | None = os.getenv("SENDGRID_FROM_EMAIL")
SENDGRID_FROM_NAME: str | None = os.getenv("SENDGRID_FROM_NAME")

# ClickUp
CLICKUP_API_TOKEN: str | None = os.getenv("CLICKUP_API_TOKEN")
CLICKUP_TEAM_ID: str | None = os.getenv("CLICKUP_TEAM_ID")
