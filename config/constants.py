# Purchase order statuses
PO_STATUS_DRAFT     = 'DRAFT'
PO_STATUS_SENT      = 'SENT'
PO_STATUS_PARTIAL   = 'PARTIAL'
PO_STATUS_RECEIVED  = 'RECEIVED'
PO_STATUS_CANCELLED = 'CANCELLED'
PO_STATUS_REVERSED  = 'REVERSED'

PO_STATUSES = [
    PO_STATUS_DRAFT,
    PO_STATUS_SENT,
    PO_STATUS_PARTIAL,
    PO_STATUS_RECEIVED,
    PO_STATUS_CANCELLED,
    PO_STATUS_REVERSED,
]

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
