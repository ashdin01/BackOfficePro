# Purchase order statuses
PO_STATUS_DRAFT     = 'DRAFT'
PO_STATUS_SENT      = 'SENT'
PO_STATUS_PARTIAL   = 'PARTIAL'
PO_STATUS_RECEIVED  = 'RECEIVED'
PO_STATUS_CANCELLED = 'CANCELLED'
PO_STATUS_REVERSED  = 'REVERSED'
PO_STATUS_CLOSED    = 'CLOSED'   # Final status for Credit/Return orders

PO_STATUSES = [
    PO_STATUS_DRAFT,
    PO_STATUS_SENT,
    PO_STATUS_PARTIAL,
    PO_STATUS_RECEIVED,
    PO_STATUS_CANCELLED,
    PO_STATUS_REVERSED,
    PO_STATUS_CLOSED,
]

# Purchase order types
PO_TYPE_PO = 'PO'   # Normal purchase order
PO_TYPE_RO = 'RO'   # Credit / Return order
PO_TYPE_IO = 'IO'   # Invoice Only

PO_TYPES = {
    PO_TYPE_PO: 'Purchase Order',
    PO_TYPE_RO: 'Credit / Return',
    PO_TYPE_IO: 'Invoice Only',
}

PO_DOC_TITLES = {
    PO_TYPE_PO: 'PURCHASE ORDER',
    PO_TYPE_RO: 'CREDIT REQUEST',
    PO_TYPE_IO: 'INVOICE ONLY',
}

# PO receiving — additional charge types (freight, fuel levy, rounding, etc.)
PO_CHARGE_TYPE_FREIGHT   = 'FREIGHT'
PO_CHARGE_TYPE_FUEL_LEVY = 'FUEL_LEVY'
PO_CHARGE_TYPE_ROUNDING  = 'ROUNDING'   # only charge type allowed a negative amount
PO_CHARGE_TYPE_OTHER     = 'OTHER'

PO_CHARGE_TYPES = {
    PO_CHARGE_TYPE_FREIGHT:   'Freight',
    PO_CHARGE_TYPE_FUEL_LEVY: 'Fuel Levy',
    PO_CHARGE_TYPE_ROUNDING:  'Rounding',
    PO_CHARGE_TYPE_OTHER:     'Other',
}

# Stocktake statuses
STOCKTAKE_OPEN      = 'OPEN'
STOCKTAKE_CLOSED    = 'CLOSED'
STOCKTAKE_CANCELLED = 'CANCELLED'

# User roles
ROLE_ADMIN   = 'ADMIN'
ROLE_MANAGER = 'MANAGER'
ROLE_STAFF   = 'STAFF'

# Stock movement types — user-selectable (shown in dropdowns)
MOVE_RECEIPT        = 'RECEIPT'
MOVE_ADJUSTMENT_IN  = 'ADJUSTMENT_IN'
MOVE_RETURN         = 'RETURN'
MOVE_SALE           = 'SALE'
MOVE_WASTAGE        = 'WASTAGE'
MOVE_ADJUSTMENT_OUT = 'ADJUSTMENT_OUT'
MOVE_SHRINKAGE      = 'SHRINKAGE'

# Stock movement types — system-generated (not shown in dropdowns)
MOVE_REVERSAL  = 'REVERSAL'
MOVE_STOCKTAKE = 'STOCKTAKE'
MOVE_REVALUE   = 'REVALUE'

# Dropdown list for stock adjustment screens — must stay in sync with MOVE_* constants above
MOVE_TYPES = [
    MOVE_RECEIPT,
    MOVE_ADJUSTMENT_IN,
    MOVE_RETURN,
    MOVE_SALE,
    MOVE_WASTAGE,
    MOVE_ADJUSTMENT_OUT,
    MOVE_SHRINKAGE,
]

# Units
UNITS = ['EA', 'KG', 'L', 'PK', 'CTN', 'G', 'ML']

# Gross profit thresholds (percentage)
GP_WARN_THRESHOLD = 30.0   # at or above → good (green)
GP_BAD_THRESHOLD  = 15.0   # below this  → bad  (red); between → warning (orange)

# How far ahead the home-screen "Upcoming Tasks" panel looks — shared by RSA
# cert expiry (1 month notice) and approaching PO deliveries, so both stay in sync.
UPCOMING_TASKS_WINDOW_DAYS = 30
