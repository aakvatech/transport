# Copyright (c) 2021, Aakvatech Limited and contributors
# For license information, please see license.txt

# import frappe
from __future__ import unicode_literals
import frappe
import time
import datetime
from frappe.model.document import Document
from frappe import _
import json
from frappe.utils import nowdate
from trans_ms.utlis.dimension import set_dimension


class TransportationOrder(Document):
    def validate(self):
        if self.customer:
            currency = frappe.get_value("Customer", self.customer, "default_currency")
            if currency:
                for row in self.assign_transport:
                    row.currency = currency
        for row in self.assign_transport:
            if not row.assigned_vehicle:
                continue
            vehicle_status = frappe.get_value("Vehicle", row.assigned_vehicle, "status")
            if vehicle_status == "In Trip":
                existing_vehicle_trip = frappe.db.get_value(
                    "Vehicle Trip",
                    {
                        "reference_doctype": row.doctype,
                        "reference_docname": row.name,
                    },
                )
                if not existing_vehicle_trip:
                    frappe.throw(
                        _("Vehicle {0} is in trip").format(row.assigned_vehicle)
                    )

    def before_save(self):
        # For assignment status
        if not self.assign_transport:
            self.set("assignment_status", "Waiting Assignment")
        elif self.cargo_type == "Container":
            assigned_containers = []
            for row in self.assign_transport:
                assigned_containers.append(row.container_number)

            for row in self.cargo:
                if row.container_number not in assigned_containers:
                    self.set("assignment_status", "Partially Assigned")
                else:
                    self.set("assignment_status", "Fully Assigned")
        elif self.cargo_type == "Loose Cargo":
            total_assigned = 0
            for row in self.assign_transport:
                total_assigned = total_assigned + row.get("amount", 0)

            if self.amount > total_assigned:
                self.set("assignment_status", "Partially Assigned")
            else:
                self.set("assignment_status", "Fully Assigned")

    def get_all_children(self, parenttype=None):
        # If reference doctype is set
        if self.get("reference_docname"):
            return self.get("assign_transport")
        else:
            """Returns all children documents from **Table** type field in a list."""
            ret = []

            for df in self.meta.get("fields", {"fieldtype": "Table"}):
                if parenttype:
                    if df.options == parenttype:
                        return self.get(df.fieldname)
                value = self.get(df.fieldname)
                if isinstance(value, list):
                    ret.extend(value)
            return ret

    def update_children(self):
        # update child tables
        # If reference doctype is set
        if self.get("reference_docname"):
            self.update_child_table("assign_transport")
        else:
            for df in self.meta.get_table_fields():
                self.update_child_table(df.fieldname, df)

    '''def set_parent_in_children(self):
		"""Updates `parent` and `parenttype` property in all children."""
		#If reference doctype is set
		if self.get('reference_docname'):
			for d in self.get_all_children():
				d.parent = self.get('reference_docname')
				d.parenttype = self.get('reference_doctype')
				if self.get('reference_doctype') == "Import":
					d.parentfield = "assign_transport"
		else:
			for d in self.get_all_children():
				d.parent = self.name
				d.parenttype = self.doctype'''

    # Custom load method for loading child tables data from imports and exports request
    def load_from_db(self):
        """Load document and children from database and create properties
        from fields"""
        if not getattr(self, "_metaclass", False) and self.meta.issingle:
            single_doc = frappe.db.get_singles_dict(self.doctype)
            if not single_doc:
                single_doc = frappe.new_doc(self.doctype).as_dict()
                single_doc["name"] = self.doctype
                del single_doc["__islocal"]

            super(Document, self).__init__(single_doc)
            self.init_valid_columns()
            self._fix_numeric_types()

        else:
            d = frappe.db.get_value(self.doctype, self.name, "*", as_dict=1)
            if not d:
                frappe.throw(
                    _("{0} {1} not found").format(_(self.doctype), self.name),
                    frappe.DoesNotExistError,
                )

            super(Document, self).__init__(d)

        if self.name == "DocType" and self.doctype == "DocType":
            from frappe.model.meta import doctype_table_fields

            table_fields = doctype_table_fields
        else:
            table_fields = self.meta.get_table_fields()

        #
        # For table fields load from request origin(if there is) else load normal
        # Also add back compatibiilty for when transport assignements were being loaded from import
        #
        for df in table_fields:
            if d.reference_doctype and d.reference_docname:
                # Fieldname depending on if it's Export or Import
                if d.reference_doctype == "Import" and df.fieldname == "cargo":
                    fieldname = "cargo_information"
                elif (
                    d.reference_doctype == "Import"
                    and df.fieldname == "assign_transport"
                ):
                    fieldname = "assign_transport"

                if df.fieldname == "assign_transport" and self.get("version") == 2:
                    children = frappe.db.get_values(
                        df.options,
                        {
                            "parent": self.name,
                            "parenttype": self.doctype,
                            "parentfield": "assign_transport",
                        },
                        "*",
                        as_dict=True,
                        order_by="idx asc",
                    )
                else:
                    children = frappe.db.get_values(
                        df.options,
                        {
                            "parent": d.reference_docname,
                            "parenttype": d.reference_doctype,
                            "parentfield": fieldname,
                        },
                        "*",
                        as_dict=True,
                        order_by="idx asc",
                    )

                if children:
                    self.set(df.fieldname, children)
                else:
                    self.set(df.fieldname, [])
            else:
                children = frappe.db.get_values(
                    df.options,
                    {
                        "parent": self.name,
                        "parenttype": self.doctype,
                        "parentfield": df.fieldname,
                    },
                    "*",
                    as_dict=True,
                    order_by="idx asc",
                )
                if children:
                    self.set(df.fieldname, children)
                else:
                    self.set(df.fieldname, [])

        # sometimes __setup__ can depend on child values, hence calling again at the end
        if hasattr(self, "__setup__"):
            self.__setup__()


