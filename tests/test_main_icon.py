"""Tests for the app icon setup in main.py."""
import os
import sys
import types
import pytest
from unittest.mock import MagicMock, patch


# ── Icon file existence ───────────────────────────────────────────────────────

def test_icon_file_exists():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, 'assets', 'icon.ico')
    assert os.path.isfile(path), f"icon.ico not found at {path}"


def test_icon_file_is_nonzero():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, 'assets', 'icon.ico')
    assert os.path.getsize(path) > 0


# ── _configure_app_icon ───────────────────────────────────────────────────────

def _import_configure():
    """Import _configure_app_icon without running main()."""
    import importlib, types
    # main.py executes logging.basicConfig at import time; suppress it
    with patch('logging.basicConfig'), patch('logging.info'), patch('glob.glob', return_value=[]):
        import main as m
    return m._configure_app_icon


def test_configure_app_icon_sets_icon(tmp_path):
    """_configure_app_icon sets a non-null icon on the QApplication."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon

    app = QApplication.instance() or QApplication(sys.argv)

    fn = _import_configure()

    # Point BASE_DIR at a temp dir containing a copy of the real icon
    import main as m
    real_ico = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'assets', 'icon.ico')
    assets_dir = tmp_path / 'assets'
    assets_dir.mkdir()
    import shutil
    shutil.copy(real_ico, assets_dir / 'icon.ico')

    orig_base = m.BASE_DIR
    try:
        m.BASE_DIR = str(tmp_path)
        fn(app)
        assert not app.windowIcon().isNull()
    finally:
        m.BASE_DIR = orig_base


def test_configure_app_icon_missing_file_logs_warning(tmp_path, caplog):
    """_configure_app_icon logs a warning when icon.ico is absent."""
    import logging
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    import main as m
    orig_base = m.BASE_DIR
    try:
        m.BASE_DIR = str(tmp_path)   # no assets/icon.ico here
        with caplog.at_level(logging.WARNING, logger='root'):
            m._configure_app_icon(app)
        assert any('icon' in r.message.lower() for r in caplog.records)
    finally:
        m.BASE_DIR = orig_base


def test_configure_app_icon_missing_file_does_not_raise(tmp_path):
    """_configure_app_icon must not raise even when the icon file is absent."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    import main as m
    orig_base = m.BASE_DIR
    try:
        m.BASE_DIR = str(tmp_path)
        m._configure_app_icon(app)   # must not raise
    finally:
        m.BASE_DIR = orig_base


# ── _configure_app_style ──────────────────────────────────────────────────────
#
# Regression coverage for: BackOfficePro rendered in light mode on Windows
# but dark mode on Linux, because the app never forced a consistent Qt
# style — each OS fell back to its own native default ("windowsvista" on
# Windows, "Fusion" on most Linux setups), and the app's dark theme (applied
# via stylesheets, not a QPalette) doesn't survive that native Windows style
# consistently. Forcing Fusion everywhere fixes it.

def test_configure_app_style_sets_fusion():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    import main as m
    m._configure_app_style(app)

    assert app.style().objectName().lower() == "fusion"


def test_main_calls_configure_app_style(monkeypatch):
    """main() must apply the style before building any UI, so no window is
    ever shown with the native (non-Fusion) style first."""
    import main as m

    calls = []
    monkeypatch.setattr(m, "_configure_app_style", lambda app: calls.append("style"))
    monkeypatch.setattr(m, "_configure_app_icon", lambda app: calls.append("icon"))

    class _StopEarly(Exception):
        pass

    def _raise(*a, **kw):
        raise _StopEarly()

    monkeypatch.setattr(m, "_pick_store", _raise)
    monkeypatch.setattr(m, "_init_all_stores", _raise)

    import config.app_config as app_cfg
    monkeypatch.setattr(app_cfg, "get_merged_login", lambda: False)

    with pytest.raises(_StopEarly):
        m.main()

    assert calls[0] == "style"


# ── .desktop file ─────────────────────────────────────────────────────────────

_REPO_DESKTOP = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'assets', 'BackOfficePro.desktop',
)
_INSTALLED_DESKTOP = os.path.expanduser('~/.local/share/applications/BackOfficePro.desktop')


def test_repo_desktop_file_exists():
    assert os.path.isfile(_REPO_DESKTOP), f"assets/BackOfficePro.desktop not found in repo"


def test_repo_desktop_file_fields():
    content = open(_REPO_DESKTOP).read()
    assert 'Name=BackOfficePro' in content
    assert 'Icon=' in content
    assert 'Exec=' in content
    assert 'StartupWMClass=BackOfficePro' in content


@pytest.mark.skipif(
    not os.path.isfile(_INSTALLED_DESKTOP),
    reason=".desktop file not installed on this machine",
)
def test_installed_desktop_file_fields():
    content = open(_INSTALLED_DESKTOP).read()
    assert 'Name=BackOfficePro' in content
    assert 'Icon=' in content
    assert 'Exec=' in content
    assert 'StartupWMClass=BackOfficePro' in content
