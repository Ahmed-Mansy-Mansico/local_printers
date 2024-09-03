# Copyright (c) 2024, mohammed hassan and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document



@frappe.whitelist(allow_guest=True)
def receive_url(url):
	new_get_printers = frappe.new_doc("Get Printers")
	new_get_printers.url = "url"
	new_get_printers.insert(ignore_permissions=True)
	frappe.db.commit()
	return new_get_printers.name

class GetPrinters(Document):
	pass