@frappe.whitelist(allow_guest=True)
def transport_order_scheduler():
    # Create requests for imports less than 10 days to eta
    for row in frappe.db.sql(
        """SELECT name, eta, reference_file_number FROM `tabImport` WHERE (status <> 'Closed' OR status IS NULL) AND `eta` < timestampadd(day, -10, now())""",
        as_dict=1,
    ):
        create_transport_order(
            reference_doctype="Import",
            reference_docname=row.name,
            file_number=row.reference_file_number,
        )


@frappe.whitelist(allow_guest=True)
def create_transport_order(**args):
    args = frappe._dict(args)

    existing_transport_order = frappe.db.get_value(
        "Transport Order", {"file_number": args.file_number}
    )

    # Timestamp
    ts = time.time()
    timestamp = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    if not existing_transport_order:
        request = frappe.new_doc("Transportion Order")
        request.update(
            {
                "reference_doctype": args.reference_doctype,
                "reference_docname": args.reference_docname,
                "file_number": args.file_number,
                "request_received": args.request_received,
                "customer": args.customer,
                "consignee": args.consignee,
                "shipper": args.shipper,
                "cargo_location_country": args.cargo_location_country,
                "cargo_location_city": args.cargo_location_city,
                "cargo_destination_country": args.cargo_destination_country,
                "cargo_destination_city": args.cargo_destination_city,
                "transport_type": args.transport_type,
                "version": 2,
            }
        )
        request.insert(ignore_permissions=True)
        return request.name
    else:
        return existing_transport_order


