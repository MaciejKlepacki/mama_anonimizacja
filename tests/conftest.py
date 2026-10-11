import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.engine import get_anonymizer  # noqa: E402
from app.settings import load_settings  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "wyrok_przyklad.docx"


@pytest.fixture(scope="session")
def settings():
    # testy nie zależą od lokalnego config/settings.json
    return load_settings(user_path=ROOT / "config" / "__nonexistent__.json")


@pytest.fixture(scope="session")
def engine(settings):
    return get_anonymizer(settings)


@pytest.fixture(scope="session")
def fixture_docx():
    if not FIXTURE.exists():
        from tests.make_fixture import build

        build(FIXTURE)
    return FIXTURE


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Klient API z odizolowanym plikiem ustawień użytkownika."""
    from fastapi.testclient import TestClient

    import app.settings as st
    from app import main as main_mod

    user_path = tmp_path / "settings.json"
    monkeypatch.setattr(st, "USER_SETTINGS_PATH", user_path)
    monkeypatch.setattr(main_mod, "load_settings", lambda: st.load_settings(user_path))
    monkeypatch.setattr(main_mod, "save_settings", lambda s: st.save_settings(s, user_path))
    monkeypatch.setattr(main_mod, "reset_settings", lambda: st.reset_settings(user_path))
    with TestClient(main_mod.app) as c:
        yield c, user_path
