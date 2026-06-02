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


# ── .desktop file ─────────────────────────────────────────────────────────────

def test_desktop_file_exists():
    path = os.path.expanduser('~/.local/share/applications/BackOfficePro.desktop')
    assert os.path.isfile(path), ".desktop file not found"


def test_desktop_file_fields():
    path = os.path.expanduser('~/.local/share/applications/BackOfficePro.desktop')
    content = open(path).read()
    assert 'Name=BackOfficePro' in content
    assert 'Icon=' in content
    assert 'Exec=' in content
    assert 'StartupWMClass=BackOfficePro' in content


def test_desktop_file_icon_path_exists():
    path = os.path.expanduser('~/.local/share/applications/BackOfficePro.desktop')
    for line in open(path):
        if line.startswith('Icon='):
            icon_path = line.strip().split('=', 1)[1]
            assert os.path.isfile(icon_path), f"Desktop file Icon= path does not exist: {icon_path}"
