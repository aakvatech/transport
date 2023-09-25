# Copyright (c) 2021, Aakvatech Limited and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document
from telegram import Location


class TripRoute(Document):
    def validate(self):
        self.before_save()

    def before_save(self):
        for d in self.get("trip_steps"):
            if (
                d and d.idx == 1 and hasattr(d, 'location_type') 
                and d.location_type and d.location_type.lower() != "loading point"
            ):
                frappe.throw("Set 1st location type to LOADING POINT")
                break
            if (
                d == len(self.get("trip_steps")) and d.location_type 
                and d.location_type.lower() != "offloading point"
            ):
                frappe.throw("Set last location type to OFFLOADING POINT")
                break
