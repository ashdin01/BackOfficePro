# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('assets',     'assets'),
        ('version.py', '.'),
        ('scripts',    'scripts'),
    ],
    hiddenimports=[
        # Flask API server — loaded in a daemon thread, not directly imported
        'api_server',
        'flask',
        'werkzeug',
        'werkzeug.serving',
        # Image handling
        'PIL',
        'PIL.Image',
        'PIL.ImageOps',
        # Reporting
        'reportlab',
        'reportlab.lib',
        'reportlab.lib.pagesizes',
        'reportlab.lib.units',
        'reportlab.lib.colors',
        'reportlab.lib.styles',
        'reportlab.lib.enums',
        'reportlab.platypus',
        'reportlab.pdfgen',
        # Microsoft auth (email backup)
        'msal',
        'msal.application',
        'requests',
        # OS keystore for secure credential storage
        'keyring',
        'keyring.backends',
        # Reports hub — all report screens are loaded via importlib.import_module,
        # so PyInstaller cannot detect them through static analysis.
        'controllers.report_controller',
        'views.reports.supplier_sales_report',
        'views.reports.gst_report',
        'views.reports.gp_report',
        'views.reports.stock_valuation',
        'views.reports.reorder_report',
        'views.reports.movement_history',
        'views.reports.writeoff_report',
        'views.reports.liquor_report',
        'views.products.plu_manager',
        'views.ar.aged_debtors',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Dev / test tools — never needed at runtime
        'pytest',
        'pytest_cov',
        'coverage',
        '_pytest',
        # Unused Qt subsystems (saves ~30 MB)
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebEngineCore',
        'PyQt6.Qt3DCore',
        'PyQt6.Qt3DRender',
        'PyQt6.QtBluetooth',
        'PyQt6.QtLocation',
        'PyQt6.QtMultimedia',
        'PyQt6.QtNfc',
        'PyQt6.QtSensors',
        'PyQt6.QtSerialPort',
        'PyQt6.QtCharts',
        # Unused stdlib heavyweights
        'tkinter',
        '_tkinter',
        'unittest',
        'xmlrpc',
        'distutils',
        'setuptools',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # binaries go in COLLECT, not the exe
    name='BackOfficePro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX causes antivirus false positives on Windows
    console=False,
    icon='assets/icon.ico',
)

# --onedir: instant launch, no temp-extraction on every run
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='BackOfficePro',
)
