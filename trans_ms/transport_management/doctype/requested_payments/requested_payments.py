# Copyright (c) 2022, Aakvatech Limited and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
import time
import datetime
import json
from frappe.model.document import Document
from frappe.utils import flt, comma_or, nowdate
from frappe import msgprint, _
from erpnext.accounts.general_ledger import process_gl_map, save_entries
from erpnext.accounts.utils import (
    get_fiscal_years,
    validate_fiscal_year,
    get_account_currency,
)
from erpnext.controllers.accounts_controller import set_balance_in_account_currency
from erpnext.accounts.doctype.budget.budget import validate_expense_against_budget


class RequestedPayments(Document):
    def onload(self):
        pass

    def get_all_children(self, parenttype=None):
        # For getting children
        return self.get("payments_reference") or []

    def update_children(self):
        """update child tables"""
        self.update_child_table("payments_reference")

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

        for df in table_fields:
            # Load details for payments already paid
            if df.fieldname == "payments_reference":
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
            elif (
                df.fieldname == "requested_funds"
            ):  # Load requests which are not approved nor rejected
                children = frappe.db.get_values(
                    df.options,
                    {
                        "parent": ["=", self.get("reference_docname")],
                        "parenttype": ["=", self.get("reference_doctype")],
                        "parentfield": [
                            "in",
                            (
                                "requested_funds",
                                "main_requested_funds",
                                "return_requested_funds",
                            ),
                        ],
                        "request_status": [
                            "in",
                            ("open", "Requested", "Recommended", "Pre-Approved"),
                        ],
                    },
                    "*",
                    as_dict=True,
                    order_by="idx asc",
                )
                if children:
                    self.set(df.fieldname, children)
                else:
                    self.set(df.fieldname, [])
            elif df.fieldname == "accounts_approval":
                children = frappe.db.get_values(
                    "Requested Funds Details",
                    {
                        "parent": ["=", self.get("reference_docname")],
                        "parenttype": ["=", self.get("reference_doctype")],
                        "parentfield": [
                            "in",
                            (
                                "requested_funds",
                                "main_requested_funds",
                                "return_requested_funds",
                            ),
                        ],
                        "request_status": [
                            "in",
                            (
                                "Approved",
                                "Rejected",
                                "Accounts Approved",
                                "Accounts Rejected",
                                "Accounts Cancelled",
                            ),
                        ],
                    },
                    "*",
                    as_dict=True,
                    order_by="idx asc",
                )
                if children:
                    for child in children:
                        child.reference = child.name
                    self.set(df.fieldname, children)
                else:
                    self.set(df.fieldname, [])

        # sometimes __setup__ can depend on child values, hence calling again at the end
        if hasattr(self, "__setup__"):
            self.__setup__()


def get_outstanding_payments(self, account_currency):
    # Timestamp
    ts = time.time()

    # Initialize values
    total_amount = outstanding_amount = 0
    due_date = datetime.datetime.now().date()

    requested_from = frappe.get_doc(self.reference_doctype, self.reference_docname)
    if self.reference_doctype == "Vehicle Trip":
        for request in requested_from.main_requested_funds:
            if (
                request.request_status == "Approved"
                and request.request_currency == account_currency
            ):
                total_amount = total_amount + request.request_amount
                # request_date = datetime.datetime.strptime(request.request_date, '%Y-%m-%d')
                if request.request_date < due_date:
                    due_date = request.request_date

        for request in requested_from.return_requested_funds:
            if (
                request.request_status == "Approved"
                and request.request_currency == account_currency
            ):
                total_amount = total_amount + request.request_amount
                if request.request_date < due_date:
                    due_date = request.request_date
    else:
        for request in requested_from.requested_funds:
            if (
                request.request_status == "Approved"
                and request.request_currency == account_currency
            ):
                total_amount = total_amount + request.request_amount
                if request.request_date < due_date:
                    due_date = request.request_date

    paid_amount = frappe.db.sql(
        """SELECT (CASE WHEN SUM(debit_in_account_currency) > 0 THEN SUM(debit_in_account_currency) ELSE 0 END) AS paid_amount 
					FROM `tabGL Entry` WHERE debit_in_account_currency > 0 AND account_currency = %s 
						AND voucher_type = 'Requested Payments' AND voucher = %s""",
        (account_currency, self.name),
        as_dict=True,
    )
    # frappe.msgprint(paid_amount[0].paid_amount)
    outstanding_amount = total_amount - float(paid_amount[0].paid_amount)

    return frappe._dict(
        {
            "due_date": due_date,
            "total_amount": total_amount,
            "outstanding_amount": outstanding_amount,
            "exchange_rate": 1,
        }
    )


