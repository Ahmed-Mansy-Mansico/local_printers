import base64

import frappe


@frappe.whitelist()
def send_si_details_on_submit(doc, method=None):
    """
    On Sales Invoice submit, render print format as PDF for each configured printer
    and broadcast ready-to-print payloads via Frappe realtime (Socket.IO).

    Each payload contains:
      - printer: printer system name
      - printer_ip: optional IP for network printers
      - is_cashier: whether this is the cashier receipt (full items)
      - pdf_base64: base64-encoded PDF content (ready to print)
      - invoice_name: the Sales Invoice name (for logging)
    """
    try:
        print_jobs = build_print_jobs(doc)
        if not print_jobs:
            frappe.log("No printer configurations found for this invoice.")
            return

        frappe.publish_realtime(
            event="sales_invoice_submitted",
            message=print_jobs,
            after_commit=True,
        )

        frappe.log(
            f"Sales Invoice {doc.name}: \
            sent {len(print_jobs)} - {print_jobs} print job(s) to subscribed clients."
        )

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Error in send_si_details_on_submit for {doc.name}",
        )


def build_print_jobs(doc):
    """
    For each Printer Item Group that matches the invoice's POS profile + items,
    render the configured Print Format as PDF and return a list of print jobs.
    """
    printer_configs = get_printer_settings(doc, doc.pos_profile)
    print_jobs = []

    for printer_name, config in printer_configs.items():
        meta = config["meta"]

        print_format_name = meta.get("print_format") or "Standard"
        no_letterhead = meta.get("no_letterhead", 0)

        # Generate PDF server-side (clean output, no toolbar / headers)
        pdf_content = frappe.get_print(
            doctype="Sales Invoice",
            name=doc.name,
            print_format=print_format_name,
            no_letterhead=no_letterhead,
            as_pdf=True,
            pdf_options={
                "margin-left": "0mm",
                "margin-right": "0mm",
                "margin-top": "0mm",
                "margin-bottom": "0mm",
            },
        )

        print_jobs.append(
            {
                "invoice_name": doc.name,
                "printer": meta.get("printer"),
                "printer_ip": meta.get("printer_ip"),
                "is_cashier": meta.get("is_cashier"),
                "print_format": print_format_name,
                "pdf_base64": base64.b64encode(pdf_content).decode("ascii"),
            }
        )

    return print_jobs


def get_printer_settings(invoice_doc, pos_profile):
    """
    Return a dict keyed by Printer Item Group name:
      {
        "PIG-xxx": {
          "meta": { printer, printer_ip, is_cashier, print_format, no_letterhead },
          "items": [ { item_code, ... }, ... ]
        }
      }
    """
    result = {}

    printers = frappe.get_all(
        "Printer Item Group",
        filters={"pos_profile": pos_profile},
        order_by="is_cashier desc",
    )

    for printer_ref in printers:
        printer_doc = frappe.get_doc("Printer Item Group", printer_ref.name)
        item_groups = {ig.item_group for ig in printer_doc.printer_item_group}

        for item in invoice_doc.items:
            item_group = frappe.db.get_value("Item", item.item_code, "item_group")

            if "All Item Groups" in item_groups or item_group in item_groups:
                if printer_doc.name not in result:
                    result[printer_doc.name] = {
                        "meta": {
                            "printer": printer_doc.printer,
                            "printer_ip": printer_doc.printer_ip,
                            "is_cashier": printer_doc.is_cashier,
                            "print_format": printer_doc.print_format,
                            "no_letterhead": printer_doc.no_letterhead,
                        },
                        "items": [],
                    }

                result[printer_doc.name]["items"].append({"item_code": item.item_code})

    return result


@frappe.whitelist()
def save_printers_data(printers):
    """Save printer names received from the Windows app."""
    if printers:
        for printer in printers:
            if not frappe.db.exists("Printer Name", {"name": printer}):
                doc = frappe.get_doc(
                    {"doctype": "Printer Name", "name": printer, "printer": printer}
                )
                doc.insert()
                frappe.db.commit()
