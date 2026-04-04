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

# Office 365 (Microsoft Graph)
O365_TENANT_ID: str | None = os.getenv("O365_TENANT_ID")
O365_CLIENT_ID: str | None = os.getenv("O365_CLIENT_ID")
O365_CLIENT_SECRET: str | None = os.getenv("O365_CLIENT_SECRET")
O365_USER_ID: str | None = os.getenv("O365_USER_ID")

# Microsoft Teams (reuses O365 credentials if not set separately)
TEAMS_TENANT_ID: str | None = os.getenv("TEAMS_TENANT_ID") or O365_TENANT_ID
TEAMS_CLIENT_ID: str | None = os.getenv("TEAMS_CLIENT_ID") or O365_CLIENT_ID
TEAMS_CLIENT_SECRET: str | None = os.getenv("TEAMS_CLIENT_SECRET") or O365_CLIENT_SECRET

# Azure Key Vault
KEYVAULT_URL: str | None = os.getenv("KEYVAULT_URL")
KEYVAULT_TENANT_ID: str | None = os.getenv("KEYVAULT_TENANT_ID") or O365_TENANT_ID
KEYVAULT_CLIENT_ID: str | None = os.getenv("KEYVAULT_CLIENT_ID") or O365_CLIENT_ID
KEYVAULT_CLIENT_SECRET: str | None = os.getenv("KEYVAULT_CLIENT_SECRET") or O365_CLIENT_SECRET

# AWS (optional — boto3 reads credentials from env/config/IAM automatically)
AWS_ACCESS_KEY_ID: str | None = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY: str | None = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_DEFAULT_REGION: str | None = os.getenv("AWS_DEFAULT_REGION")

# Slack
SLACK_BOT_TOKEN: str | None = os.getenv("SLACK_BOT_TOKEN")

# HubSpot
HUBSPOT_API_TOKEN: str | None = os.getenv("HUBSPOT_API_TOKEN")

# Jira
JIRA_BASE_URL: str | None = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL: str | None = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN: str | None = os.getenv("JIRA_API_TOKEN")

# Google Tasks
GTASKS_DELEGATED_USER: str | None = os.getenv("GTASKS_DELEGATED_USER")

# GitHub
GITHUB_TOKEN: str | None = os.getenv("GITHUB_TOKEN")
GITHUB_DEFAULT_OWNER: str | None = os.getenv("GITHUB_DEFAULT_OWNER")
GITHUB_DEFAULT_REPO: str | None = os.getenv("GITHUB_DEFAULT_REPO")

# QuickBooks Online
QB_CLIENT_ID: str | None = os.getenv("QB_CLIENT_ID")
QB_CLIENT_SECRET: str | None = os.getenv("QB_CLIENT_SECRET")
QB_REFRESH_TOKEN: str | None = os.getenv("QB_REFRESH_TOKEN")
QB_REALM_ID: str | None = os.getenv("QB_REALM_ID")
QB_ENVIRONMENT: str = os.getenv("QB_ENVIRONMENT", "production")

# Google Sheets
GOOGLE_SERVICE_ACCOUNT_JSON: str | None = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID: str | None = os.getenv(
    "GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID"
)

# Stripe
STRIPE_API_KEY: str | None = os.getenv("STRIPE_API_KEY")
