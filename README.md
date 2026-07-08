# BackOfficePro

A desktop back-office management system for independent supermarkets and grocery
stores — products, suppliers, purchase orders, stock levels, stocktakes,
accounts receivable, and reporting, all backed by a local SQLite database.
Built with PyQt6, with a Flask REST API alongside it for companion mobile apps
(RetailPOSPro for point-of-sale, StocktakeAppPro for Android barcode scanning).

For what the app does day-to-day, see the **[User Guide](USER_GUIDE.md)**.
For coding/architecture conventions, see **[CONVENTIONS.md](CONVENTIONS.md)**.

## Architecture

```
views  →  controllers  →  models  →  database/connection
```

- **`views/`** — PyQt6 UI. Never touches SQL directly; only imports `controllers.*`.
- **`controllers/`** — business logic. Thin wrappers around models, with validation
  and multi-model orchestration where needed.
- **`models/`** — all persistence. Every SQL statement in the app lives here.
- **`database/`** — connection pooling (`connection.py`) and the schema/migration
  system (`schema.py`, `migrations.py`).
- **`api_server.py`** — Flask REST API for RetailPOSPro and StocktakeAppPro,
  built entirely on `controllers.*` (no direct DB access).

See [CONVENTIONS.md](CONVENTIONS.md) for the full layering rules and naming
conventions (`create` vs `add`, controller signatures, etc.).

## Getting started

Requires Python 3.11+.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

A fresh SQLite database is created automatically in `data/` on first launch,
along with a prompt to set the Admin PIN.

To run the REST API standalone (used by RetailPOSPro / StocktakeAppPro):

```bash
./start_api.sh
```

### Multi-store setup

Additional stores are configured in `config/settings.py`:

```python
STORES = [
    {"name": "Little Red Apple", "db": "backoffice.db"},
    {"name": "Harcourt Cider",   "db": "harcourt_cider.db"},
]
```

A single entry skips the store picker entirely; each store gets its own
SQLite file under `data/`.

## Testing

```bash
python3 -m pytest tests/ -q
```

Coverage targets `models/`, `controllers/`, `database/`, `utils/`, and
`api_server.py` (see `pytest.ini` / `.coveragerc`) with a 65% CI floor —
in practice these layers sit close to 100%. The `views/` layer (PyQt6 UI)
is not included in the coverage gate; it's covered by a smaller set of
`pytest-qt` regression tests for specific screens rather than broad
coverage.

## Releases

1. Bump `VERSION` in `version.py`.
2. Commit with a `vX.Y.Z — summary` message.
3. Tag it: `git tag -a vX.Y.Z -m "..."` and push both the commit and tag.
4. Pushing a `v*` tag triggers `.github/workflows/build.yml`: tests run,
   then (if they pass) a Windows executable is built with PyInstaller and
   attached to a GitHub Release automatically.

No installation is required to run the built app — the release zip contains
a self-contained `BackOfficePro.exe`; a fresh database is created on first
launch next to the executable.

## Project layout

```
api_server.py        REST API for RetailPOSPro / StocktakeAppPro
main.py               Desktop app entry point
config/                Settings, constants, styling
controllers/            Business logic layer
models/                  All SQL / persistence
database/                Connection pooling, schema, migrations
views/                    PyQt6 UI
utils/                    Shared helpers (PDF generation, validators, TLS, secrets)
scripts/                  Standalone scripts (CSV import, Atria sales sync)
tests/                    pytest suite
```
