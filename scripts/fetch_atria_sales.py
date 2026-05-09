"""
Atria POS — automated daily sales fetcher for BackOfficePro.

Logs into the Atria web interface, navigates to the PLU sales report,
downloads yesterday's CSV, and passes it straight into import_sales.py.

Usage (manual / test):
    python3 scripts/fetch_atria_sales.py

Scheduled (cron, runs every morning):
    0 7 * * * cd /home/ashley/BackOfficePro && python3 scripts/fetch_atria_sales.py

Dependencies:
    pip install requests beautifulsoup4
"""

import os
import sys
import tempfile
import logging
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

# ── Config ─────────────────────────────────────────────────────────────────────
ATRIA_BASE   = "http://192.168.1.107/ATRIA"
LOGIN_URL    = f"{ATRIA_BASE}/Account/Login"

# TODO: fill in your Atria login credentials
ATRIA_USER   = "your_username_here"
ATRIA_PASS   = "your_password_here"

# TODO: set the correct report URL and date parameters after inspecting
# the network traffic on the report page (see instructions below).
#
# REPORT_URL is the URL of the page or endpoint that returns (or lets you
# download) the PLU sales CSV.  Set REPORT_IS_DOWNLOAD = True if that URL
# returns the file directly; False if it returns an HTML page with a
# download link you need to click.
#
# Examples of what this might look like in Atria:
#   REPORT_URL = f"{ATRIA_BASE}/Reports/DailySales"
#   REPORT_URL = f"{ATRIA_BASE}/Reports/PLUSalesExport"
REPORT_URL        = f"{ATRIA_BASE}/REPLACE_WITH_REPORT_PATH"
REPORT_IS_DOWNLOAD = False   # set True if the URL itself serves the CSV file

# Date to fetch — defaults to yesterday.
TARGET_DATE = date.today() - timedelta(days=1)

# ── Helpers ────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)


def _get_token(session, url):
    """Fetch a page and extract the ASP.NET anti-forgery token."""
    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    token_input = soup.find("input", {"name": "__RequestVerificationToken"})
    if not token_input:
        raise RuntimeError(
            "Could not find __RequestVerificationToken on login page.\n"
            "Open DevTools → Network, log in manually, and check the POST payload\n"
            "to confirm the field name, then update this script."
        )
    return token_input["value"]


def login(session):
    """
    Log into Atria.  Returns True on success.

    ASP.NET MVC login flow:
      1. GET login page  → grab anti-forgery token
      2. POST credentials + token  → server sets auth cookie
    """
    log.info("Fetching login page …")
    token = _get_token(session, LOGIN_URL)

    # TODO: confirm the exact field names by right-clicking the login page
    # → View Page Source and finding the <form> tag.  Common names are
    # 'UserName'/'Password' or 'Email'/'Password'.
    payload = {
        "__RequestVerificationToken": token,
        "UserName": ATRIA_USER,          # ← change if field name differs
        "Password": ATRIA_PASS,
        "RememberMe": "false",
    }

    log.info("Posting credentials …")
    resp = session.post(LOGIN_URL, data=payload, timeout=15, allow_redirects=True)
    resp.raise_for_status()

    # A successful ASP.NET login redirects to the home page.
    # If we're still on /Account/Login after the POST, credentials were rejected.
    if "/Account/Login" in resp.url:
        raise RuntimeError(
            "Login failed — still on login page after POST.\n"
            "Check ATRIA_USER / ATRIA_PASS, or inspect the form field names."
        )

    log.info("Login successful (redirected to %s)", resp.url)
    return True


def _build_report_params():
    """
    Return the query-string / POST parameters needed to request yesterday's
    PLU sales report.

    TODO: navigate to the report manually, change the date to yesterday,
    click Generate / Export, then open DevTools → Network and look at the
    request that fetches (or downloads) the data.  Copy the parameters here.

    Example — replace with what you observe in DevTools:
        return {
            "ReportDate": TARGET_DATE.strftime("%d/%m/%Y"),
            "ExportFormat": "CSV",
        }
    """
    return {
        "ReportDate": TARGET_DATE.strftime("%d/%m/%Y"),
        # add more parameters as needed
    }


def fetch_csv(session):
    """
    Download the PLU sales CSV for TARGET_DATE.
    Returns the raw CSV bytes.
    """
    params = _build_report_params()
    log.info("Fetching report for %s …", TARGET_DATE.strftime("%d/%m/%Y"))

    if REPORT_IS_DOWNLOAD:
        # The URL returns the CSV file directly
        resp = session.get(REPORT_URL, params=params, timeout=30)
        resp.raise_for_status()
        return resp.content
    else:
        # The URL returns an HTML page — find the download link and follow it
        resp = session.get(REPORT_URL, params=params, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # TODO: inspect the report page HTML and update this selector to match
        # the Export / Download CSV link or button.
        # Examples:
        #   download_link = soup.find("a", string=lambda t: t and "Export" in t)
        #   download_link = soup.find("a", id="lnkExportCSV")
        #   download_link = soup.find("a", {"class": "export-link"})
        download_link = soup.find("a", string=lambda t: t and "CSV" in (t or ""))

        if not download_link:
            raise RuntimeError(
                "Could not find a CSV download link on the report page.\n"
                "Open the report page in a browser, right-click the Export/Download\n"
                "button → Inspect, and update the soup.find() call above to match."
            )

        href = download_link.get("href", "")
        if href.startswith("/"):
            href = f"http://192.168.1.107{href}"
        elif not href.startswith("http"):
            href = f"{ATRIA_BASE}/{href}"

        log.info("Following download link: %s", href)
        dl_resp = session.get(href, timeout=30)
        dl_resp.raise_for_status()
        return dl_resp.content


# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    # Add project root to path so import_sales can find database/ etc.
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    import import_sales  # local sibling script

    session = requests.Session()
    session.headers["User-Agent"] = "BackOfficePro/1.4 SalesFetcher"

    login(session)

    csv_bytes = fetch_csv(session)
    if not csv_bytes:
        raise RuntimeError("Downloaded file is empty — check report parameters.")

    log.info("Downloaded %d bytes", len(csv_bytes))

    # Write to a temp file and pass to the existing importer
    suffix = f"_atria_{TARGET_DATE.strftime('%Y%m%d')}.csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="wb") as tmp:
        tmp.write(csv_bytes)
        tmp_path = tmp.name

    log.info("Saved to temp file: %s", tmp_path)

    try:
        import_sales.ensure_tables()
        upserted, movements, unmatched = import_sales.import_csv(tmp_path)
        log.info("Import complete — %d rows, %d movements, %d unmatched PLUs",
                 upserted, movements, unmatched)
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        log.error("fetch_atria_sales failed: %s", exc, exc_info=True)
        sys.exit(1)
