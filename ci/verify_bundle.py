"""Fail the build if a dynamically-loaded screen is missing from the exe.

Usage: python ci/verify_bundle.py dist/BackOfficePro/BackOfficePro[.exe]
Checks every views/reports/*.py and views/settings/*.py is in the PYZ.
"""
import os
import sys

from PyInstaller.archive.readers import CArchiveReader

exe = sys.argv[1]
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ar = CArchiveReader(exe)
pyz_name = next(n for n in ar.toc if n.startswith("PYZ") and n.endswith(".pyz"))
bundled = set(ar.open_embedded_archive(pyz_name).toc)

missing = []
for pkg in ("reports", "settings"):
    d = os.path.join(root, "views", pkg)
    for f in sorted(os.listdir(d)):
        if f.endswith(".py") and f != "__init__.py":
            mod = f"views.{pkg}.{f[:-3]}"
            if mod not in bundled:
                missing.append(mod)

if missing:
    print("MISSING FROM BUNDLE:\n  " + "\n  ".join(missing))
    sys.exit(1)
print("Bundle check OK: all views.reports / views.settings modules present.")
