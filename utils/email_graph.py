"""
utils/email_graph.py
--------------------
Microsoft Graph API email utility for BackOfficePro.
Handles sending emails (with optional PDF attachments) via Microsoft 365.
Credentials are loaded from the settings table in the database.
Supports Purchase Orders now, and Reports in future.
"""

import base64
import logging
import mimetypes
import os

import msal
import requests


# ── Settings loader ───────────────────────────────────────────────────────────
def _load_graph_settings() -> dict:
    """Load Microsoft Graph credentials from the settings table."""
    from database.connection import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT key, value FROM settings WHERE key IN "
        "('graph_client_id','graph_tenant_id','graph_client_secret','graph_from_address')"
    ).fetchall()
    conn.close()
    return {r[0]: (r[1] or "").strip() for r in rows}


# ── Token acquisition ─────────────────────────────────────────────────────────
def _get_access_token(client_id: str, tenant_id: str, client_secret: str) -> str:
    """Obtain an OAuth2 access token using client credentials flow."""
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret,
    )
    result = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "Unknown error"))
        raise RuntimeError(f"Failed to obtain access token: {error}")
    return result["access_token"]


# ── Core send function ────────────────────────────────────────────────────────
def send_email(
    to_address: str,
    subject: str,
    body: str,
    attachment_path: str = None,
    cc_address: str = None,
    body_type: str = "Text",
) -> bool:
    """
    Send an email via Microsoft Graph API.

    Args:
        to_address:      Recipient email address.
        subject:         Email subject line.
        body:            Email body content.
        attachment_path: Optional full path to a file to attach (e.g. PDF).
        cc_address:      Optional CC email address.
        body_type:       "Text" or "HTML". Defaults to "Text".

    Returns:
        True on success, raises RuntimeError on failure.
    """
    settings = _load_graph_settings()

    client_id     = settings.get("graph_client_id", "")
    tenant_id     = settings.get("graph_tenant_id", "")
    client_secret = settings.get("graph_client_secret", "")
    from_address  = settings.get("graph_from_address", "")

    if not all([client_id, tenant_id, client_secret, from_address]):
        raise RuntimeError(
            "Microsoft Graph API credentials are not fully configured.\n"
            "Please complete the Email Configuration in Settings."
        )

    token = _get_access_token(client_id, tenant_id, client_secret)

    # ── Build message payload ─────────────────────────────────────────────────
    message = {
        "subject": subject,
        "body": {
            "contentType": body_type,
            "content": body,
        },
        "toRecipients": [
            {"emailAddress": {"address": to_address}}
        ],
    }

    if cc_address:
        message["ccRecipients"] = [
            {"emailAddress": {"address": cc_address}}
        ]

    # ── Attach file if provided ───────────────────────────────────────────────
    if attachment_path and os.path.isfile(attachment_path):
        with open(attachment_path, "rb") as f:
            file_data = f.read()
        encoded = base64.b64encode(file_data).decode("utf-8")
        filename = os.path.basename(attachment_path)
        content_type, _ = mimetypes.guess_type(attachment_path)
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": filename,
                "contentType": content_type or "application/octet-stream",
                "contentBytes": encoded,
            }
        ]

    # ── Send via Graph API ────────────────────────────────────────────────────
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # saveToSentItems=true ensures email appears in Sent folder
    response = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{from_address}/sendMail",
        headers=headers,
        json={
            "message": message,
            "saveToSentItems": True,
        },
        timeout=30,
    )

    if response.status_code == 202:
        logging.info(f"Email sent successfully to {to_address} | Subject: {subject}")
        return True
    else:
        error_detail = response.text or f"HTTP {response.status_code}"
        logging.error(f"Graph API send failed: {error_detail}")
        raise RuntimeError(f"Failed to send email (HTTP {response.status_code}):\n{error_detail}")


# ── Purchase Order helper ─────────────────────────────────────────────────────
def send_purchase_order(po_id: int, to_address: str, pdf_path: str) -> bool:
    """
    Send a Purchase Order PDF by email.

    Args:
        po_id:       The PO ID (used to build the subject line).
        to_address:  Supplier email address.
        pdf_path:    Full path to the exported PO PDF.

    Returns:
        True on success, raises RuntimeError on failure.
    """
    from database.connection import get_connection
    conn = get_connection()
    po = conn.execute(
        """SELECT po.po_number, s.name as supplier_name 
   FROM purchase_orders po
   JOIN suppliers s ON po.supplier_id = s.id
   WHERE po.id=?""", (po_id,)
    ).fetchone()
    settings_rows = conn.execute(
        "SELECT key, value FROM settings WHERE key IN ('store_name', 'store_manager')"
    ).fetchall()
    conn.close()
    settings = {r[0]: (r[1] or "").strip() for r in settings_rows}

    po_number     = po["po_number"] if po else f"PO-{po_id}"
    supplier      = po["supplier_name"] if po else "Supplier"
    store_name    = settings.get("store_name", "Our Store")
    store_manager = settings.get("store_manager", store_name)

    subject = f"Purchase Order {po_number} — {store_name}"
    body = (
        f"Dear {supplier},\n\n"
        f"Please find attached Purchase Order {po_number} from {store_name}.\n\n"
        f"Kind regards,\n{store_manager}\n{store_name}"
    )

    return send_email(
        to_address=to_address,
        subject=subject,
        body=body,
        attachment_path=pdf_path,
    )


# ── Backup helper ────────────────────────────────────────────────────────────
def send_backup(backup_path: str, to_address: str) -> bool:
    """
    Email a database backup file to to_address.

    Args:
        backup_path: Full path to the .db backup file.
        to_address:  Recipient email address.

    Returns:
        True on success, raises RuntimeError on failure.
    """
    from database.connection import get_connection
    from datetime import datetime as _dt
    conn = get_connection()
    store = conn.execute("SELECT value FROM settings WHERE key='store_name'").fetchone()
    conn.close()

    store_name = store["value"] if store else "BackOfficePro"
    ts = _dt.now().strftime("%d/%m/%Y %H:%M")
    filename = os.path.basename(backup_path)
    size_kb = os.path.getsize(backup_path) / 1024

    subject = f"BackOfficePro Backup — {store_name} — {ts}"
    body = (
        f"Automated database backup from {store_name}.\n\n"
        f"File:  {filename}\n"
        f"Size:  {size_kb:.1f} KB\n"
        f"Time:  {ts}\n\n"
        f"This backup was sent automatically on application close."
    )

    return send_email(
        to_address=to_address,
        subject=subject,
        body=body,
        attachment_path=backup_path,
    )


# ── Connection test ───────────────────────────────────────────────────────────
def test_graph_connection() -> tuple[bool, str]:
    """
    Test the Microsoft Graph API connection using saved credentials.

    Returns:
        (True, "Success message") or (False, "Error message")
    """
    try:
        settings = _load_graph_settings()
        client_id     = settings.get("graph_client_id", "")
        tenant_id     = settings.get("graph_tenant_id", "")
        client_secret = settings.get("graph_client_secret", "")
        from_address  = settings.get("graph_from_address", "")

        if not all([client_id, tenant_id, client_secret, from_address]):
            return False, "Please fill in all Microsoft Graph API fields before testing."

        _get_access_token(client_id, tenant_id, client_secret)
        return True, (
            "✓ Connection successful!\n"
            "Credentials are valid and ready to send emails."
        )
    except Exception as e:
        return False, str(e)
