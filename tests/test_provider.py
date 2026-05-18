"""Tests do dispatch claude/gemini e do parser de spec."""

from win_runner.provider import MODELS_PER_PROVIDER, PROVIDERS, model_id_for, parse_spec


def test_parse_spec_alias_bare():
    assert parse_spec("opus") == ("claude", "opus")
    assert parse_spec("sonnet") == ("claude", "sonnet")
    assert parse_spec("haiku") == ("claude", "haiku")


def test_parse_spec_with_provider():
    assert parse_spec("claude:opus") == ("claude", "opus")
    assert parse_spec("gemini:pro") == ("gemini", "pro")
    assert parse_spec("gemini:flash") == ("gemini", "flash")


def test_parse_spec_unknown_prefix_falls_back_to_claude():
    # Spec com prefixo desconhecido cai no claude, tratando inteiro como alias.
    assert parse_spec("codex:gpt5") == ("claude", "codex:gpt5")


def test_parse_spec_empty():
    assert parse_spec("") == ("claude", "")
    assert parse_spec(None) == ("claude", "")


def test_model_id_for_claude():
    assert model_id_for("claude", "opus") == "claude-opus-4-7"
    assert model_id_for("claude", "sonnet") == "claude-sonnet-4-6"
    assert model_id_for("claude", "haiku") == "claude-haiku-4-5"


def test_model_id_for_gemini():
    assert model_id_for("gemini", "pro") == "gemini-3.1-pro-preview"
    assert model_id_for("gemini", "flash") == "gemini-3-flash-preview"


def test_model_id_full_id_passthrough():
    assert model_id_for("claude", "claude-opus-4-7") == "claude-opus-4-7"
    assert model_id_for("gemini", "gemini-3.1-pro-preview") == "gemini-3.1-pro-preview"


def test_providers_table_complete():
    assert set(MODELS_PER_PROVIDER) == set(PROVIDERS)