def validate_requested_funds(doc):
    make_request = False
    open_requests = []
    for requested_fund in doc.requested_funds:
        if requested_fund.request_status == "open":
            make_request = True
            open_requests.append(requested_fund)

    if make_request:
        args = {
            "reference_doctype": doc.doctype,
            "reference_docname": doc.name,
            "company": doc.company,
        }
        request_status = request_funds(
            reference_doctype=doc.doctype,
            reference_docname=doc.name,
            company=doc.company,
        )
        if request_status == "Request Inserted" or request_status == "Request Updated":
            for open_request in open_requests:
                open_request.set("request_status", "Requested")


@frappe.whitelist(allow_guest=True)
def request_funds(**args):
    args = frappe._dict(args)
    existing_payment_request = frappe.db.get_value(
        "Requested Payments",
        {
            "reference_doctype": args.reference_doctype,
            "reference_docname": args.reference_docname,
        },
    )

    # Timestamp
    ts = time.time()
    timestamp = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    if existing_payment_request:
        # Mark the request as open
        doc = frappe.get_doc("Requested Payments", existing_payment_request)
        doc.db_set("approval_status", "Waiting Approval")
        doc.db_set("modified", timestamp)
        doc.db_set("company", args.company)
        return "Request Updated"
    else:
        request = frappe.new_doc("Requested Payments")
        request.update(
            {
                "reference_doctype": args.reference_doctype,
                "reference_docname": args.reference_docname,
                "company": args.company,
                "customer": args.customer,
                "vehicle_no": args.vehicle_no,
                "driver": args.driver,
                "trip_route": args.trip_route,
                "approval_status": "Waiting Approval",
                "payment_status": "Waiting Approval",
            }
        )
        request.insert(ignore_permissions=True)
        return "Request Inserted"


@frappe.whitelist(allow_guest=True)
def recommend_request(**args):
    args = frappe._dict(args)

    # frappe.db.sql("UPDATE `tabRequested Funds Details` SET request_status = 'Recommended', request_hidden_status = 0 WHERE name = %s", args.request_docname)
    # return args.request_docname
    # Mark the request as open
    doc = frappe.get_doc("Requested Funds Details", args.request_docname)
    doc.db_set("request_status", "Recommended")
    doc.db_set("request_hidden_status", "0")
    doc.db_set("recommended_by", args.user)
    return "Request Updated"


@frappe.whitelist(allow_guest=True)
def recommend_against_request(**args):
    args = frappe._dict(args)

    # frappe.db.sql("UPDATE `tabRequested Funds Details` SET request_status = 'Recommended', request_hidden_status = 0 WHERE name = %s", args.request_docname)
    # return args.request_docname
    # Mark the request as open
    doc = frappe.get_doc("Requested Funds Details", args.request_docname)
    doc.db_set("request_status", "Recommended Against")
    doc.db_set("request_hidden_status", "0")
    doc.db_set("recommended_by", args.user)
    return "Request Updated"


@frappe.whitelist(allow_guest=True)
def approve_request(**args):
    args = frappe._dict(args)

    # frappe.db.sql("UPDATE `tabRequested Funds Details` SET request_status = 'Approved', request_hidden_status = 0 WHERE name = %s", args.request_docname)
    # return args.request_docname
    # Mark the request as open
    doc = frappe.get_doc("Requested Funds Details", args.request_docname)
    doc.db_set("request_status", "Approved")
    doc.db_set("request_hidden_status", "1")
    doc.db_set("approved_by", args.user)
    return "Request Updated"


