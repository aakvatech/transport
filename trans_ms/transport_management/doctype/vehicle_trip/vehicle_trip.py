# -*- coding: utf-8 -*-
# Copyright (c) 2015, Aakvatech Limited and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
from operator import mul
import frappe
import time
import datetime
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
import json
from frappe.utils import nowdate, cstr, cint, flt, comma_or, now
from frappe import _, msgprint
from trans_ms.utlis.dimension import set_dimension
from erpnext.setup.utils import get_exchange_rate
from trans_ms.transport_management.doctype.requested_payments.requested_payments import request_funds

class VehicleTrip(Document):
    # def before_insert(self):
    #     self.set_expenses()
    #     self.set_driver()

    def before_submit(self):
        self.validate_request_status()

    def on_submit(self):
        if self.transporter_type == "In House":
            if not self.stock_out_entry:
                frappe.throw(_("Stock Out Entry is not set"))

    def onload(self):

        if not self.company:
            self.company = frappe.defaults.get_user_default(
                "Company"
            ) or frappe.defaults.get_global_default("company")

    def before_insert(self):
        if self.transporter_type == "In House":
            self.set_expenses()
        elif self.transporter_type == "Sub-Contractor":
            self.main_requested_funds = []

    def validate(self):
        self.validate_fuel_requests()
        self.set_driver()
        self.set_permits()

    def set_expenses(self):
        reference_doc = frappe.get_doc(self.reference_doctype, self.reference_docname)
        self.main_route = reference_doc.route
        reference_route = frappe.get_doc("Trip Route", self.main_route)
        if len(reference_route.fixed_expenses) > 0:
            self.main_requested_funds = []
            for row in reference_route.fixed_expenses:
                fixed_expense_doc = frappe.get_doc("Fixed Expense", row.expense)
                aday = nowdate()
                new_row = self.append("main_requested_funds", {})
                new_row.request_date = aday
                new_row.request_amount = row.amount
                new_row.request_currency = row.currency
                new_row.request_status = "Pre-Approved"
                new_row.expense_type = row.expense
                new_row.expense_account = fixed_expense_doc.expense_account
                new_row.payable_account = fixed_expense_doc.cash_bank_account
                new_row.party_type = row.party_type
                if row.party_type == "Employee":
                    new_row.party = frappe.db.get_value(
                        "Driver", self.driver, "employee"
                    )

    def set_driver(self):
        employee = None
        if self.transporter_type == "In House":
            if not self.driver:
                frappe.throw("Driver is not set")
            employee = frappe.db.get_value("Driver", self.driver, "employee")
        elif self.transporter_type == "Sub-Contractor":
            if not self.driver_name:
                frappe.throw("Driver Name is not set")

        # frappe.throw("EMP" + str(employee))
        for row in self.main_requested_funds:
            if row.party_type == "Employee":
                if employee:
                    row.party = employee

    def set_permits(self):
        if self.main_cargo_category and not len(self.trip_permits):
            self.trip_permits = []
            cargo_category = frappe.get_doc(
                "Transport Cargo Type", self.main_cargo_category
            )
            for row in cargo_category.permits:
                new_row = self.append("trip_permits", {})
                new_row.permit_name = row.permit_name
                new_row.mandatory = row.mandatory

    def before_save(self):
        # validate_requested_funds(self)
        self.validate_main_route_inputs()

    def validate_fuel_requests(self):
        make_request = False

        # Check main trip
        for request in self.get("main_fuel_request"):
            if request.status == "Open":
                make_request = True


        if make_request:
            existing_fuel_request = frappe.db.get_value(
                "Fuel Request",
                {"reference_doctype": "Vehicle Trip", "reference_docname": self.name},
            )

            # Timestamp
            ts = time.time()
            timestamp = datetime.datetime.fromtimestamp(ts).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            if existing_fuel_request:
                doc = frappe.get_doc("Fuel Request", existing_fuel_request)
                doc.db_set("modified", timestamp)
                if "Fully Processed" == doc.status:
                    doc.db_set("status", "Partially Processed")
            else:
                fuel_request = frappe.new_doc("Fuel Request")
                fuel_request.update(
                    {
                        "vehicle_plate_number": self.get("vehicle_plate_number"),
                        "customer": self.get("customer"),
                        "vehicle": self.get("vehicle_plate_number"),
                        "driver": self.get("driver"),
                        "reference_doctype": "Vehicle Trip",
                        "reference_docname": self.name,
                        "status": "Waiting Approval",
                    }
                )
                fuel_request.insert(ignore_permissions=True)

            # Mark the requests as open
            for request in self.get("main_fuel_request"):
                if request.status == "Open":
                    request.set("status", "Requested")


    def validate_main_route_inputs(self):
        loading_date = None
        offloading_date = None

        steps = self.get("main_route_steps")
        for step in steps:
            if step.location_type == "Loading Point":
                loading_date = step.loading_date
            if step.location_type == "Offloading Point":
                offloading_date = step.offloading_date
        if offloading_date and not loading_date:
            frappe.throw("Loading Date must be set before Offloading Date")

    def validate_request_status(self):
        for row in self.main_fuel_request:
            if row.status not in  ["Rejected", "Approved"]:
                frappe.throw("<b>All fuel requests must be on either approved or rejected before submitting the trip</b>")
            
            if row.status == "Approved" and not row.purchase_order:
                frappe.throw("<b>All approved fuel requests must have Purchase Order before submitting the trip</b>")
        
        for row in self.main_requested_funds:
            if row.request_status not in  ["Rejected", "Approved"]:
                frappe.throw("<b>All fund requests must be on either approved or rejected before submitting the trip</b>")
            
            if row.request_status == "Approved" and not row.journal_entry:
                frappe.throw("<b>All approved fund requests must have a Journal Entry before submitting the trip</b>")

