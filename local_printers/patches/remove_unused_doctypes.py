import frappe


def execute():
    """Remove unused doctypes: Allowed Domains, Get Printers, Available Printers."""
    doctypes_to_remove = ["Allowed Domains", "Get Printers", "Available Printers"]

    for dt in doctypes_to_remove:
        if frappe.db.exists("DocType", dt):
            # Delete all records first
            frappe.db.delete(dt)
            # Delete the DocType itself
            frappe.delete_doc("DocType", dt, force=True)
            frappe.db.commit()
            print(f"Removed DocType: {dt}")
        else:
            print(f"DocType {dt} does not exist, skipping.")