@frappe.whitelist(allow_guest=True)
def reject_request(**args):
    args = frappe._dict(args)

    # frappe.db.sql("UPDATE `tabRequested Funds Details` SET request_status = 'Rejected', request_hidden_status = 0 WHERE name = %s", args.request_docname)
    # return "OK"
    # Mark the request as open
    doc = frappe.get_doc("Requested Funds Details", args.request_docname)
    doc.db_set("request_status", "Rejected")
    doc.db_set("request_hidden_status", "2")
    doc.db_set("approved_by", args.user)
    return "Request Updated"


@frappe.whitelist(allow_guest=True)
def accounts_approval(**args):
    args = frappe._dict(args)
    local = json.loads(args.local)

    if args.reference:
        reference = frappe.get_doc("Requested Funds Details", args.reference)
        if reference.request_status in ["Approved", "Accounts Cancelled"]:
            to_validate = [
                {"fieldname": "posting_date", "label": "Posting Date"},
                {"fieldname": "cost_center", "label": "Cost Center"},
                {"fieldname": "expense_account", "label": "Expense Account"},
                {"fieldname": "payable_account", "label": "Payable Account"},
                {"fieldname": "party_type", "label": "Party Type"},
                {"fieldname": "party", "label": "Party"},
            ]
            for field in to_validate:
                if not local.get(field["fieldname"]):
                    frappe.throw(
                        "Error: Please enter " + field["label"] + " for all rows"
                    )

            # Save changes made to accounts info
            to_save = [
                "expense_account",
                "payable_account",
                "party_type",
                "expense_type",
                "party",
                "invoice_number",
                "expense_account_currency",
                "conversion_rate",
                "payable_account_currency",
                "cost_center",
                "posting_date",
                "accounts_approved_by",
                "accounts_approved_on",
                "accounts_approver_comment",
            ]
            for field in to_save:
                reference.db_set(field, local.get(field))

            # Make GL Entries
            gl_entries = get_gl_entries(
                reference, args.parent_doctype, args.parent_docname
            )
            make_gl_entries(gl_entries)

            reference.db_set("request_status", "Accounts Approved")
            reference.db_set("request_hidden_status", "1")
            reference.db_set("accounts_approved_by", args.user)
            parent = frappe.get_doc("Requested Payments", args.parent_docname)
            update_payment_status(parent)
            return "Request Updated"


@frappe.whitelist(allow_guest=True)
def accounts_cancel(**args):
    args = frappe._dict(args)
    local = json.loads(args.local)

    if args.reference:
        reference = frappe.get_doc("Requested Funds Details", args.reference)

        if reference.request_status == "Accounts Approved":
            paid_amount = get_paid_amount(
                args.parent_doctype,
                args.parent_docname,
                reference.party_type,
                reference.party,
                reference.payable_account,
            )
            total_approved = get_total_approved(
                args.parent_doctype,
                args.parent_docname,
                reference.party_type,
                reference.party,
                reference.payable_account,
            )
            in_account_currency = reference.request_amount * reference.conversion_rate

            if (total_approved - (paid_amount + in_account_currency)) < 0:
                frappe.throw(
                    "Unable to cancel. Payment has already been made against the account. Please cancel the payment entry first."
                    + "Paid: "
                    + str(paid_amount)
                    + " Total Approved: "
                    + str(total_approved)
                    + " Account Currency: "
                    + str(in_account_currency)
                )
            else:
                # Make GL Entries
                gl_entries = get_gl_entries(
                    reference, args.parent_doctype, args.parent_docname
                )
                make_gl_entries(gl_entries, True)

                reference.db_set("request_status", "Accounts Cancelled")
                reference.db_set("request_hidden_status", "1")
                reference.db_set("accounts_approved_by", args.user)
                parent = frappe.get_doc("Requested Payments", args.parent_docname)
                update_payment_status(parent)
                return "Request Updated"


def get_paid_amount(dt, dn, party_type, party, account):
    if party_type == "Customer":
        dr_or_cr = "credit_in_account_currency - debit_in_account_currency"
    else:
        dr_or_cr = "debit_in_account_currency - credit_in_account_currency"

    paid_amount = frappe.db.sql(
        """
		select ifnull(sum({dr_or_cr}), 0) as paid_amount
		from `tabGL Entry`
		where against_voucher_type = %s
			and against_voucher = %s
			and party_type = %s
			and party = %s
			and account = %s
			and {dr_or_cr} > 0
	""".format(
            dr_or_cr=dr_or_cr
        ),
        (dt, dn, party_type, party, account),
    )

    return paid_amount[0][0] if paid_amount else 0