@frappe.whitelist(allow_guest=True)
def assign_vehicle(**args):
    args = frappe._dict(args)

    # Change cargo status to assigned (1)
    # doc = frappe.get_doc("Cargo Details", args.cargo_docname)
    # doc.db_set("transport_status", "0", False)
    # doc.db_set("idx", args.cargo_idx, False)

    # Add/Update assigned transport details
    existing_transport_details = frappe.db.get_value(
        "Transport Assignment", {"cargo": args.cargo_docname}
    )

    if existing_transport_details:
        # Update the transport details
        doc = frappe.get_doc("Transport Assignment", existing_transport_details)
        doc.assigned_vehicle = args.assigned_vehicle
        doc.assigned_trailer = args.assigned_trailer
        doc.assigned_driver = args.assigned_driver
        doc.cargo = args.cargo_docname
        doc.amount = args.amount
        doc.expected_loading_date = args.expected_loading_date
        doc.container_number = args.container_number
        doc.units = args.units
        doc.transporter_type = args.transporter_type
        doc.sub_contractor = args.sub_contractor
        doc.vehicle_plate_number = args.vehicle_plate_number
        doc.trailer_plate_number = args.trailer_plate_number
        doc.driver_name = args.driver_name
        doc.passport_number = args.passport_number
        doc.route = args.route
        doc.idx = args.assigned_idx
        doc.save()
    else:
        request = frappe.new_doc("Transport Assignment")
        request.update(
            {
                "cargo": args.cargo_docname,
                "amount": args.amount,
                "expected_loading_date": args.expected_loading_date,
                "container_number": args.container_number,
                "units": args.units,
                "transporter_type": args.transporter_type,
                "sub_contractor": args.sub_contractor,
                "vehicle_plate_number": args.vehicle_plate_number,
                "trailer_plate_number": args.trailer_plate_number,
                "driver_name": args.driver_name,
                "passport_number": args.passport_number,
                "route": args.route,
                "parent": args.reference_docname,
                "parenttype": args.reference_doctype,
                "parentfield": "assign_transport",
                "assigned_vehicle": args.assigned_vehicle,
                "assigned_trailer": args.assigned_trailer,
                "assigned_driver": args.assigned_driver,
                "idx": args.assigned_idx,
            }
        )
        request.insert(ignore_permissions=True)

    # Edit vehicle status

    """vehicle = frappe.get_doc("Vehicle", args.assigned_vehicle)
	if vehicle.status == 'Available':
		vehicle.status = "Booked"
		vehicle.save()"""
    return "success"


@frappe.whitelist()
def create_sales_invoice(doc, rows):
    doc = frappe.get_doc(json.loads(doc))
    rows = json.loads(rows)
    if not rows:
        return
    items = []
    item_row_per = []
    for row in rows:
        description = ""
        trip_info = None
        if row["transporter_type"] == "In House":
            description += "<b>VEHICLE NUMBER: " + row["assigned_vehicle"]
            trip_info = "<BR>TRIP: " + row["created_trip"]
        elif row["transporter_type"] == "Sub-Contractor":
            description += "<b>VEHICLE NUMBER: " + row["vehicle_plate_number"]
        if row["route"]:
            description += "<BR>ROUTE: " + row["route"]
        if trip_info:
            description += trip_info
        item = frappe._dict({
                "item_code": row["item"],
                "qty": 1,
                "uom": frappe.get_value("Item", row["item"], "stock_uom"),
                "rate": row["rate"],
                "description": description,
            }
        )
        item_row_per.append([row, item])
        items.append(item)
        
    invoice = frappe.get_doc(
        dict(
            doctype="Sales Invoice",
            customer=doc.customer,
            currency=row["currency"],
            posting_date=nowdate(),
            company=doc.company,
            items=items,
        ),
    )

    set_dimension(doc, invoice, src_child=row)
    invoice.items = []
    for i in item_row_per:
        set_dimension(doc, invoice, src_child=i[0], tr_child=i[1])
        invoice.append("items", i[1])
    
    frappe.flags.ignore_account_permission = True
    invoice.set_taxes()
    invoice.set_missing_values()
    invoice.flags.ignore_mandatory = True
    invoice.calculate_taxes_and_totals()
    invoice.insert(ignore_permissions=True)
    for item in doc.assign_transport:
        if item.name in [i["name"] for i in rows]:
            item.invoice = invoice.name
            if item.transporter_type == "In House":
                trip = frappe.get_doc("Vehicle Trip", item.created_trip)
                trip.invoice_number = invoice.name
                trip.save()
    doc.save()
           
        
    frappe.msgprint(_("Sales Inoice {0} Created").format(invoice.name), alert=True)
    return invoice
