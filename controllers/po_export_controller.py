"""PDF, email, and CSV export for purchase orders."""
import csv
import logging
import os

import models.po_lines as lines_model
import models.product as product_model
import models.purchase_order as po_model
import models.settings as settings_model
import models.stock_on_hand as stock_model
import models.supplier as supplier_model


def _po_pdf_path(po) -> str:
    """Return the full output path for a PO PDF, creating the directory if needed."""
    folder = (settings_model.get_setting('po_pdf_path') or '').strip()
    if not folder:
        folder = os.path.join(os.path.expanduser('~'), 'Documents', 'BackOfficePro', 'PurchaseOrders')
    os.makedirs(folder, exist_ok=True)
    filename = f"{po['po_number']}_{po['supplier_name'].replace(' ', '_')}.pdf"
    return os.path.join(folder, filename)


def generate_po_pdf_to_disk(po_id) -> str:
    """Generate the PO PDF to the configured folder. Return the full path."""
    from utils.po_pdf import generate_po_pdf
    po   = po_model.get_by_id(po_id)
    path = _po_pdf_path(po)
    generate_po_pdf(po_id, path)
    return path


def send_po_email(po_id, supplier_email) -> str:
    """Generate PDF, email to supplier, and mark PO as SENT. Return the PDF path."""
    from utils.email_graph import send_purchase_order
    from config.constants import PO_STATUS_SENT
    path = generate_po_pdf_to_disk(po_id)
    send_purchase_order(po_id=po_id, to_address=supplier_email, pdf_path=path)
    po_model.update_status(po_id, PO_STATUS_SENT)
    logging.info(f"PO {po_id} emailed to {supplier_email}, marked SENT")
    return path


def write_po_csv(po_id, output_path) -> None:
    """Write a CSV of PO lines to output_path."""
    po       = po_model.get_by_id(po_id)
    supplier = supplier_model.get_by_id(po['supplier_id']) if po['supplier_id'] else None
    sup_name  = po['supplier_name'] or ''
    sup_email = (supplier['email_orders'] or '') if supplier and supplier['email_orders'] else ''
    po_lines  = lines_model.get_by_po(po_id)

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Supplier', sup_name])
        writer.writerow(['Email', sup_email])
        writer.writerow(['PO Number', po['po_number']])
        writer.writerow(['Status', po['status']])
        writer.writerow([])
        writer.writerow(['Barcode', 'Description', 'Units per Carton', 'Total Units',
                         'SOH (Actual)', 'SOH (System)', 'Variance (Actual less System)'])
        for line in po_lines:
            if line['is_note']:
                writer.writerow(['', f'NOTE: {line["description"]}', '', '', '', '', ''])
                continue
            product   = product_model.get_by_barcode(line['barcode'])
            pack_qty  = int(product['pack_qty']) if product and product['pack_qty'] else 1
            pack_unit = (product['pack_unit'] or 'EA') if product else 'EA'
            soh       = stock_model.get_by_barcode(line['barcode'])
            on_hand   = int(soh['quantity']) if soh else 0
            total_units = int(line['ordered_qty']) * pack_qty
            writer.writerow([f'="{line["barcode"]}"', line['description'],
                             f'{pack_qty} x {pack_unit}', total_units, '', on_hand, ''])
