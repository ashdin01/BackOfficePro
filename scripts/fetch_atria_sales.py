"""
ATRIA Daily PLU Sales report auto-downloader for BackOfficePro.

Logs into the ATRIA reporting system (Telerik/Progress report server under
the hood), requests yesterday's "DailyPluSales" report as CSV, saves it to
OUTPUT_DIR, then imports it into BackOfficePro (stock movements +
sales_daily) via import_sales.py.

Designed to be run once a day (e.g. via Windows Task Scheduler, early each
morning) to pull and apply the previous day's sales automatically, with no
manual step.

Credentials are stored in the OS keystore (Windows Credential Manager, via
utils/secret_store.py) rather than hardcoded. Set them once with:

    python scripts/fetch_atria_sales.py --set-credentials

--------------------------------------------------------------------------
ONE THING THAT ISN'T FULLY VERIFIED:
The captured browser traffic showed the *requests* sent to /api/rptsvr/...
but never the *response bodies* (Chrome's Network tab was only shared via
the Headers/Payload tabs, not Response). So the exact JSON key names the
server uses for "client id", "instance id" and "document id" in its
responses are inferred, not confirmed. The extract_id() helper below tries
several common key spellings and will raise a clear error showing the raw
response if none match -- if that happens on first run, open the printed
JSON, find the right key, and add it to the relevant candidates list.
--------------------------------------------------------------------------

Requires: pip install requests keyring
"""

import datetime
import getpass
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests

if getattr(sys, "frozen", False):
    _BASE = sys._MEIPASS
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from utils.secret_store import get_secret, set_secret
from database.connection import get_connection
import scripts.import_sales as import_sales

# ---------------- Configuration ----------------

BASE_URL = "http://192.168.1.107/ATRIA"

STORE_ID = 1  # matches the StoreId / AllowedStores value seen in captured traffic
REPORT_NAME = "DailyPluSales.trdx"

OUTPUT_DIR = Path.home() / "Downloads" / "ATRIA_Reports"
LOG_DIR = OUTPUT_DIR / "logs"

REQUEST_TIMEOUT = 30
DOWNLOAD_RETRY_ATTEMPTS = 8
DOWNLOAD_RETRY_DELAY_SECONDS = 2

_CRED_USER_KEY = "atria_username"
_CRED_PASS_KEY = "atria_password"

