import pytest
from pydantic import ValidationError

from chatbi.config import Settings


def test_secret_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATBI_SECRET_KEY", "s3cret-from-env")

    settings = Settings()

    assert settings.secret_key.get_secret_value() == "s3cret-from-env"


def test_secret_key_from_file(monkeypatch, tmp_path) -> None:
    key_file = tmp_path / "master.key"
    key_file.write_text("  s3cret-from-file\n", encoding="utf-8")
    monkeypatch.delenv("CHATBI_SECRET_KEY", raising=False)
    monkeypatch.setenv("CHATBI_SECRET_KEY_FILE", str(key_file))

    settings = Settings()

    assert settings.secret_key.get_secret_value() == "s3cret-from-file"


def test_missing_secret_key_is_a_clear_error(monkeypatch) -> None:
    monkeypatch.delenv("CHATBI_SECRET_KEY", raising=False)
    monkeypatch.delenv("CHATBI_SECRET_KEY_FILE", raising=False)

    with pytest.raises(ValidationError) as excinfo:
        Settings()

    assert "CHATBI_SECRET_KEY" in str(excinfo.value)


def test_empty_key_file_is_rejected(monkeypatch, tmp_path) -> None:
    key_file = tmp_path / "empty.key"
    key_file.write_text("   \n", encoding="utf-8")
    monkeypatch.delenv("CHATBI_SECRET_KEY", raising=False)
    monkeypatch.setenv("CHATBI_SECRET_KEY_FILE", str(key_file))

    with pytest.raises(ValidationError):
        Settings()


def test_repr_does_not_leak_the_secret(monkeypatch) -> None:
    monkeypatch.setenv("CHATBI_SECRET_KEY", "do-not-print-me")

    settings = Settings()

    assert "do-not-print-me" not in repr(settings)


def test_the_llm_timeouts_are_two_separate_knobs(monkeypatch) -> None:
    """**两个超时必须能分别配**（P3c 设计 §3.2）。

    合成一个值的实现在这条测试上会红。它守的不是「有没有默认值」，而是「首 token 与
    总时长是两件不同的事」这个判断——上游 spec §4.5 的单一 30s 已被实测推翻（本机
    冷启动 36s，单一 30s 会让冷启动必然误报超时）。
    """
    monkeypatch.setenv("CHATBI_SECRET_KEY", "s3cret")
    monkeypatch.setenv("CHATBI_LLM_FIRST_TOKEN_TIMEOUT", "5")
    monkeypatch.setenv("CHATBI_LLM_TOTAL_TIMEOUT", "7")

    settings = Settings()

    assert settings.llm_first_token_timeout == 5.0
    assert settings.llm_total_timeout == 7.0


def test_the_llm_defaults_match_the_measured_numbers() -> None:
    """默认值就是设计 §0.1 那组实测数字推出来的，改它们要先重测。"""
    settings = Settings(secret_key="s3cret")

    assert settings.llm_first_token_timeout == 60.0  # 覆盖 36s 冷启动
    assert settings.llm_total_timeout == 180.0  # 4.1 tok/s 下约 700 token
    assert settings.llm_provider == "ollama"
