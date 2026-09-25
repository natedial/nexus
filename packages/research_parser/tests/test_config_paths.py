"""REPO_ROOT resolves in monorepo checkouts and standalone/Docker layouts."""

from src.config import PACKAGE_ROOT, REPO_ROOT, Settings


def test_repo_root_resolves_without_index_error():
    assert REPO_ROOT.is_absolute()
    if PACKAGE_ROOT.parent.name == "packages":
        assert REPO_ROOT == PACKAGE_ROOT.parent.parent
    else:
        assert REPO_ROOT == PACKAGE_ROOT


def test_settings_env_file_tuple_uses_repo_and_package_roots():
    env_files = Settings.model_config["env_file"]
    assert env_files == (REPO_ROOT / ".env", PACKAGE_ROOT / ".env")
