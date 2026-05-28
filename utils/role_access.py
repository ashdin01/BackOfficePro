"""
Role-based access control helpers.

Screen indices match the order screens are built in MainWindow._build_ui():
  0  Home          4  Purchase Orders   8  Sales
  1  Products      5  Reports           9  Bundles
  2  Suppliers     6  Stocktake        10  A/Receivable
  3  Departments   7  Stock Adjust     11  Total Sales

STAFF may only view the four read-only / sales-facing screens.
Every other role (MANAGER, ADMIN) has full access.
"""

_STAFF_ALLOWED: frozenset[int] = frozenset({0, 1, 5, 8})


def user_can_access_screen(role: str, screen_index: int) -> bool:
    """Return True if *role* is permitted to navigate to *screen_index*."""
    if role in ("ADMIN", "MANAGER"):
        return True
    return screen_index in _STAFF_ALLOWED


def staff_allowed_screens() -> frozenset[int]:
    """Return the frozenset of screen indices visible to STAFF users."""
    return _STAFF_ALLOWED
