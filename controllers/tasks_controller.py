"""Aggregates dated reminders from multiple domains into a single
'upcoming tasks' feed for the home screen — recurring supplier order days,
purchase orders approaching delivery, and RSA certs approaching expiry.

No dedicated tasks table: each item is derived live from its own domain's
data, so it naturally disappears once the underlying state changes (PO
received, cert renewed, order placed).
"""
from datetime import date, datetime

import models.supplier as supplier_model
import models.purchase_order as po_model
import models.user as user_model


def _parse_date(value):
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def _severity(due_date, today):
    if due_date < today:
        return "overdue"
    if due_date == today:
        return "today"
    return "soon"


def get_upcoming_tasks() -> list[dict]:
    today = date.today()
    tasks = []

    for supplier in supplier_model.get_order_due_today():
        tasks.append({
            "kind": "order_due",
            "icon": "🛒",
            "title": supplier["name"],
            "subtitle": "Order due today",
            "due_date": today,
            "ref_id": supplier["id"],
            "severity": "today",
        })

    for po in po_model.get_upcoming_deliveries():
        due_date = _parse_date(po["delivery_date"])
        tasks.append({
            "kind": "po_delivery",
            "icon": "📦",
            "title": f"PO {po['po_number']} — {po['supplier_name']}",
            "subtitle": f"Delivery due {due_date.strftime('%d %b %Y')}",
            "due_date": due_date,
            "ref_id": po["id"],
            "severity": _severity(due_date, today),
        })

    for user in user_model.get_expiring_rsa_certs():
        due_date = _parse_date(user["rsa_expiry_date"])
        tasks.append({
            "kind": "rsa_expiry",
            "icon": "🪪",
            "title": user["full_name"] or user["username"],
            "subtitle": f"RSA certificate expires {due_date.strftime('%d %b %Y')}",
            "due_date": due_date,
            "ref_id": user["id"],
            "severity": _severity(due_date, today),
        })

    tasks.sort(key=lambda t: t["due_date"])
    return tasks
