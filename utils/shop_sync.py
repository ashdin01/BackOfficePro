"""Push Harcourt Cider catalogue changes to the online shop as they happen.

A background thread watches the Harcourt Cider database. When anything the
shop displays changes (price, name, Online Shop tick, group...), it builds a
small snapshot and POSTs it to the shop's /api/catalogue endpoint, so the
website shows the new price within a few seconds.

Only what the shop needs leaves this machine: online-shop products (name,
price, tax, weight, flags) and group names. Cost prices, suppliers, stock,
users etc. are never included.

Configuration - DATA_DIR/shop_sync.json (kept next to the databases):

    {"url": "https://<your-shop-domain>", "token": "<CATALOGUE_TOKEN>"}

Optional keys: "store_db" (default "harcourt_cider.db"), "poll_seconds" (5),
"settle_seconds" (3). Env vars SHOP_SYNC_URL / SHOP_SYNC_TOKEN override the
file. No file and no env vars = feature off.

Manual push (also the way to make the shop current after being offline):
    python -m utils.shop_sync --push        # push now
    python -m utils.shop_sync --dry-run     # build snapshot, don't send

If you add a column to the shop's queries (HarcourtCiderShop/app.py), add it
to _PRODUCT_COLUMNS and to catalogue.REQUIRED in the shop.
"""
import gzip
import hashlib
import json
import logging
import os
import sqlite3
import tempfile
import threading

log = logging.getLogger(__name__)

# Columns the shop reads from `products`, in snapshot order.
_PRODUCT_COLUMNS = (
    "barcode", "description", "brand", "sell_price", "tax_rate", "unit",
    "variable_weight", "weight_grams", "active", "online_available",
    "online_notes", "department_id", "group_id",
)

_SNAPSHOT_SCHEMA = """
CREATE TABLE product_groups (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE products (
    barcode TEXT PRIMARY KEY, description TEXT NOT NULL, brand TEXT DEFAULT '',
    sell_price REAL NOT NULL, tax_rate REAL DEFAULT 0, unit TEXT DEFAULT 'EA',
    variable_weight INTEGER DEFAULT 0, weight_grams INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1, online_available INTEGER DEFAULT 0,
    online_notes TEXT, department_id INTEGER, group_id INTEGER
);
"""


class SyncConfig:
    def __init__(self, url, token, db_path, poll=5.0, settle=3.0):
        self.url, self.token, self.db_path = url.rstrip("/"), token, db_path
        self.poll, self.settle = poll, settle


def load_config(data_dir: str | None = None, environ=None) -> "SyncConfig | None":
    """Resolve config from DATA_DIR/shop_sync.json + env overrides; None if off."""
    environ = os.environ if environ is None else environ
    if data_dir is None:
        import config.settings as _cfg
        data_dir = _cfg.DATA_DIR
    raw = {}
    path = os.path.join(data_dir, "shop_sync.json")
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            log.warning("shop_sync: could not read %s", path, exc_info=True)
            return None
    url = environ.get("SHOP_SYNC_URL") or raw.get("url") or ""
    token = environ.get("SHOP_SYNC_TOKEN") or raw.get("token") or ""
    if not (url and token):
        return None
    if not url.startswith("https://") and "localhost" not in url and "127.0.0.1" not in url:
        log.warning("shop_sync: refusing non-HTTPS url %r (token would travel in clear)", url)
        return None
    db_path = os.path.join(data_dir, raw.get("store_db", "harcourt_cider.db"))
    return SyncConfig(url, token, db_path,
                      float(raw.get("poll_seconds", 5)), float(raw.get("settle_seconds", 3)))


# ── Snapshot ─────────────────────────────────────────────────────────────────

