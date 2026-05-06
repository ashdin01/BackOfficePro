# BackOfficePro — User Guide

## Contents

1. [Overview](#overview)
2. [Getting Started](#getting-started)
3. [Navigating the App](#navigating-the-app)
4. [Home Dashboard](#home-dashboard)
5. [Products](#products)
6. [Suppliers](#suppliers)
7. [Departments](#departments)
8. [Purchase Orders](#purchase-orders)
9. [Reports](#reports)
10. [Stocktake](#stocktake)
11. [Stock Adjust](#stock-adjust)
12. [Settings](#settings)
13. [Backup & Restore](#backup--restore)
14. [User Roles & Permissions](#user-roles--permissions)
15. [Keyboard Reference](#keyboard-reference)

---

## Overview

BackOfficePro is a desktop back-office management system for supermarkets and grocery stores. It manages products, suppliers, departments, purchase orders, stock levels, stocktakes, sales data, and reporting — all stored in a local SQLite database.

---

## Getting Started

### First Launch

On first launch, the app will prompt you to create a 4-digit PIN for the **Admin** account before it opens. Choose a PIN you will remember — this is required every time you log in as Admin.

### Logging In

1. The login screen shows all active user accounts.
2. Click your name to select it (it will highlight blue).
3. Type your 4-digit PIN and press **Enter** or click **Login**.

**Lockout:** After 5 incorrect PIN attempts, the account is locked for 30 seconds. Wait for the countdown to expire before trying again.

---

## Navigating the App

The left sidebar lists all main sections. Click a button or use the keyboard shortcuts below (these work whenever focus is **not** inside a text field):

| Key | Section |
|-----|---------|
| `H` | Home |
| `P` | Products |
| `S` | Suppliers |
| `D` | Departments |
| `O` | Purchase Orders |
| `R` | Reports |
| `K` | Stocktake |
| `A` | Stock Adjust |
| `Esc` | Home |

The sidebar also shows your logged-in name and role, a **Lock** button to return to the login screen, backup controls, and a Settings button (Admin/Manager only).

---

## Home Dashboard

The Home screen gives a live snapshot of the store at a glance.

### Stat Cards

| Card | What it shows |
|------|--------------|
| **Today's Sales** | Total sales dollars imported for today |
| **Open Purchase Orders** | Count of POs with DRAFT or SENT status |
| **Low Stock Items** | Products at or below their reorder point |
| **Active Products** | Total active products in the database |

Cards refresh automatically every 60 seconds.

### Import Sales

The **Import Sales** button lets you load daily PLU sales files (CSV or PDF) exported from your POS system.

- Click **⬆ Import Sales** and select one or more files.
- A flashing amber asterisk (✱) appears next to the label when today's sales have not yet been imported.
- The status line shows the date of the last import and warns (in orange) if it is more than one day old.

### Quick Navigation

Buttons at the bottom of the Home screen jump directly to Products, Suppliers, Purchase Orders, and Reports. The keyboard shortcut for each section is shown in the button label (e.g. `[P]`, `[S]`).

---

## Products

**Access:** All roles.

The Products screen lists every product in the database with its barcode, PLU, description, brand, department, supplier, unit, sell price, cost price, stock on hand, and status.

### Searching

The search bar at the top filters by barcode, PLU, description, brand, supplier, or department as you type (500 ms debounce). Press `/` to jump back to the search bar at any time. Press **Enter** in the search bar to move focus to the table.

Press **Esc** in the search bar to clear the search and return to the Home screen.

### Show Inactive

Tick **Show Inactive** to include inactive products in the list. Inactive products that still have non-zero stock are always shown (highlighted orange) regardless of this setting.

### Colour Coding

| Colour | Meaning |
|--------|---------|
| Orange row | Inactive product with stock on hand — needs attention |
| Green barcode text | Temporary barcode (starts with `TEMP-`) — update when the real barcode is available |
| Green stock number | 4 or more units on hand |
| Orange stock number | 0–3 units on hand |
| Red stock number | Negative stock |

### Adding a Product

Click **Add Product** or press `N`. Fill in at minimum: barcode (or use the auto-generated TEMP barcode), description, department, sell price, and cost price. Save to add the product to the database.

### Editing a Product

Double-click any row (or select and press **Enter**) to open the edit form. All fields can be updated. Deactivating a product sets its status to INACTIVE; it will still appear if it has stock on hand.

### Exporting

Click **⬇ Export CSV** to save the currently visible product list to a CSV file.

---

## Suppliers

**Access:** Admin / Manager only.

Manage the suppliers your store orders stock from.

- **Add Supplier** — opens a form for name, contact details, and email address.
- **Edit Supplier** — double-click a row to edit.
- Suppliers are referenced in Products and Purchase Orders.

---

## Departments

**Access:** Admin / Manager only.

Departments group products for reporting and organisation. Each department can belong to a **Group** (a higher-level category).

- **Add / Edit Department** — name and assign to a group.
- **Add / Edit Group** — top-level category name.

---

## Purchase Orders

**Access:** Admin / Manager only.

### PO Statuses

| Status | Meaning |
|--------|---------|
| **DRAFT** | Created but not yet sent to supplier |
| **SENT** | Order sent to supplier, awaiting delivery |
| **PARTIAL** | Some items received, others still outstanding |
| **RECEIVED** | All items received (or PO closed) |
| **CANCELLED** | Order cancelled |

### Active Orders Tab

Shows all DRAFT, SENT, and PARTIAL purchase orders.

**Actions:**

| Button | Shortcut | What it does |
|--------|----------|-------------|
| ＋ New PO | `Ctrl+N` | Create a new purchase order |
| 📋 Open PO | `Ctrl+O` | Open/edit the selected PO |
| 📦 Receive PO | `Ctrl+R` | Record stock received against a SENT or PARTIAL PO |
| ✓ Close PO | — | Close a PARTIAL PO — marks remaining lines as not supplied |
| ✕ Cancel PO | — | Cancel a DRAFT or SENT PO |
| ✔ Update PO | `Ctrl+U` | Force a PARTIAL PO to RECEIVED (only available if at least one line has been received) |

Right-click any row for a context menu with the same options.

### Creating a Purchase Order

1. Click **＋ New PO**.
2. Select the supplier and set an expected delivery date.
3. Add product lines: search by barcode, PLU, or description; set the ordered quantity and cost price.
4. Save as **DRAFT**, or save and mark as **SENT** (which will email the PO to the supplier if email is configured).

### Receiving Stock

1. Select a SENT or PARTIAL PO and click **📦 Receive PO**.
2. For each line, enter the quantity actually received.
3. If all lines are fully received, the PO moves to RECEIVED and stock on hand is updated automatically.
4. If some lines are short-supplied, the PO moves to PARTIAL.

### Closing a Partial PO

If some lines will never arrive, select the PARTIAL PO and click **✓ Close PO**. You will be shown the outstanding lines and asked for a reason (e.g. "Out of stock", "Discontinued"). The PO is then marked RECEIVED with notes on the missing lines.

### Archive Tab

Shows all RECEIVED and CANCELLED POs. Use the filter dropdown to narrow by status. Double-click to view the PO history (read-only).

---

## Reports

**Access:** All roles.

The Reports screen is divided into tabs:

| Tab | Contents |
|-----|---------|
| **📈 Sales** | Daily/weekly/monthly sales totals from imported PLU data |
| **🧾 GST / BAS** | GST collected, suitable for BAS reporting |
| **⚠ Reorder** | Products at or below their reorder point |
| **💰 Stock Valuation** | Total stock value at cost and sell price |
| **📊 Gross Profit** | GP% by product or department |
| **📋 Movement History** | Stock movements (receipts, adjustments, write-offs) |
| **🏪 Supplier Sales** | Sales by supplier |
| **🗑 Write-Offs** | Stock written off (expired, damaged, etc.) |

Most reports have date-range filters and can be exported to CSV.

---

## Stocktake

**Access:** Admin / Manager only.

Stocktakes compare counted quantities against the system's stock on hand and produce a variance report.

### Creating a Session

1. Go to **Stocktake** and click **New Stocktake**.
2. Give the session a name (e.g. "Full stocktake April 2026") and save.
3. Open the session to start counting.

### Counting Stock

Within a session you can add counted quantities in three ways:

**Manual scan / entry**
- Type or scan a barcode into the scan bar and press **Enter**.
- Adjust the **Qty** spinner if counting more than 1 at a time.
- Each scan adds to the running total for that barcode.

**Import CSV**
- Click **📂 Import CSV** and select a file.
- Required columns: `barcode` (also accepts `ean`, `code`, or `upc`) and `qty` (also accepts `quantity`, `count`, or `counted`).
- Quantities are added to any counts already entered.

**Import SQLite**
- Click **🗄 Import SQLite** and select a `.db` or `.sqlite` file.
- The import will auto-detect tables containing barcode and quantity columns.

### Finalising a Stocktake

Once all counting is complete, click **Finalise**. The app will:
1. Compare counted quantities to the current stock on hand.
2. Show a **Variance Report** listing over/under counts for each product.
3. Give you the option to **Apply** the variances — this updates stock on hand to match the counted quantities.

---

## Stock Adjust

**Access:** Admin / Manager only. Staff cannot access this section.

Use Stock Adjust to manually correct individual product stock levels outside of a full stocktake. This is useful for one-off adjustments such as damaged goods or invoice corrections.

### Making an Adjustment

1. Search for a product by barcode, PLU, or description.
2. Select it from the results table.
3. Enter the adjustment quantity (positive to add stock, negative to remove).
4. Select a **reason code**:

| Code | Reason |
|------|--------|
| IS | Incorrectly Sold |
| NS | Not on Shelf |
| OD | Out of Date |
| IE | Invoice Error |
| SE | Stocktake Error |

5. Confirm the adjustment. The change is recorded in the movement history.

---

## Settings

**Access:** Admin / Manager only.

Open Settings from the **⚙ Settings** button in the sidebar.

### Store Details

| Field | Description |
|-------|-------------|
| Store Name | Displayed on the Home dashboard and on purchase orders |
| Store Manager | Name of the store manager |
| Address | Store street address |
| Phone | Contact phone number |
| ABN | Australian Business Number |

### Email Addresses

| Field | Description |
|-------|-------------|
| Accounts | Receives invoices from suppliers |
| Purchasing | Sends purchase orders to suppliers |
| Contact | General enquiries |

### PO PDF Folder

Override the default save location for purchase order PDFs. Leave blank to use `Documents/BackOfficePro/PurchaseOrders`.

### Microsoft Graph (Email)

BackOfficePro can send purchase orders and backup files by email via Microsoft 365. To enable this, enter the credentials from an Azure App Registration:

| Field | Description |
|-------|-------------|
| Client ID | Azure App Registration Client ID |
| Tenant ID | Azure Directory (Tenant) ID |
| Client Secret | Azure App Client Secret value |
| From Address | The Microsoft 365 address emails are sent from |

Contact your IT administrator or Microsoft 365 admin to obtain these values.

### Backup Email

Enter an email address to automatically receive a database backup every time the app is closed. Leave blank to disable email backups.

---

## Backup & Restore

Protecting your data is critical. BackOfficePro provides three layers of backup.

### Automatic Backup on Close

Every time you close the app, a backup is silently saved to `~/BackOfficeBackups/` (a folder in your home directory). The last 30 backups are kept; older ones are deleted automatically. If a backup email address is configured, the backup is also emailed.

### Manual Backup

Click **💾 Backup Data** in the sidebar at any time. A file-save dialog opens, defaulting to `~/BackOfficeBackups/` with a timestamped filename. Click Save to create the backup immediately.

The sidebar shows the date and time of the most recent backup.

### Restoring a Backup

Click **⟳ Restore Backup** in the sidebar.

1. Select the `.db` backup file to restore.
2. The app validates that the file is a valid BackOfficePro database.
3. You will be asked to confirm — the restore will **replace all current data**.
4. Before replacing, the current database is automatically backed up as a safety copy (named `supermarket_PRE_RESTORE_<timestamp>.db`).
5. After the restore completes, **restart the app** for changes to take effect.

> **Warning:** Restoring a backup overwrites all current data. Only restore if you are certain the backup file is correct.

---

## User Roles & Permissions

| Section | ADMIN / MANAGER | STAFF |
|---------|:--------------:|:-----:|
| Home | Yes | Yes |
| Products | Yes | Yes |
| Suppliers | Yes | No |
| Departments | Yes | No |
| Purchase Orders | Yes | No |
| Reports | Yes | Yes |
| Stocktake | Yes | No |
| Stock Adjust | Yes | No |
| Settings | Yes (Admin only) | No |
| Backup / Restore | Yes | Yes |

Disabled sections appear greyed out in the sidebar with the tooltip "Admin access required".

---

## Keyboard Reference

### Global (when not typing in a field)

| Key | Action |
|-----|--------|
| `H` | Go to Home |
| `P` | Go to Products |
| `S` | Go to Suppliers |
| `D` | Go to Departments |
| `O` | Go to Purchase Orders |
| `R` | Go to Reports |
| `K` | Go to Stocktake |
| `A` | Go to Stock Adjust |
| `Esc` | Go to Home |

### Products Screen

| Key | Action |
|-----|--------|
| `/` | Focus search bar |
| `N` | Add new product |
| `Esc` (in search) | Clear search, go to Home |
| Double-click row | Edit product |

### Purchase Orders Screen

| Key | Action |
|-----|--------|
| `Ctrl+N` | New purchase order |
| `Ctrl+O` | Open selected PO |
| `Ctrl+R` | Receive selected PO |
| `Ctrl+U` | Update PARTIAL PO to Received |
| `Enter` | Open selected PO |
