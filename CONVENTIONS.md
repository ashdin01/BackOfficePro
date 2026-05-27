# BackOfficePro — Development Conventions

## Model function naming

| Purpose | Name |
|---|---|
| Create a top-level entity | `create(...)` → returns the new row `id` |
| Add a sub-item to a parent | `add(...)` → e.g. `po_lines.add()`, `ar_invoice.add_line()` |
| Update an existing record | `update(...)` |
| Soft-delete / deactivate | `deactivate(...)` |
| Hard-delete a record | `delete(...)` |
| Delete a sub-item | `delete_<item>(...)` → e.g. `delete_eligible()`, `delete_line()` |
| Fetch one by surrogate key | `get_by_id(id)` |
| Fetch one by natural key | `get_by_barcode(barcode)`, `get_by_code(code)` |
| Fetch all (optionally filtered) | `get_all(...)` |
| Fetch all for a parent | `get_by_<parent>(parent_id)` → e.g. `get_by_po(po_id)` |

### The `add` vs `create` rule in plain English

- **`create`** — the function *is* the thing. It allocates a row in a master table, increments a counter, and returns an id. You would say "create a supplier" or "create an invoice".
- **`add`** — the function attaches something to a parent that already exists. You would say "add a line to this PO" or "add an alias for this barcode".

Examples already in the codebase:

```python
# create — top-level entity
purchase_order.create(supplier_id, ...)   # → po_id
ar_invoice.create(invoice_number, ...)    # → invoice_id
product.create(barcode, ...)              # → (no return; barcode is the PK)
supplier.create(code, name, ...)

# add — sub-item attached to a parent
po_lines.add(po_id, barcode, ...)
ar_invoice.add_line(invoice_id, ...)
bundle.add_eligible(bundle_id, barcode, ...)
barcode_alias.add(alias_barcode, master_barcode)
```

## Controller function naming

Controller functions mirror model naming but may be more descriptive when the operation involves multiple models or business logic:

```python
# OK — descriptive compound names
product_controller.add_product(...)        # wraps product.create + soh init
ar_controller.create_invoice(...)          # wraps invoice.create + sequence
ar_controller.create_customer(...)         # wraps customer.create
ar_controller.add_invoice_line(...)        # wraps ar_invoice.add_line + totals
department_controller.create(...)          # thin wrapper
department_controller.create_group(...)    # thin wrapper
```

## Layer rules

```
views  →  controllers  →  models  →  database/connection
```

- **Views** import only `controllers.*`, `config.*`, `utils.*`, `views.base_view`.
- **Controllers** import only `models.*`, `config.*`, `utils.*`. No PyQt6, no `database.connection`.
- **Models** import only `database.connection.get_connection`, `config.*`. No cross-model imports.
- **`api_server.py`** imports only `controllers.*`.

## Model write pattern

Every function that calls `conn.commit()` must have an `except` that rolls back:

```python
def create(...):
    conn = get_connection()
    try:
        conn.execute("INSERT ...", (...))
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

Read-only functions use `try / finally` only (no rollback needed).

## View base classes

All views inherit from `views.base_view.BaseView` (QWidget subclass) or `BaseDialog` (QDialog subclass). Override `_load()` for data-fetch logic; call `self.load()` (not `self._load()`) from `__init__`, `showEvent`, and action handlers so failures are caught and shown via `show_error`.
