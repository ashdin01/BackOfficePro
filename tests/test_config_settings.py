"""Tests for config/settings.py's DATA_DIR resolution.

Run via subprocess (not import + monkeypatch) since DATA_DIR is resolved
at module import time — a subprocess keeps each scenario isolated from the
already-imported config.settings used by every other test in this suite.
"""
import os
import subprocess
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolved_data_dir(env_overrides):
    env = dict(os.environ, **env_overrides)
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings as s; print(s.DATA_DIR)"],
        cwd=_REPO_ROOT, env=env, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def test_data_dir_override_env_var_is_honored(tmp_path):
    override_dir = str(tmp_path / "explicit_data")
    resolved = _resolved_data_dir({"BACKOFFICEPRO_DATA_DIR": override_dir})
    assert resolved == override_dir


def test_default_unfrozen_data_dir_unaffected_without_override(tmp_path):
    default_resolved = _resolved_data_dir({})
    assert default_resolved == os.path.join(_REPO_ROOT, "data")
