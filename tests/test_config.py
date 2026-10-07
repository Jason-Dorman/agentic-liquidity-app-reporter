"""config.py: settings load from the environment, .env first, and fail naming the setting."""

from pathlib import Path

import pytest

from daily_review.config import Settings, SettingsError, load_settings, read_environment

KEY = {"ANTHROPIC_API_KEY": "sk-ant-test-key"}
INTEGER_SETTINGS = ["MAX_TOOL_CALLS", "MAX_OUTPUT_TOKENS", "HISTORY_DAYS"]


def test_missing_api_key_fails_and_names_the_setting():
    """R-CFG-2: a missing key stops the run before any call, naming the setting."""
    with pytest.raises(SettingsError) as caught:
        load_settings({})
    assert caught.value.names == ("ANTHROPIC_API_KEY",)
    assert "ANTHROPIC_API_KEY" in str(caught.value)


def test_blank_api_key_counts_as_missing():
    """R-CFG-2: .env.example ships the key blank; blank must not pass as a key."""
    with pytest.raises(SettingsError) as caught:
        load_settings({"ANTHROPIC_API_KEY": "  "})
    assert caught.value.names == ("ANTHROPIC_API_KEY",)


def test_defaults():
    """R-CFG-1: every setting but the key has a default."""
    settings = load_settings(KEY)
    assert settings.blockford_api_base_url == "http://localhost:3300/corridor-scout/api"
    assert settings.model == "claude-sonnet-5-5"
    assert settings.max_tool_calls == 15
    assert settings.max_output_tokens == 16000
    assert settings.history_days == 7


def test_values_from_the_environment_replace_defaults():
    settings = load_settings(
        {
            **KEY,
            "BLOCKFORD_API_BASE_URL": "http://localhost:3301/corridor-scout/api",
            "MODEL": "claude-opus-5-5",
            "MAX_TOOL_CALLS": "3",
            "MAX_OUTPUT_TOKENS": "8000",
            "HISTORY_DAYS": "14",
        }
    )
    assert settings.blockford_api_base_url == "http://localhost:3301/corridor-scout/api"
    assert settings.model == "claude-opus-5-5"
    assert (settings.max_tool_calls, settings.max_output_tokens, settings.history_days) == (
        3,
        8000,
        14,
    )


def test_blank_optional_setting_takes_its_default():
    settings = load_settings({**KEY, "MODEL": "", "HISTORY_DAYS": " "})
    assert settings.model == "claude-sonnet-5-5"
    assert settings.history_days == 7


@pytest.mark.parametrize("name", INTEGER_SETTINGS)
@pytest.mark.parametrize("bad", ["abc", "1.5", "0", "-3"])
def test_malformed_integer_fails_and_names_the_setting(name, bad):
    """R-CFG-2: a malformed integer stops the run, naming the setting."""
    with pytest.raises(SettingsError) as caught:
        load_settings({**KEY, name: bad})
    assert caught.value.names == (name,)
    assert name in str(caught.value)


def test_every_bad_setting_is_named_at_once():
    with pytest.raises(SettingsError) as caught:
        load_settings({"MAX_TOOL_CALLS": "x", "HISTORY_DAYS": "0"})
    assert set(caught.value.names) == {"ANTHROPIC_API_KEY", "MAX_TOOL_CALLS", "HISTORY_DAYS"}


@pytest.mark.parametrize("bad", ["localhost:3300/corridor-scout/api", "ftp://localhost/api"])
def test_base_url_without_http_scheme_fails_and_names_the_setting(bad):
    with pytest.raises(SettingsError) as caught:
        load_settings({**KEY, "BLOCKFORD_API_BASE_URL": bad})
    assert caught.value.names == ("BLOCKFORD_API_BASE_URL",)


def test_api_key_never_appears_when_settings_are_printed():
    """ARCHITECTURE section 7: the key never appears in a log line."""
    settings = load_settings(KEY)
    assert "sk-ant-test-key" not in repr(settings)
    assert "sk-ant-test-key" not in str(settings)
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-test-key"


def test_settings_are_frozen():
    settings = load_settings(KEY)
    with pytest.raises(ValueError):
        settings.model = "other"


def test_dotenv_is_read(tmp_path: Path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("ANTHROPIC_API_KEY=from-file\nMAX_TOOL_CALLS=4\n")
    settings = load_settings(read_environment(dotenv, {}))
    assert settings.anthropic_api_key.get_secret_value() == "from-file"
    assert settings.max_tool_calls == 4


def test_environment_wins_over_dotenv(tmp_path: Path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("ANTHROPIC_API_KEY=from-file\nMAX_TOOL_CALLS=4\n")
    settings = load_settings(read_environment(dotenv, {"MAX_TOOL_CALLS": "9"}))
    assert settings.max_tool_calls == 9


def test_blank_environment_value_does_not_hide_dotenv_value(tmp_path: Path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("ANTHROPIC_API_KEY=from-file\n")
    environment = read_environment(dotenv, {"ANTHROPIC_API_KEY": ""})
    assert load_settings(environment).anthropic_api_key.get_secret_value() == "from-file"


def test_missing_dotenv_file_is_not_an_error(tmp_path: Path):
    assert read_environment(tmp_path / "absent.env", KEY) == KEY


def test_settings_type_is_exported():
    assert isinstance(load_settings(KEY), Settings)