# -------------------------------------------------


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{datetime.date.today().isoformat()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def get_atria_credentials() -> tuple:
    """Read ATRIA credentials from the OS keystore, falling back to env vars."""
    username = get_secret(_CRED_USER_KEY) or os.environ.get("ATRIA_USERNAME", "")
    password = get_secret(_CRED_PASS_KEY) or os.environ.get("ATRIA_PASSWORD", "")
    if not username or not password:
        raise RuntimeError(
            "ATRIA credentials not set. Run:\n"
            "    python scripts/fetch_atria_sales.py --set-credentials\n"
            "or set the ATRIA_USERNAME / ATRIA_PASSWORD environment variables."
        )
    return username, password


def set_credentials_interactive() -> None:
    """One-time interactive setup: store ATRIA credentials in the OS keystore."""
    print("Storing ATRIA credentials in the OS keystore (Windows Credential Manager).")
    username = input("ATRIA username: ").strip()
    password = getpass.getpass("ATRIA password: ")
    set_secret(_CRED_USER_KEY, username)
    set_secret(_CRED_PASS_KEY, password)
    print("Saved. You can now run this script normally.")


def extract_id(data: dict, candidates: list) -> str:
    for key in candidates:
        if key in data:
            return data[key]
    raise KeyError(
        f"None of the expected keys {candidates} were found in response: {data}"
    )


def get_login_token(session: requests.Session) -> str:
    """GET the login page and pull the anti-forgery token out of the HTML."""
    resp = session.get(
        f"{BASE_URL}/Account/Login",
        params={"ReturnUrl": "/ATRIA/"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    match = re.search(
        r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', resp.text
    )
    if not match:
        raise RuntimeError(
            "Could not find __RequestVerificationToken on the login page. "
            "The login page HTML may have changed."
        )
    return match.group(1)


def login(session: requests.Session, username: str, password: str) -> None:
    logging.info("Logging in as %s", username)
    token = get_login_token(session)
    resp = session.post(
        f"{BASE_URL}/Account/Login",
        params={"ReturnUrl": "/ATRIA/"},
        data={
            "__RequestVerificationToken": token,
            "UserName": username,
            "Password": password,
            "RememberMe": "false",
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    if "Account/Login" in resp.url:
        raise RuntimeError(
            "Login appears to have failed - still on the login page after POST. "
            "Check the username/password (python scripts/fetch_atria_sales.py --set-credentials)."
        )
    logging.info("Login OK")


def create_client(session: requests.Session) -> str:
    resp = session.post(
        f"{BASE_URL}/api/rptsvr/clients",
        json={"timeStamp": int(time.time() * 1000)},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    client_id = extract_id(
        resp.json(), ["clientID", "ClientID", "clientId", "id", "Id"]
    )
    logging.info("Created report client %s", client_id)
    return client_id


def create_instance(session: requests.Session, client_id: str, target_date: datetime.date) -> str:
    date_str = f"{target_date.isoformat()}T00:00:00.000Z"
    payload = {
        "report": REPORT_NAME,
        "parameterValues": {
            "DateSelector": "Y",
            "FromDate": date_str,
            "ToDate": date_str,
            "StoreId": [STORE_ID],
            "SortBy": "plua",
            "FirstPluCode": 1,
            "LastPluCode": 999999,
            "AllowedStores": [STORE_ID],
        },
    }
    resp = session.post(
        f"{BASE_URL}/api/rptsvr/clients/{client_id}/instances",
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    instance_id = extract_id(
        resp.json(), ["instanceID", "InstanceID", "instanceId", "id", "Id"]
    )
    logging.info("Created report instance %s for %s", instance_id, target_date)
    return instance_id


def request_csv_document(session: requests.Session, client_id: str, instance_id: str) -> str:
    payload = {
        "format": "CSV",
        "deviceInfo": {
            "enableSearch": True,
            "BasePath": "/ATRIA/api/rptsvr",
        },
        "useCache": True,
    }
    resp = session.post(
        f"{BASE_URL}/api/rptsvr/clients/{client_id}/instances/{instance_id}/documents",
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    document_id = extract_id(
        resp.json(), ["documentID", "DocumentID", "documentId", "id", "Id"]
    )
    logging.info("Requested CSV document %s", document_id)
    return document_id


def download_document(
    session: requests.Session, client_id: str, instance_id: str, document_id: str
) -> bytes:
    url = (
        f"{BASE_URL}/api/rptsvr/clients/{client_id}/instances/{instance_id}"
        f"/documents/{document_id}"
    )
    last_error = None
    for attempt in range(1, DOWNLOAD_RETRY_ATTEMPTS + 1):
        try:
            resp = session.get(
                url,
                params={"response-content-disposition": "attachment"},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 200 and resp.content:
                logging.info("Downloaded document on attempt %d", attempt)
                return resp.content
            last_error = f"status={resp.status_code}, len={len(resp.content)}"
        except requests.RequestException as exc:
            last_error = str(exc)

        logging.info(
            "Document not ready yet (attempt %d/%d): %s",
            attempt,
            DOWNLOAD_RETRY_ATTEMPTS,
            last_error,
        )
        time.sleep(DOWNLOAD_RETRY_DELAY_SECONDS)

    raise RuntimeError(f"Gave up waiting for document after {DOWNLOAD_RETRY_ATTEMPTS} attempts: {last_error}")


# ── Import-log bookkeeping ────────────────────────────────────────────────────
#
# atria_import_log records every attempt, including zero-sale days (e.g. store
# closed), so the startup catch-up sync can tell "already checked" apart from
# "never attempted" and doesn't keep retrying closed days forever.

def _record_import_result(sale_date: str, row_count: int, status: str, error_message: str = '') -> None:
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO atria_import_log (sale_date, row_count, status, error_message)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(sale_date) DO UPDATE SET
                imported_at   = datetime('now', 'localtime'),
                row_count     = excluded.row_count,
                status        = excluded.status,
                error_message = excluded.error_message
        """, (sale_date, row_count, status, error_message))
        conn.commit()
    finally:
        conn.release()


def _missing_dates(days: int) -> list:
    """Return the past `days` calendar days (not including today) that have
    no atria_import_log entry yet, oldest first."""
    today = datetime.date.today()
    candidates = [today - datetime.timedelta(days=i) for i in range(1, days + 1)]

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT sale_date FROM atria_import_log WHERE sale_date >= ?",
            (min(candidates).isoformat(),)
        ).fetchall()
    finally:
        conn.release()

    done = {r['sale_date'] for r in rows}
    missing = [d for d in candidates if d.isoformat() not in done]
    missing.sort()
    return missing


def _fetch_and_import_one_day(session: requests.Session, target_date: datetime.date) -> int:
    """Download + import the ATRIA PLU sales report for a single date.

    Returns the number of sales_daily rows upserted. Raises on failure —
    callers are responsible for recording the outcome via _record_import_result.
    """
    client_id = create_client(session)
    instance_id = create_instance(session, client_id, target_date)
    document_id = request_csv_document(session, client_id, instance_id)
    content = download_document(session, client_id, instance_id, document_id)

    out_file = OUTPUT_DIR / f"DailyPluSales_{target_date.isoformat()}.csv"
    out_file.write_bytes(content)
    logging.info("Saved report to %s (%d bytes)", out_file, len(content))

    import_sales.ensure_tables()
    upserted, movements, unmatched = import_sales.import_csv(str(out_file))
    logging.info(
        "Import complete for %s — %d rows, %d movements, %d unmatched PLUs",
        target_date, upserted, movements, unmatched,
    )
    return upserted


def sync_missing_days(days: int = 7) -> dict:
    """Catch up any of the last `days` calendar days not yet recorded in
    atria_import_log, downloading and importing each one.

    Safe to call from a background thread: never raises. A missing-credential
    or login failure is logged once and skips the whole run; a failure on an
    individual day is logged and recorded, and the loop continues with the
    remaining days.

    Returns {"imported": [...dates], "failed": [...dates], "skipped_reason": str|None}.
    """
    setup_logging()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = {"imported": [], "failed": [], "skipped_reason": None}

    missing = _missing_dates(days)
    if not missing:
        logging.info("Atria sync: last %d days already accounted for", days)
        return result

    try:
        username, password = get_atria_credentials()
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) atria-auto-download/1.0",
            }
        )
        login(session, username, password)
    except Exception as exc:
        logging.warning("Atria sync skipped: %s", exc)
        result["skipped_reason"] = str(exc)
        return result

    for target_date in missing:
        try:
            row_count = _fetch_and_import_one_day(session, target_date)
            _record_import_result(target_date.isoformat(), row_count, "OK")
            result["imported"].append(target_date.isoformat())
        except Exception as exc:
            logging.exception("Atria sync: failed to import %s", target_date)
            _record_import_result(target_date.isoformat(), 0, "ERROR", str(exc))
            result["failed"].append(target_date.isoformat())

    return result


def main() -> int:
    setup_logging()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    yesterday = datetime.date.today() - datetime.timedelta(days=1)

    try:
        username, password = get_atria_credentials()

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) atria-auto-download/1.0",
            }
        )

        login(session, username, password)
        row_count = _fetch_and_import_one_day(session, yesterday)
        _record_import_result(yesterday.isoformat(), row_count, "OK")
        return 0

    except Exception as exc:
        logging.exception("Daily report download failed")
        _record_import_result(yesterday.isoformat(), 0, "ERROR", str(exc))
        return 1


if __name__ == "__main__":
    if "--set-credentials" in sys.argv:
        set_credentials_interactive()
        sys.exit(0)
    sys.exit(main())
