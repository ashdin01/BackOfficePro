# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('version.py', '.'), ('scripts', 'scripts')],
    hiddenimports=['pdfplumber', 'PIL', 'reportlab', 'reportlab.lib', 'reportlab.lib.pagesizes', 'reportlab.lib.units', 'reportlab.lib.colors', 'reportlab.lib.styles', 'reportlab.lib.enums', 'reportlab.platypus', 'reportlab.pdfgen'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BackOfficePro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='assets/icon.ico',
)
