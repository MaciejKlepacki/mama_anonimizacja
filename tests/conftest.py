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
