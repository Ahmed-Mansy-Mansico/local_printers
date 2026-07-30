import base64

import frappe
from frappe import _





@frappe.whitelist()
def send_doc_details_on_event(doc, method=None):
    """
    Render print format as PDF for each configured printer and broadcast
    ready-to-print payloads via Frappe realtime (Socket.IO).

    Each payload contains:
      - printer: printer system name
      - printer_ip: optional IP for network printers
      - is_cashier: whether this is the cashier receipt (full items)
      - pdf_base64: base64-encoded PDF content (ready to print)
      - document_name: document name (for logging)
    """
    # Guard against the wildcard ("*") doc_events hook firing on every doctype:
    # skip anything that can't possibly be POS-linked, and explicitly skip
    # "Error Log" so a failure here can never recursively re-trigger itself
    # via frappe.log_error() creating a new Error Log document.
    if doc.doctype == "Error Log" or not getattr(doc, "pos_profile", None):
        return

    trigger_method = method or "on_submit"

    try:
        print_jobs = build_print_jobs(doc, trigger_method)
        if not print_jobs:
            frappe.log(
                f"No printer configurations found for {doc.doctype} {doc.name} on {trigger_method}."
            )
            return

        frappe.publish_realtime(
            event="document_print_event",
            message={
                "doctype": doc.doctype,
                "document_name": doc.name,
                "method": trigger_method,
                "jobs": print_jobs,
            },
            after_commit=True,
        )

        # Backward compatibility for current Sales Invoice listeners.
        if doc.doctype == "Sales Invoice" and trigger_method == "on_submit":
            frappe.publish_realtime(
                event="sales_invoice_submitted",
                message=print_jobs,  # type: ignore[arg-type]
                after_commit=True,
            )

        frappe.log(
            f"{doc.doctype} {doc.name}: sent {len(print_jobs)} print job(s) for {trigger_method}."
        )

    except Exception:  # noqa: BLE001
        frappe.log_error(
            frappe.get_traceback(),
            f"Error in send_doc_details_on_event for {doc.doctype} {doc.name}",
        )


def send_si_details_on_submit(doc, method=None):
    """Compatibility wrapper for older hook path."""
    send_doc_details_on_event(doc, method=method)


def build_print_jobs(doc, trigger_method):
    """
    For each matching Printer Item Group, render the configured Print Format as
    PDF (scoped to that printer's routed items) and return a list of print jobs.
    """
    printer_configs = get_printer_settings(doc, trigger_method)
    print_jobs = []

    original_items = list(getattr(doc, "items", None) or []) or None

    try:
        for config in printer_configs.values():
            meta = config["meta"]

            print_format_name = meta.get("print_format") or "Standard"
            no_letterhead = meta.get("no_letterhead", 0)

            if original_items is not None:
                if meta.get("is_cashier"):
                    # Cashier receipt always gets every item on the document.
                    setattr(doc, "items", original_items)
                else:
                    matched_item_codes = {
                        item["item_code"] for item in config.get("items", [])
                    }
                    filtered_items = [
                        row for row in original_items if row.item_code in matched_item_codes
                    ]
                    setattr(doc, "items", filtered_items)

                    if not filtered_items:
                        # Nothing routed to this printer for this document - skip it.
                        continue

            # Generate PDF server-side (clean output, no toolbar / headers).
            # Pass `doc` explicitly so the print view renders this in-memory
            # (item-filtered) document instead of reloading the full one from the DB.
            pdf_content = frappe.get_print(
                doctype=doc.doctype,
                name=doc.name,
                print_format=print_format_name,
                no_letterhead=no_letterhead,
                doc=doc,
                as_pdf=True,
                pdf_options={
                    "margin-left": "0mm",
                    "margin-right": "0mm",
                    "margin-top": "0mm",
                    "margin-bottom": "0mm",
                },
            )

            if isinstance(pdf_content, (bytes, bytearray)):
                pdf_bytes = bytes(pdf_content)
            elif isinstance(pdf_content, str):
                pdf_bytes = pdf_content.encode("utf-8")
            else:
                pdf_bytes = str(pdf_content).encode("utf-8")

            print_jobs.append(
                {
                    "doctype": doc.doctype,
                    "document_name": doc.name,
                    "invoice_name": doc.name,
                    "printer": meta.get("printer"),
                    "printer_ip": meta.get("printer_ip"),
                    "is_cashier": meta.get("is_cashier"),
                    "print_format": print_format_name,
                    "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                }
            )
    finally:
        if original_items is not None:
            setattr(doc, "items", original_items)

    return print_jobs


def get_printer_settings(doc, trigger_method):
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

    if not getattr(doc, "pos_profile", None):
        return result

    printers = frappe.get_all(
        "Printer Item Group",
        filters={
            "pos_profile": doc.pos_profile,
            "target_doctype": doc.doctype,
            "trigger_method": trigger_method,
        },
        order_by="is_cashier desc",
    )

    doc_items = getattr(doc, "items", None)

    for printer_ref in printers:
        printer_doc = frappe.get_doc("Printer Item Group", printer_ref.name)
        printer_items = printer_doc.get("printer_item_group") or []
        item_groups = {
            ig.item_group for ig in printer_items if getattr(ig, "item_group", None)
        }

        if not doc_items:
            result[printer_doc.name] = {
                "meta": {
                    "printer": printer_doc.get("printer"),
                    "printer_ip": printer_doc.get("printer_ip"),
                    "is_cashier": printer_doc.get("is_cashier"),
                    "print_format": printer_doc.get("print_format"),
                    "no_letterhead": printer_doc.get("no_letterhead"),
                },
                "items": [],
            }
            continue

        for item in doc_items:
            item_group = frappe.db.get_value("Item", item.item_code, "item_group")
            if (
               "All Item Groups" in item_groups
                or item_group in item_groups
            ):
                if printer_doc.name not in result:
                    result[printer_doc.name] = {
                        "meta": {
                            "printer": printer_doc.get("printer"),
                            "printer_ip": printer_doc.get("printer_ip"),
                            "is_cashier": printer_doc.get("is_cashier"),
                            "print_format": printer_doc.get("print_format"),
                            "no_letterhead": printer_doc.get("no_letterhead"),
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