@frappe.whitelist(allow_guest=True)
def create_vehicle_trip(**args):
    args = frappe._dict(args)
    frappe.msgprint(str(args))
    existing_vehicle_trip = frappe.db.get_value(
        "Vehicle Trip",
        {
            "reference_doctype": args.reference_doctype,
            "reference_docname": args.reference_docname,
        },
    )

    if existing_vehicle_trip:
        # Mark the request as open and update modified time
        trip = frappe.get_doc("Vehicle Trip", existing_vehicle_trip)
        # doc.db_set("request_status", "open")
        # doc.db_set("modified", timestamp)
        
        # Update transport assignment
        doc = frappe.get_doc(args.reference_doctype, args.reference_docname)
        doc.created_trip = existing_vehicle_trip
        doc.status = "Processed"
        doc.save()
        return trip
    else:        
        cargo_details = frappe.get_doc("Cargo Details", args.cargo)
        trip = frappe.new_doc("Vehicle Trip")
        trip.update(
            {
                "reference_doctype": args.reference_doctype,
                "reference_docname": args.reference_docname,
                "status": "En Route",
                "hidden_status": 2,
                "main_cargo_location_country": cargo_details.cargo_location_country,
                "main_cargo_location_city": cargo_details.cargo_location_city,
                "main_cargo_destination_country": cargo_details.cargo_destination_country,
                "main_cargo_destination_city": cargo_details.cargo_destination_city,
                "main_cargo_category": cargo_details.cargo_type,
                "transporter_type": args.transporter_type,
                "vehicle": args.assigned_vehicle,
                "vehicle_plate_number": args.vehicle_plate_number,
                "trailer": args.assigned_trailer,
                "trailer_plate_number": args.trailer_plate_number,
                "customer": args.customer,
                "trip_route": args.trip_route,
                "driver": args.driver,
                "driver_name": args.driver_name,
                "invoice_number": args.invoice_number
            }
        )
        trip.insert(ignore_permissions=True, ignore_mandatory=True)



        # Update transport assignment
        doc = frappe.get_doc(args.reference_doctype, args.reference_docname)
        doc.created_trip = trip.name
        doc.status = "Processed"
        doc.save()
        
        # set funds request for In House Transporter
        if args.transporter_type == "In House":
            funds_args = {
                "reference_doctype": "Vehicle Trip",
                "reference_docname": trip.name,
                "customer": args.customer,
                "vehicle_no": args.vehicle,
                "driver": args.driver,
                "trip_route": args.trip_route
            }
            request_funds(**funds_args)
            
        # If company vehicle, update vehicle status
        if args.transporter == "In House":
            vehicle = frappe.get_doc("Vehicle", args.vehicle)
            vehicle.status = "In Trip"
            # vehicle.hidden_status = 2
            vehicle.trans_ms_current_trip = trip.name
            vehicle.save()
        return trip

