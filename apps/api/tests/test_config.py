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