def get_total_approved(dt, dn, party_type, party, account):
    total_approved = frappe.db.sql(
        """
		select ifnull(sum(credit_in_account_currency), 0) as total_approved
		from `tabGL Entry`
		where against_voucher_type = %s
			and against_voucher = %s
			and party_type = %s
			and party = %s
			and account = %s
	""",
        (dt, dn, party_type, party, account),
    )

    return total_approved[0][0] if total_approved else 0


def get_gl_entries(data, reference_doctype, reference_docname):
    gl_entry = []
    doc = frappe.get_doc(reference_doctype, reference_docname)
    company_currency = frappe.db.get_value("Company", doc.company, "default_currency")

    # payable entry
    payable_account_currency = get_account_currency(data.payable_account)
    gl_entry.append(
        get_gl_dict(
            doc,
            data,
            {
                "account": data.payable_account,
                "credit": data.request_amount,
                "credit_in_account_currency": data.request_amount
                if payable_account_currency == company_currency
                else data.request_amount / data.conversion_rate,
                "against": data.name,
                "party_type": data.party_type,
                "party": data.party,
                "against_voucher_type": doc.doctype,
                "against_voucher": doc.name,
            },
        )
    )

    # expense entries
    expense_account_currency = get_account_currency(data.expense_account)
    gl_entry.append(
        get_gl_dict(
            doc,
            data,
            {
                "account": data.expense_account,
                "debit": data.request_amount,
                "debit_in_account_currency": data.request_amount
                if expense_account_currency == company_currency
                else data.request_amount / data.conversion_rate,
                "against": data.name,
                "cost_center": data.cost_center,
                "against_voucher_type": doc.doctype,
                "against_voucher": doc.name,
            },
        )
    )

    return gl_entry


def get_gl_dict(doc, data, args, account_currency=None):
    """this method populates the common properties of a gl entry record"""

    fiscal_years = get_fiscal_years(data.request_date, company=doc.company)
    if len(fiscal_years) > 1:
        frappe.throw(
            _(
                "Multiple fiscal years exist for the date {0}. Please set company in Fiscal Year"
            ).format(formatdate(self.posting_date))
        )
    else:
        fiscal_year = fiscal_years[0][0]

    gl_dict = frappe._dict(
        {
            "company": doc.company,
            "posting_date": data.posting_date,
            "fiscal_year": fiscal_year,
            "voucher_type": doc.doctype,
            "voucher_no": doc.name,
            "remarks": data.get("remarks"),
            "debit": 0,
            "credit": 0,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": 0,
            "is_opening": "No",
            "party_type": None,
            "party": None,
            "project": data.get("project"),
        }
    )
    gl_dict.update(args)

    company_currency = frappe.db.get_value("Company", doc.company, "default_currency")

    if not account_currency:
        account_currency = get_account_currency(gl_dict.account)

    if gl_dict.account and doc.doctype not in [
        "Journal Entry",
        "Period Closing Voucher",
        "Payment Entry",
    ]:

        # self.validate_account_currency(gl_dict.account, account_currency)
        set_balance_in_account_currency(
            gl_dict, account_currency, data.get("conversion_rate"), company_currency
        )

    return gl_dict


def make_gl_entries(
    gl_map,
    cancel=False,
    adv_adj=False,
    merge_entries=True,
    update_outstanding="Yes",
    from_repost=False,
):
    if gl_map:
        if not cancel:
            gl_map = process_gl_map(gl_map, merge_entries)
            if gl_map and len(gl_map) > 1:
                save_entries(gl_map, adv_adj, update_outstanding, from_repost)
            else:
                frappe.throw(
                    _(
                        "Incorrect number of General Ledger Entries found. You might have selected a wrong Account in the transaction."
                    )
                )
        else:
            delete_gl_entries(
                gl_map, adv_adj=adv_adj, update_outstanding=update_outstanding
            )


