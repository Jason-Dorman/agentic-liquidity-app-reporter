"""Load and validate settings from the environment into one typed Settings value."""

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, PositiveInt, SecretStr, ValidationError, field_validator

DEFAULT_DOTENV = Path(".env")


class SettingsError(Exception):
    """One or more settings are missing or malformed. `names` holds their environment names."""

    def __init__(self, problems: Mapping[str, str]):
        self.names = tuple(problems)
        lines = [f"{name}: {problem}" for name, problem in problems.items()]
        super().__init__("Bad settings. Fix .env or the environment.\n" + "\n".join(lines))


class Settings(BaseModel):
    """Every setting from spec section 10. Field names are the environment names, lower case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    anthropic_api_key: SecretStr
    blockford_api_base_url: str = "http://localhost:3300/corridor-scout/api"
    model: str = "claude-sonnet-5-5"
    max_tool_calls: PositiveInt = 15
    max_output_tokens: PositiveInt = 16000
    history_days: PositiveInt = 7

    @field_validator("blockford_api_base_url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value


def _present(values: Mapping[str, str | None]) -> dict[str, str]:
    """Drop unset and blank values, so a blank counts as not set."""
    return {name: value for name, value in values.items() if value and value.strip()}


def read_environment(dotenv_path: Path, environ: Mapping[str, str]) -> dict[str, str]:
    """The .env file's values with the real environment laid over them. Writes nothing."""
    return {**_present(dotenv_values(dotenv_path)), **_present(environ)}


def _problems(error: ValidationError) -> dict[str, str]:
    """Map pydantic errors to environment names. Never echoes a value: one may be the key."""
    problems: dict[str, str] = {}
    for detail in error.errors():
        name = str(detail["loc"][0]).upper()
        problems[name] = "is required" if detail["type"] == "missing" else detail["msg"]
    return problems


def load_settings(environ: Mapping[str, str]) -> Settings:
    """Build Settings from a name-to-value mapping. Raises SettingsError naming each bad one."""
    present = _present(environ)
    names = {field: field.upper() for field in Settings.model_fields}
    values = {field: present[name] for field, name in names.items() if name in present}
    try:
        return Settings(**values)
    except ValidationError as error:
        raise SettingsError(_problems(error)) from None


def settings_from_environment(dotenv_path: Path = DEFAULT_DOTENV) -> Settings:
    """Load Settings from .env and the process environment. The only reader of os.environ."""
    return load_settings(read_environment(dotenv_path, os.environ))