@frappe.whitelist()
def make_vehicle_inspection(source_name, target_doc=None, ignore_permissions=False):

    docs = get_mapped_doc(
        "Vehicle Trip",
        source_name,
        {
            "Vehicle Trip": {
                "doctype": "Vehicle Inspection",
                "field_map": {
                    "driver_name": "driver_name",
                    "vehicle_plate_number": "vehicle_plate_number",
                    "name": "trip_reference",
                },
                "validation": {
                    "docstatus": ["=", 0],
                },
            }
        },
        target_doc,
        postprocess=None,
        ignore_permissions=ignore_permissions,
    )

    return docs


@frappe.whitelist(allow_guest=True)
def check_trip_status(**args):
    args = frappe._dict(args)
    frappe.msgprint("ok")

    existing_trip = frappe.db.get_value(
        "Vehicle Trip", {"main_file_number": args.file_number}
    )
    if existing_trip:
        doc = frappe.get_doc("Vehicle Trip", existing_trip)
        status = doc.status
        frappe.msgprint(status)
        if status != "Closed":
            frappe.msgprint(
                "Cannot Close the File because it's Trip is not closed,Please Create the Trip"
            )
        else:
            return status
    else:
        frappe.msgprint(
            "Cannot Close because Trip has not been created yet for the current file"
        )


"""@frappe.whitelist(allow_guest=True)
def validate_route_inputs(**args):
	args = frappe._dict(args)

	frappe.msgprint("OOOOOKKKK")

	#trip = frappe.db.get_value("Vehicle Trip", {"name": args.name})
	#docs = frappe.get_doc("Vehicle Trip", trip)
	#steps=docs.main_route_steps

	if args.offloading_date and not args.loading_date:
		frappe.msgprint("Loading Steps must be filled before offloading",raise_exeption==True)
"""


@frappe.whitelist()
def create_fund_jl(doc, row):
    doc = frappe.get_doc(json.loads(doc))
    row = frappe._dict(json.loads(row))
    if row.journal_entry:
        frappe.throw("Journal Entry Already Created")

    if row.request_status != "Approved":
        frappe.throw("Fund Request is not Approved")

    accounts = []
    company_currency = frappe.db.get_value(
        "Company",
        doc.company,
        "default_currency",
    )
    frappe.msgprint(company_currency)
    if company_currency != row.request_currency:
        multi_currency = 1
        exchange_rate = get_exchange_rate(row.request_currency, company_currency)
    else:
        multi_currency = 0
        exchange_rate = 1

    if row.request_currency != row.expense_account_currency:
        debit_amount = row.request_amount * exchange_rate
        debit_exchange_rate = exchange_rate
    else:
        debit_amount = row.request_amount
        debit_exchange_rate = 1

    if row.request_currency != row.payable_account_currency:
        credit_amt = row.request_amount * exchange_rate
        credit_exchange_rate = exchange_rate
    else:
        credit_amt = row.request_amount
        credit_exchange_rate = 1

    debit_row = dict(
        account=row.expense_account,
        exchange_rate=debit_exchange_rate,
        debit_in_account_currency=debit_amount,
        cost_center=row.cost_center,
    )
    accounts.append(debit_row)

    credit_row = dict(
        account=row.payable_account,
        exchange_rate=credit_exchange_rate,
        credit_in_account_currency=credit_amt,
        cost_center=row.cost_center,
    )
    accounts.append(credit_row)

    company = doc.company
    user_remark = "Vehicle Trip No: {0}".format(doc.name)
    if row.request_date:
        date = row.request_date
    else:
        date = nowdate()
        
    jv_doc = frappe.get_doc(
        dict(
            doctype="Journal Entry",
            posting_date=date,
            accounts=accounts,
            company=company,
            multi_currency=multi_currency,
            user_remark=user_remark,
        )
    )
    jv_doc.flags.ignore_permissions = True
    frappe.flags.ignore_account_permission = True
    set_dimension(doc, jv_doc)
    for account_row in jv_doc.accounts:
        set_dimension(doc, jv_doc, tr_child=account_row)
    jv_doc.save()
    jv_url = frappe.utils.get_url_to_form(jv_doc.doctype, jv_doc.name)
    si_msgprint = "Journal Entry Created <a href='{0}'>{1}</a>".format(
        jv_url, jv_doc.name
    )
    frappe.msgprint(_(si_msgprint))
    frappe.set_value(row.doctype, row.name, "journal_entry", jv_doc.name)
    return jv_doc