def _shop_rows(db_path: str):
    """(products, groups) exactly as the shop needs them, from a read-only connection."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    try:
        cols = ", ".join(_PRODUCT_COLUMNS)
        products = conn.execute(
            f"SELECT {cols} FROM products WHERE online_available = 1 ORDER BY barcode"
        ).fetchall()
        groups = conn.execute("SELECT id, name FROM product_groups ORDER BY id").fetchall()
    finally:
        conn.close()
    return products, groups


def fingerprint(db_path: str) -> str:
    """Hash of everything that goes into the snapshot - changes iff the shop would."""
    products, groups = _shop_rows(db_path)
    return hashlib.sha256(json.dumps([products, groups], default=str).encode()).hexdigest()


def build_snapshot(db_path: str) -> tuple[bytes, int]:
    """Return (gzip-compressed SQLite snapshot, product count)."""
    products, groups = _shop_rows(db_path)
    fd, tmp = tempfile.mkstemp(suffix=".db", prefix="shop-snapshot-")
    os.close(fd)
    try:
        out = sqlite3.connect(tmp)
        try:
            out.execute("PRAGMA journal_mode = DELETE")  # single self-contained file
            out.executescript(_SNAPSHOT_SCHEMA)
            out.executemany("INSERT INTO product_groups VALUES (?, ?)", groups)
            out.executemany(
                f"INSERT INTO products ({', '.join(_PRODUCT_COLUMNS)}) "
                f"VALUES ({', '.join('?' * len(_PRODUCT_COLUMNS))})", products)
            out.commit()
        finally:
            out.close()
        with open(tmp, "rb") as f:
            return gzip.compress(f.read()), len(products)
    finally:
        os.remove(tmp)


# ── Network ──────────────────────────────────────────────────────────────────

def push(cfg: SyncConfig, payload: bytes, timeout: float = 90) -> dict:
    """POST the snapshot. Raises RuntimeError with the shop's message on failure."""
    import requests
    try:
        r = requests.post(cfg.url + "/api/catalogue", data=payload, timeout=timeout,
                          headers={"X-Catalogue-Token": cfg.token,
                                   "Content-Type": "application/gzip"})
    except requests.RequestException as e:
        raise RuntimeError(f"could not reach shop: {e}") from e
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code != 200 or not body.get("ok"):
        raise RuntimeError(f"shop rejected catalogue ({r.status_code}): "
                           f"{body.get('error') or r.text[:200]}")
    return body


def push_now(cfg: SyncConfig) -> dict:
    payload, n = build_snapshot(cfg.db_path)
    result = push(cfg, payload)
    log.info("shop_sync: pushed %d products (%d bytes)", n, len(payload))
    return result


# ── Watcher ──────────────────────────────────────────────────────────────────

class ShopSyncWatcher(threading.Thread):
    """Polls the fingerprint; pushes when it changes. No push at startup - the
    first reading is the baseline (use --push to force a full push)."""

    MAX_BACKOFF = 300.0

    def __init__(self, cfg: SyncConfig, push_fn=push_now, fingerprint_fn=fingerprint):
        super().__init__(daemon=True, name="shop-sync")
        self.cfg, self._push, self._fp = cfg, push_fn, fingerprint_fn
        self._stop_evt = threading.Event()
        self._last_pushed: str | None = None
        self._backoff = 0.0

    def stop(self):
        self._stop_evt.set()

    def check_once(self, settle: bool = True) -> str:
        """One poll. Returns 'baseline' | 'unchanged' | 'pushed' | 'failed'."""
        try:
            fp = self._fp(self.cfg.db_path)
        except sqlite3.Error:
            log.warning("shop_sync: could not read %s", self.cfg.db_path, exc_info=True)
            return "failed"
        if self._last_pushed is None:
            self._last_pushed = fp
            return "baseline"
        if fp == self._last_pushed:
            return "unchanged"
        if settle:  # let a burst of edits finish, then push the final state once
            self._stop_evt.wait(self.cfg.settle)
            try:
                fp = self._fp(self.cfg.db_path)
            except sqlite3.Error:
                return "failed"
        try:
            self._push(self.cfg)
        except Exception as e:  # noqa: BLE001 - network, shop or snapshot errors
            self._backoff = min(max(self._backoff * 2, 10.0), self.MAX_BACKOFF)
            log.warning("shop_sync: push failed (%s); retrying in %.0fs", e, self._backoff)
            return "failed"
        self._last_pushed, self._backoff = fp, 0.0
        return "pushed"

    def run(self):
        log.info("shop_sync: watching %s -> %s", self.cfg.db_path, self.cfg.url)
        while not self._stop_evt.is_set():
            try:
                self.check_once()
            except Exception:  # never let the watcher die
                log.exception("shop_sync: unexpected error")
            self._stop_evt.wait(max(self.cfg.poll, self._backoff))


def start_if_configured() -> "ShopSyncWatcher | None":
    try:
        cfg = load_config()
        if cfg is None:
            return None
        if not os.path.isfile(cfg.db_path):
            log.warning("shop_sync: %s not found; not starting", cfg.db_path)
            return None
        w = ShopSyncWatcher(cfg)
        w.start()
        return w
    except Exception:
        log.exception("shop_sync: failed to start (BackOfficePro continues normally)")
        return None


if __name__ == "__main__":
    import argparse
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Push the Harcourt Cider catalogue to the shop.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--push", action="store_true", help="build and push a snapshot now")
    g.add_argument("--dry-run", action="store_true", help="build a snapshot but don't send")
    args = ap.parse_args()
    c = load_config()
    if c is None:
        sys.exit("shop_sync is not configured: create DATA_DIR/shop_sync.json "
                 "with {\"url\": ..., \"token\": ...} (see module docstring).")
    if args.dry_run:
        data, n = build_snapshot(c.db_path)
        print(f"OK: would push {n} products, {len(data)} bytes, to {c.url}")
    else:
        print(push_now(c))
