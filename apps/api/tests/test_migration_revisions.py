from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

API_ROOT = Path(__file__).resolve().parents[1]


def test_all_alembic_revision_ids_fit_the_version_table() -> None:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    revisions = list(ScriptDirectory.from_config(config).walk_revisions())

    assert revisions
    assert all(len(item.revision) <= 32 for item in revisions)