def delete_gl_entries(
    gl_entries=None,
    voucher_type=None,
    voucher_no=None,
    adv_adj=False,
    update_outstanding="Yes",
):

    from erpnext.accounts.doctype.gl_entry.gl_entry import (
        validate_balance_type,
        check_freezing_date,
        update_outstanding_amt,
        validate_frozen_account,
    )

    if not gl_entries:
        gl_entries = frappe.db.sql(
            """
			select account, posting_date, party_type, party, cost_center, fiscal_year,voucher_type,
			voucher_no, against_voucher_type, against_voucher, cost_center, company
			from `tabGL Entry`
			where voucher_type=%s and voucher_no=%s""",
            (voucher_type, voucher_no),
            as_dict=True,
        )

    if gl_entries:
        check_freezing_date(gl_entries[0]["posting_date"], adv_adj)

    for entry in gl_entries:
        frappe.db.sql(
            """delete from `tabGL Entry` where voucher_type=%s and voucher_no=%s AND against=%s""",
            (entry.voucher_type, entry.voucher_no, entry.against),
        )

        validate_frozen_account(entry["account"], adv_adj)
        validate_balance_type(entry["account"], adv_adj)
        if not adv_adj:
            validate_expense_against_budget(entry)

        if entry.get("against_voucher") and update_outstanding == "Yes" and not adv_adj:
            update_outstanding_amt(
                entry["account"],
                entry.get("party_type"),
                entry.get("party"),
                entry.get("against_voucher_type"),
                entry.get("against_voucher"),
                on_cancel=True,
            )


def update_payment_status(doc):
    paid_amount = frappe.db.sql(
        """select ifnull(sum(debit_in_account_currency), 0) as amt 
		from `tabGL Entry` where against_voucher_type = 'Requested Payments' and against_voucher = %s AND voucher_type <> 'Requested Payments'""",
        (doc.name),
        as_dict=1,
    )[0].amt

    total_approved = frappe.db.sql(
        """
		select ifnull(sum(credit_in_account_currency), 0) as total_approved
		from `tabGL Entry`
		where against_voucher_type = 'Requested Payments'
			and against_voucher = %s
	""",
        (doc.name),
        as_dict=1,
    )[0].total_approved

    if paid_amount >= total_approved:
        frappe.db.set_value("Requested Payments", doc.name, "payment_status", "Paid")
    else:
        frappe.db.set_value(
            "Requested Payments", doc.name, "payment_status", "Waiting Payment"
        )


@frappe.whitelist(allow_guest=True)
def reference_payment(**args):
    args = frappe._dict(args)

    request = frappe.new_doc("Reference Payment Table")
    request.update(
        {
            "parent": args.parent,
            "parentfield": args.parentfield,
            "parenttype": args.parenttype,
            "date_of_payment": args.date_of_payment,
            "accounting_system": args.accounting_system,
            "amount": args.amount,
            "currency": args.currency,
            "reference_no": args.reference_no,
            "status": "paid",
        }
    )
    request.insert(ignore_permissions=True)

    parent = frappe.get_doc("Requested Payments", args.parent)
    parent.db_set("payment_status", args.payment_status)
    return "inserted"


@frappe.whitelist(allow_guest=True)
def make_payment(source_name, target_doc=None, ignore_permissions=False):
    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = "Pay"
    pe.posting_date = nowdate()
    pe.mode_of_payment = "Cash"
    pe.party_type = "Employee"
    pe.allocate_payment_amount = 1

    return pe


@frappe.whitelist(allow_guest=True)
def approve_request(**args):
    args = frappe._dict(args)
    # Timestamp
    ts = time.time()
    timestamp = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    doc = frappe.get_doc("Requested Funds Details", args.request_docname)
    doc.db_set("request_status", "Approved")
    doc.db_set("approved_by", args.user)
    doc.db_set("approved_date", timestamp)
    return "Request Updated"


@frappe.whitelist(allow_guest=True)
def reject_request(**args):
    args = frappe._dict(args)
    # Timestamp
    ts = time.time()
    timestamp = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    doc = frappe.get_doc("Requested Funds Details", args.request_docname)
    doc.db_set("request_status", "Rejected")
    doc.db_set("approved_by", args.user)
    doc.db_set("approved_date", timestamp)
    return "Request Updated"
