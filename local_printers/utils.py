import re

import frappe
from frappe.utils import get_url


@frappe.whitelist()
def send_si_details_on_submit(doc, method=None):
    """
    On Sales Invoice submit, render print format HTML for each configured printer
    and broadcast ready-to-print payloads via Frappe realtime (Socket.IO).

    Each payload contains:
      - printer: printer system name
      - printer_ip: optional IP for network printers
      - is_cashier: whether this is the cashier receipt (full items)
      - html: fully rendered print-ready HTML (from the chosen Print Format)
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
            user=None,
        )

        frappe.log(
            f"Sales Invoice {doc.name}: sent {len(print_jobs)} print job(s) to subscribed clients."
        )

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Error in send_si_details_on_submit for {doc.name}",
        )


def build_print_jobs(doc):
    """
    For each Printer Item Group that matches the invoice's POS profile + items,
    render the configured Print Format into HTML and return a list of print jobs.
    """
    printer_configs = get_printer_settings(doc, doc.pos_profile)
    print_jobs = []

    for printer_name, config in printer_configs.items():
        meta = config["meta"]

        # Render the Print Format HTML server-side
        print_format_name = meta.get("print_format") or "Standard"
        no_letterhead = meta.get("no_letterhead", 0)

        html = frappe.get_print(
            doctype="Sales Invoice",
            name=doc.name,
            print_format=print_format_name,
            no_letterhead=no_letterhead,
        )

        html = make_urls_absolute(html)

        print_jobs.append(
            {
                "invoice_name": doc.name,
                "printer": meta.get("printer"),
                "printer_ip": meta.get("printer_ip"),
                "is_cashier": meta.get("is_cashier"),
                "print_format": print_format_name,
                "html": html,
            }
        )

    return print_jobs


def make_urls_absolute(html):
    """Convert relative URLs in HTML to absolute URLs so wkhtmltopdf can resolve them."""
    base_url = get_url()
    # Replace src="/...", href="/...", url('/...')
    html = re.sub(r'(src|href)=(["\'])/(?!/)', rf'\1=\2{base_url}/', html)
    html = re.sub(r"url\((['\"]?)/(?!/)", rf"url(\1{base_url}/", html)
    return html


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