@frappe.whitelist()
def create_stock_out_entry(doc, fuel_stock_out):
    doc = frappe.get_doc(json.loads(doc))
    if doc.stock_out_entry:
        return frappe.get_doc("Stock Entry", doc.stock_out_entry)
    fuel_item = frappe.get_value("Transport Settings", None, "fuel_item")
    if not fuel_item:
        frappe.throw(_("Please Set Fuel Item in Transport Settings"))
    warehouse = frappe.get_value("Vehicle", doc.vehicle, "trans_ms_fuel_warehouse")
    if not warehouse:
        frappe.throw(_("Please Set Fuel Warehouse in Vehicle"))
    item = {"item_code": fuel_item, "qty": float(fuel_stock_out)}
    stock_entry_doc = frappe.get_doc(
        dict(
            doctype="Stock Entry",
            from_bom=0,
            posting_date=nowdate(),
            posting_time=now(),
            items=[item],
            stock_entry_type="Material Issue",
            purpose="Material Issue",
            from_warehouse=warehouse,
            # to_warehouse=dispatch_bay_wh,
            company=doc.company,
            remarks="Transfer for {0} in vehicle {1}".format(
                doc.driver_name,
                doc.vehicle,
            ),
        )
    )
    set_dimension(doc, stock_entry_doc)
    set_dimension(doc, stock_entry_doc, tr_child=stock_entry_doc.items[0])
    stock_entry_doc.insert(ignore_permissions=True)
    doc.stock_out_entry = stock_entry_doc.name
    doc.save()
    return stock_entry_doc


@frappe.whitelist()
def create_purchase_order(request_doc, item):
    # frappe.throw(request_doc)
    item = frappe._dict(json.loads(item))
    request_doc = frappe._dict(json.loads(request_doc))
    set_warehouse = frappe.get_value(
        "Vehicle", request_doc.vehicle_plate_number, "trans_ms_fuel_warehouse"
    )
    if not set_warehouse:
        frappe.throw(_("Fuel Stock Warehouse not set in Vehicle"))
    if item.purchase_order:
        frappe.throw(_("Purchase Order is already exists"))
    doc = frappe.new_doc("Purchase Order")
    doc.company = request_doc.company
    doc.department = item.supplier
    doc.supplier = item.supplier
    doc.currency = item.currency
    if item.transaction_date:
        doc.transaction_date = item.transaction_date
        doc.schedule_date = item.transaction_date
    else:
        doc.schedule_date = nowdate()
    # doc.docstatus = 1
    doc.set_warehouse = set_warehouse
    new_item = doc.append("items", {})
    new_item.item_code = item.item_code
    new_item.qty = item.quantity
    new_item.rate = item.cost_per_litre
    new_item.source_name = "fuel_request"
    set_dimension(request_doc, doc)
    set_dimension(request_doc, doc, tr_child=new_item)
    doc.insert(ignore_permissions=True)
    frappe.msgprint(_("Purchase Order {0} is created").format(doc.name))
    frappe.set_value(item.doctype, item.name, "purchase_order", doc.name)
    return doc.name
