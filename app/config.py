from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import ValidationError

from app.models import AgentConfig, RuntimeSecrets


def load_dotenv(dotenv_path: str = ".env") -> None:
    path = Path(dotenv_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def load_agent_config(config_path: str) -> AgentConfig:
    data = tomllib.loads(Path(config_path).read_text(encoding="utf-8"))
    try:
        return AgentConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"配置文件校验失败: {exc}") from exc


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_runtime_secrets() -> RuntimeSecrets:
    data = {
        "confluence_base_url": os.getenv("CONFLUENCE_BASE_URL", "").rstrip("/"),
        "confluence_email": os.getenv("CONFLUENCE_EMAIL"),
        "confluence_api_token": os.getenv("CONFLUENCE_API_TOKEN"),
        "confluence_bearer_token": os.getenv("CONFLUENCE_BEARER_TOKEN"),
        "html_cookie": os.getenv("HTML_COOKIE"),
        "confluence_ssl_verify": _env_bool("CONFLUENCE_SSL_VERIFY", True),
        "confluence_ca_bundle": os.getenv("CONFLUENCE_CA_BUNDLE"),
        "llm_base_url": os.getenv("LLM_BASE_URL"),
        "llm_api_key": os.getenv("LLM_API_KEY"),
        "llm_model": os.getenv("LLM_MODEL"),
        "llm_ssl_verify": _env_bool("LLM_SSL_VERIFY", True),
        "llm_ca_bundle": os.getenv("LLM_CA_BUNDLE"),
    }

    try:
        secrets = RuntimeSecrets.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"环境变量校验失败: {exc}") from exc

    if not secrets.confluence_base_url:
        raise ValueError("缺少 CONFLUENCE_BASE_URL 环境变量。")

    return secrets
