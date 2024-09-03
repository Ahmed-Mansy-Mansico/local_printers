import frappe
from frappe.utils import cstr

@frappe.whitelist()
def send_si_details_on_submit(doc, method=None):
    """
    Send Sales Invoice details to all subscribed clients using Frappe Socket
    when the Sales Invoice is submitted.
    """
    try:
        # Extract necessary details from the Sales Invoice document
        printers = get_printer_settings(doc, doc.pos_profile)
        formatted_printers = format_printer_items(printers, doc)
        
        # Publish the invoice data to all connected clients
        frappe.publish_realtime(
            event="sales_invoice_submitted",
            message=formatted_printers,
            user=None
        )

        frappe.log("Sales Invoice details sent to subscribed clients.")
    
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"Error in send_si_details_on_submit: {str(e)}")



def format_printer_items(printers, doc):
    """
    Get a formatted response for Sales Invoices, ensuring the number of responses matches
    the number of printers, with the chosen items to be printed.
    """
    formatted_response = []

    for printer_name, items in printers.items():
        # Create a copy of the original document to avoid mutating the original `doc`
        cur_printer = frappe._dict(doc.as_dict())
        
        # Update the document with printer-specific information
        cur_printer.update({
            "printer_name": printer_name,
            "printer": items[0].get("printer"),
            "printer_ip": items[0].get("printer_ip"),
            "is_cashier": items[0].get("is_cashier"),
        })
        
        cur_printer["items"] = []  # Initialize the items list for the current printer

        # Filter and add relevant items for this printer
        for item in items:
            for row in doc.items:
                if item["item_code"] == row.item_code:
                    cur_printer["items"].append(frappe._dict(row.as_dict()))  # Ensure rows are added as dicts

        formatted_response.append(cur_printer)

    return formatted_response

    
def get_printer_settings(invoice_doc, pos_profile):
    """
    Retrieve and set printer settings based on the Sales Invoice document and POS profile.
    """
    item_printer_mapping = {}
    printers = frappe.get_all(
        "Printer Item Group", 
        filters={"pos_profile": pos_profile}, 
        order_by="is_cashier desc"
    )

    for printer_doc in printers:
        printer = frappe.get_doc("Printer Item Group", printer_doc.name)
        item_groups = {item_group.item_group for item_group in printer.printer_item_group}

        for item in invoice_doc.items:
            item_group = frappe.db.get_value("Item", item.item_code, "item_group")
            
            if "All Item Groups" in item_groups or item_group in item_groups:
                if printer.name not in item_printer_mapping:
                    item_printer_mapping[printer.name] = []

                item_printer_mapping[printer.name].append({
                    "name": printer.name,
                    "item_code": item.item_code,
                    "pos_profile": printer.pos_profile,
                    "company": printer.company,
                    "warehouse": printer.warehouse,
                    "printer": printer.printer,
                    "printer_ip": printer.printer_ip,
                    "is_cashier": printer.is_cashier,
                })

    return item_printer_mapping


@frappe.whitelist()
def save_printers_data(printers):
    if printers:
        for printer in printers:
            # Check if the printer already exists
            if not frappe.db.exists("Printer Name", {"name": printer}):
                # Create a new printer record
                doc = frappe.get_doc({
                    "doctype": "Printer Name",
                    "name": printer,
                    "printer": printer
                })
                doc.insert()
                frappe.db.commit()
