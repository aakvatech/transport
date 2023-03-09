// Copyright (c) 2022, Aakvatech Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on('Requested Payments', {
	onload: function (frm) {
		// //Load the approve and reject buttons
		// var html = '<button style="background-color: green; color: #FFF;" class="btn btn-default btn-xs" onclick="cur_frm.cscript.approve_request(\'' + frm + '\');">Approve</button> ';
		// html += '<button style="background-color: red; color: #FFF;" class="btn btn-default btn-xs" onclick="cur_frm.cscript.reject_request(\'' + frm + '\');">Reject</button>';
		// $(frm.fields_dict.html1.wrapper).html(html);

		// //Load the recommend and recommend against buttons
		// var html2 = '<button style="background-color: green; color: #FFF;" class="btn btn-default btn-xs" onclick="cur_frm.cscript.recommend_request(\'' + frm + '\');">Recommend</button> ';
		// html2 += '<button style="background-color: red; color: #FFF;" class="btn btn-default btn-xs" onclick="cur_frm.cscript.recommend_against_request(\'' + frm + '\');">Recommend Against</button>';
		// $(frm.fields_dict.html2.wrapper).html(html2);

		//Load the approve and reject buttons
		var html = '<button style="background-color: green; color: #FFF;" class="btn btn-default btn-xs" onclick="cur_frm.cscript.approve_request(\'' + frm + '\');">Approve</button> ';
		html += '<button style="background-color: red; color: #FFF;" class="btn btn-default btn-xs" onclick="cur_frm.cscript.reject_request(\'' + frm + '\');">Reject</button>';
		$(frm.fields_dict.approve_buttons.wrapper).html(html);

		//Load the accounts approval buttons
		var html3 = '<button style="background-color: green; color: #FFF;" class="btn btn-default btn-xs" onclick="cur_frm.cscript.accounts_approval(\'' + frm + '\');">Approve</button> ';
		html3 += '<button style="background-color: red; color: #FFF;" class="btn btn-default btn-xs" onclick="cur_frm.cscript.accounts_cancel(\'' + frm + '\');">Cancel</button>';
		$(frm.fields_dict.html1.wrapper).html(html3);

		// //cur_frm.disable_save();
		// frappe.after_ajax(function () {
		// 	frm.events.show_hide_sections(frm);
		// });
	},

	refresh: function (frm) {
		// console.log(frm);

		// Hide delete buttons for Requested fuel Child Doctype
		$('*[data-fieldname="requested_funds"]').find('.grid-remove-rows').hide();
		$('*[data-fieldname="requested_funds"]').find('.grid-remove-all-rows').hide();
		$('*[data-fieldname="requested_funds"]').find('.grid-add-row').hide();

		//Beautify the previous approved table
		$(frm.wrapper).on("grid-row-render", function (e, grid_row) {
			if (grid_row.doc.request_status == "Approved") {
				$(grid_row.columns.request_status).css({ "font-weight": "bold", "color": "green" });
			}
			else if (grid_row.doc.request_status == "Rejected") {
				$(grid_row.columns.request_status).css({ "font-weight": "bold", "color": "red" });
			}
		});

		frappe.after_ajax(function () {
			frm.events.show_hide_sections(frm);
		});

		//For total requested
		var total_request_tsh = 0;
		var total_request_usd = 0;
		var all_approved = true;
		cur_frm.doc.requested_funds.forEach(function (row) {
			if (row.request_currency == 'TZS') {
				total_request_tsh += row.request_amount;
			}
			else if (row.request_currency == 'USD') {
				total_request_usd += row.request_amount;
			}
		});

		//If all requests have been processed, change approval status			
		if (total_request_tsh == 0 && total_request_usd == 0 && frm.doc.approval_status != "Processed") {
			frm.set_value('approval_status', 'Processed');
			frm.save_or_update();
		}

		cur_frm.get_field("request_total_amount").wrapper.innerHTML = '<p class="text-muted small">Total Amount Approved</p><b>USD ' + total_request_usd.toLocaleString() + ' <br> TZS ' + total_request_tsh.toLocaleString() + '</b>';


		//For total approved
		var total_approved_tsh = 0;
		var total_approved_usd = 0;
		/*cur_frm.doc.previous_requested_funds.forEach(function(row){
			if(row.request_status == "Approved" && row.request_currency == 'TZS')
			{
				total_approved_tsh += row.request_amount;
			}
			else if(row.request_status == "Approved" && row.request_currency == 'USD')
			{
				total_approved_usd += row.request_amount;
			}
		});
		
		cur_frm.get_field("total_approved_amount").wrapper.innerHTML = '<p class="text-muted small">Total Amount Approved</p><b>USD ' + total_approved_usd.toLocaleString() + ' <br> TZS ' + total_approved_tsh.toLocaleString() + '</b>'; */

		//For total paid amount
		var total_tsh = 0;
		var total_usd = 0;
		frm.doc.payments_reference.forEach(function (row) {
			if (row.currency == "TZS") {
				total_tsh += row.amount;
			}
			else if (row.currency == 'USD') {
				total_usd += row.amount;
			}
		});

		//For payment status (If all payments have been paid, payment status == 'Paid')
		if (total_usd > 0 && total_tsh > 0 && total_usd >= total_approved_usd && total_tsh >= total_approved_tsh && frm.doc.payment_status != "Paid") {
			frm.set_value('payment_status', "Paid");
			frm.save_or_update();
		}
		else if ((total_approved_tsh > total_tsh || total_approved_usd > total_usd) && frm.doc.payment_status != "Waiting Payment") {
			frm.set_value('payment_status', 'Waiting Payment');
			frm.save_or_update();
		}

		cur_frm.get_field("total_paid_amount").wrapper.innerHTML = '<p class="text-muted small">Total Amount Paid</p><b>USD ' + total_usd.toLocaleString() + ' <br> TZS ' + total_tsh.toLocaleString() + '</b>';

		//Make payment button
		frm.add_custom_button(__('Make Payment'),
			function () {
				frm.events.make_payment();
			}
		);

		frm.add_custom_button(__('Accounting Ledger'), function () {
			frappe.route_options = {
				voucher_no: frm.doc.name,
				company: frm.doc.company,
				group_by_voucher: false
			};
			frappe.set_route("query-report", "General Ledger");
		}, __("View"));

		let amount_tsh = 0
		let amount_usd = 0
		frm.doc.accounts_approval.forEach((d) => {
			if (d.request_currency == "TZS") {
				amount_tsh += d.request_amount;
			}
			else if (d.request_currency == 'USD') {
				amount_usd += d.request_amount;
			}
		});
		frm.get_field("total_amount").wrapper.innerHTML = '<p class="text-muted small">Total Amount</p><b>USD ' + amount_usd.toLocaleString() + ' <br> TZS ' + amount_tsh.toLocaleString() + '</b>';
	},

	make_payment: function () {
		frappe.model.open_mapped_doc({
			method: "trans_ms.transport_management.doctype.requested_payments.requested_payments.make_payment",
			frm: cur_frm
		});
	},

	validate_payment: function (frm) {
		var to_return = true;
		frm.doc.payments_reference.forEach(function (row) {
			if (row.amount <= 0 || !row.date_of_payment || row.date_of_payment == "" || !row.reference_no || row.reference_no == "" || !row.paid_to || row.paid_to == "" || row.payment_method == "" || row.payment_account == "") {
				to_return = false;
			}
		});
		return to_return;
	},

	show_hide_sections: function (frm) {
		frm.toggle_display(['request_total_amount', 'html1', 'html2'], (frm.doc.requested_funds.length > 0));
		//frm.toggle_display('section_previous_requested_funds', (frm.doc.previous_requested_funds.length > 0));
		//frm.toggle_display('section_payments_details', frm.doc.previous_requested_funds.length > 0);
		//frm.toggle_display('total_paid_amount', (frm.doc.previous_requested_funds.length > 0));
		//frm.toggle_display(['requested_funds', 'request_total_amount', 'section_previous_requested_funds', 'total_approved_amount', 'payments_reference', 'total_paid_amount'], true);
	},

	get_account_currency (frm, cdt, cdn, account) {
		if (account) {
			frappe.call({
				'method': 'frappe.client.get_value',
				'args': {
					'doctype': 'Account',
					'filters': {
						'name': account
					},
					'fieldname': 'account_currency'
				},
				'callback': function (res) {
					return res.message.account_currency;
				}
			});
		}
	}
});

frappe.ui.form.on('Requested Funds Details', {

	form_render (frm, cdt, cdn) {
		frm.fields_dict.requested_funds.grid.wrapper.find('.grid-delete-row').hide();
		frm.fields_dict.requested_funds.grid.wrapper.find('.grid-duplicate-row').hide();
		frm.fields_dict.requested_funds.grid.wrapper.find('.grid-move-row').hide();
		frm.fields_dict.requested_funds.grid.wrapper.find('.grid-append-row').hide();
		frm.fields_dict.requested_funds.grid.wrapper.find('.grid-insert-row-below').hide();
		frm.fields_dict.requested_funds.grid.wrapper.find('.grid-insert-row').hide();
	},
});
frappe.ui.form.on('Requested Funds Accounts Table', {
	form_render: function (frm, cdt, cdn) {
		frappe.call({
			'method': 'frappe.client.get_value',
			'args': {
				'doctype': 'Company',
				'filters': {
					name: frm.doc.company
				},
				'fieldname': 'cost_center'
			},
			'callback': function (r) {
				frappe.model.set_value(cdt, cdn, 'cost_center', r.message.cost_center);
			}
		});

		if (!locals[cdt][cdn].posting_date) {
			frappe.model.set_value(cdt, cdn, 'posting_date', frappe.datetime.get_today());
		}

		if (locals[cdt][cdn].conversion_rate == 0) {
			frappe.model.set_value(cdt, cdn, 'conversion_rate', 1);
		}
	},

	expense_type: function (frm, cdt, cdn) {
		frappe.call({
			method: "erpnext.hr.doctype.expense_claim.expense_claim.get_expense_claim_account",
			args: {
				"expense_claim_type": locals[cdt][cdn].expense_type,
				"company": frm.doc.company
			},
			callback: function (r) {
				if (r.message) {
					locals[cdt][cdn].expense_account = r.message.account;
					if (r.message.account) {
						frappe.model.set_value(cdt, cdn, 'expense_account_currency', frm.events.get_account_currency(frm, cdt, cdn, r.message.account));
					}
				}
			}
		});
	},

	expense_account: function (frm, cdt, cdn) {
		if (locals[cdt][cdn].expense_account) {
			var expense_account_currency = frm.events.get_account_currency(frm, cdt, cdn, locals[cdt][cdn].expense_account);
			if (expense_account_currency) {
				frappe.model.set_value(cdt, cdn, 'expense_account_currency', expense_account_currency);
			}
		}
	},

	payable_account: function (frm, cdt, cdn) {
		if (locals[cdt][cdn].payable_account) {
			var payable_account_currency = frm.events.get_account_currency(frm, cdt, cdn, locals[cdt][cdn].payable_account);
			if (payable_account_currency) {
				frappe.model.set_value(cdt, cdn, 'payable_account_currency', payable_account_currency);
			}
		}
	}
});


frappe.ui.form.on('Requested Payments', {
	form_render: function (frm, cdt, cdn) {
		if (locals[cdt][cdn].status == "") {
		}
	}
});


//For recommend button
cur_frm.cscript.recommend_request = function (frm) {
	var selected = cur_frm.get_selected();
	if (selected['requested_funds']) {
		frappe.confirm(
			'Confirm: Recommend selected requests?',
			function () {
				$.each(selected['requested_funds'], function (index, value) {
					frappe.call({
						method: "trans_ms.transport_management.doctype.requested_payments.requested_payments.recommend_request",
						freeze: true,
						args: {
							request_doctype: "Requested Funds Details",
							request_docname: value,
							user: frappe.user.full_name()
						},
						callback: function (data) {
							//alert(JSON.stringify(data));
						}
					});
				});
				location.reload();
			},
			function () {
				//Do nothing
			}
		);
	}
	else {
		show_alert("Error: Please select requests to process.");
	}
};


//For recommend against button
cur_frm.cscript.recommend_against_request = function (frm) {
	var selected = cur_frm.get_selected();
	if (selected['requested_funds']) {
		frappe.confirm(
			'Confirm: Recommend against the selected requests?',
			function () {
				$.each(selected['requested_funds'], function (index, value) {
					frappe.call({
						method: "erpnext.accounts.doctype.requested_payments.requested_payments.recommend_against_request",
						freeze: true,
						args: {
							request_doctype: "Requested Funds Details",
							request_docname: value,
							user: frappe.user.full_name()
						},
						callback: function (data) {
							//alert(JSON.stringify(data));
						}
					});
				});
				location.reload();
			},
			function () {
				//Do nothing
			}
		);
	}
	else {
		show_alert("Error: Please select requests to process.");
	}
};


//For approve button
cur_frm.cscript.approve_request = function (frm) {
	var selected = cur_frm.get_selected();
	if (selected['requested_funds']) {
		frappe.confirm(
			'Confirm: Approve selected requests?',
			function () {
				$.each(selected['requested_funds'], function (index, value) {
					frappe.call({
						method: "trans_ms.transport_management.doctype.requested_payments.requested_payments.approve_request",
						freeze: true,
						args: {
							request_doctype: "Requested Funds Details",
							request_docname: value,
							user: frappe.user.full_name()
						},
						callback: function (data) {
							//alert(JSON.stringify(data));
						}
					});
				});
				location.reload();
			},
			function () {
				//Do nothing
			}
		);
	}
	else {
		show_alert("Error: Please select requests to process.");
	}
};

//For reject button
cur_frm.cscript.reject_request = function (frm) {
	//cur_frm.cscript.populate_child(cur_frm.doc.reference_doctype, cur_frm.doc.reference_docname);
	var selected = cur_frm.get_selected();
	if (selected['requested_funds']) {
		frappe.confirm(
			'Confirm: Reject selected requests?',
			function () {
				$.each(selected['requested_funds'], function (index, value) {
					frappe.call({
						method: "trans_ms.transport_management.doctype.requested_payments.requested_payments.reject_request",
						freeze: true,
						args: {
							request_doctype: "Requested Funds Details",
							request_docname: value,
							user: frappe.user.full_name()
						},
						callback: function (data) {
							//alert(JSON.stringify(data));
						}
					});
				});
				location.reload();
			},
			function () {
				//Do nothing
			}
		);
	}
	else {
		show_alert("Error: Please select requests to process.");
	}
};


//For accounts approval
cur_frm.cscript.accounts_approval = function (frm) {
	var selected = cur_frm.get_selected();
	if (selected['accounts_approval']) {
		frappe.confirm(
			'Confirm: Approve selected requests?',
			function () {
				$.each(selected['accounts_approval'], function (index, value) {
					frappe.call({
						method: "trans_ms.transport_management.doctype.requested_payments.requested_payments.accounts_approval",
						freeze: true,
						args: {
							request_doctype: "Requested Funds Accounts Table",
							request_docname: value,
							parent_doctype: cur_frm.doctype,
							parent_docname: cur_frm.docname,
							local: locals['Requested Funds Accounts Table'][value],
							reference: locals['Requested Funds Accounts Table'][value].reference,
							user: frappe.user.full_name()
						},
						callback: function (data) {
							console.log(JSON.stringify(data));
						}
					});
				});
				frappe.after_ajax(function () {
					cur_frm.reload_doc();
				});
			},
			function () {
				//Do nothing
			}
		);
	}
	else {
		show_alert("Error: Please select requests to process.");
	}
};


//For accounts cancel
cur_frm.cscript.accounts_cancel = function (frm) {
	var selected = cur_frm.get_selected();
	var reload = false;
	if (selected['accounts_approval']) {
		frappe.confirm(
			'Confirm: Cancel selected requests?',
			function () {
				$.each(selected['accounts_approval'], function (index, value) {
					reload = false;
					frappe.call({
						method: "trans_ms.transport_management.doctype.requested_payments.requested_payments.accounts_cancel",
						freeze: true,
						args: {
							request_doctype: "Requested Funds Accounts Table",
							request_docname: value,
							parent_doctype: cur_frm.doctype,
							parent_docname: cur_frm.docname,
							local: locals['Requested Funds Accounts Table'][value],
							reference: locals['Requested Funds Accounts Table'][value].reference,
							user: frappe.user.full_name()
						},
						callback: function (data) {
							console.log(data.message);
						}
					});
				});
				location.reload();
			},
			function () {
				//Do nothing
			}
		);
	}
	else {
		show_alert("Error: Please select requests to process.");
	}
};


cur_frm.cscript.populate_child = function (reference_doctype, reference_docname) {
	frappe.model.with_doc(reference_doctype, reference_docname, function () {
		var request_total_amount_tsh = 0;
		var request_total_amount_usd = 0;
		var reference_doc = frappe.get_doc(reference_doctype, reference_docname);

		//If its requested from vehicle trip, there is main and return requested funds
		if ('Vehicle Trip' == reference_doctype) {
			//For main trip
			reference_doc.main_requested_funds.forEach(function (row) {
				//if(row.request_hidden_status == "0")
				if (row.request_status != "Approved" && row.request_status != "Rejected") {
					var new_row = cur_frm.add_child("requested_funds");
					new_row.name = row.name;
					new_row.request_date = row.request_date;
					new_row.request_amount = row.request_amount;
					new_row.request_currency = row.request_currency;
					new_row.request_description = row.request_description;
					new_row.request_comment = row.request_comment;
					new_row.request_status = row.request_status;
					if (row.request_currency == 'TZS') {
						request_total_amount_tsh += row.request_amount;
					}
					else if (row.request_currency == 'USD') {
						request_total_amount_usd += row.request_amount;
					}
					cur_frm.refresh_field("requested_funds");
				}
				else {
					console.log("Executing");
					var new_row = cur_frm.add_child("previous_requested_funds");
					new_row.name = row.name;
					new_row.request_date = row.request_date;
					new_row.request_amount = row.request_amount;
					new_row.request_currency = row.request_currency;
					new_row.request_description = row.request_description;
					new_row.request_comment = row.request_comment;
					new_row.request_status = row.request_status;
					cur_frm.refresh_field("previous_requested_funds");
				}
			});

			//For return trip
			reference_doc.return_requested_funds.forEach(function (row) {
				//if(row.request_hidden_status == "0")
				if (row.request_status != "Approved" && row.request_status != "Rejected") {
					var new_row = cur_frm.add_child("requested_funds");
					new_row.name = row.name;
					new_row.request_date = row.request_date;
					new_row.request_amount = row.request_amount;
					new_row.request_currency = row.request_currency;
					new_row.request_description = row.request_description;
					new_row.request_comment = row.request_comment;
					new_row.request_status = row.request_status;
					if (row.request_currency == 'TZS') {
						request_total_amount_tsh += row.request_amount;
					}
					else if (row.request_currency == 'USD') {
						request_total_amount_usd += row.request_amount;
					}
					cur_frm.refresh_field("requested_funds");
				}
				else {
					var new_row = cur_frm.add_child("previous_requested_funds");
					new_row.name = row.name;
					new_row.request_date = row.request_date;
					new_row.request_amount = row.request_amount;
					new_row.request_currency = row.request_currency;
					new_row.request_description = row.request_description;
					new_row.request_comment = row.request_comment;
					new_row.request_status = row.request_status;
					cur_frm.refresh_field("previous_requested_funds");
				}
			});
		}
		else {
			reference_doc.requested_funds.forEach(function (row) {
				//if(row.request_hidden_status == "0")
				if (row.request_status != "Approved" && row.request_status != "Rejected") {
					var new_row = cur_frm.add_child("requested_funds");
					new_row.name = row.name;
					new_row.request_date = row.request_date;
					new_row.request_amount = row.request_amount;
					new_row.request_currency = row.request_currency;
					new_row.request_description = row.request_description;
					new_row.request_comment = row.request_comment;
					new_row.request_status = row.request_status;
					if (row.request_currency == 'TZS') {
						request_total_amount_tsh += row.request_amount;
					}
					else if (row.request_currency == 'USD') {
						request_total_amount_usd += row.request_amount;
					}
					cur_frm.refresh_field("requested_funds");
				}
				else {
					var new_row = cur_frm.add_child("previous_requested_funds");
					new_row.name = row.name;
					new_row.request_date = row.request_date;
					new_row.request_amount = row.request_amount;
					new_row.request_currency = row.request_currency;
					new_row.request_description = row.request_description;
					new_row.request_comment = row.request_comment;
					new_row.request_status = row.request_status;
					cur_frm.refresh_field("previous_requested_funds");
				}
			});
		}
		if (request_total_amount_tsh != 0 || request_total_amount_usd != 0) {
			cur_frm.set_df_property("html1", "hidden", 0);
			cur_frm.set_df_property("html2", "hidden", 0);
			console.log(cur_frm.get_field('request_total_amount'));
			cur_frm.get_field("request_total_amount").$wrapper[0].innerHTML = '<p class="text-muted small">Total Requested Amount</p><b>USD ' + request_total_amount_usd + ' <br> TZS ' + request_total_amount_tsh.toLocaleString() + '</b>';
			//cur_frm.refresh_field("request_total_amount");
		}
		else {
			cur_frm.set_df_property("request_total_amount", "hidden", 1);
			cur_frm.set_df_property("html1", "hidden", 1);
			cur_frm.set_df_property("html2", "hidden", 1);
		}
	});
};


frappe.ui.form.on('Requested Funds Accounts Table', {
	disburse_funds: function (frm, cdt, cdn) {
		frm.save_or_update();
		if (frm.is_dirty()) {
			frappe.throw(__("Plase Save First"));
			return;
		}
		const row = locals[cdt][cdn];
		if (row.journal_entry) return;
		frappe.call({
			method: "trans_ms.transport_management.doctype.vehicle_trip.vehicle_trip.create_fund_jl",
			args: {
				doc: frm.doc,
				row: row
			},
			callback: function (data) {
				frappe.set_route('Form', data.message.doctype, data.message.name);
			}
		});
	}
});




//For approve button
cur_frm.cscript.approve_request = function (frm) {
	var selected = cur_frm.get_selected();
	if (selected['requested_funds']) {
		frappe.confirm(
			'Confirm: Approve selected requests?',
			function () {
				$.each(selected['requested_funds'], function (index, value) {
					frappe.call({
						method: "trans_ms.transport_management.doctype.requested_payments.requested_payments.approve_request",
						freeze: true,
						args: {
							request_doctype: "Requested Funds Details",
							request_docname: value,
							user: frappe.user.full_name()
						},
						callback: function (data) {
							//alert(JSON.stringify(data));
						}
					});
				});
				location.reload();
			},
			function () {
				//Do nothing
			}
		);
	} else {
		show_alert("Error: Please select requests to process.");
	}
};

//For reject button
cur_frm.cscript.reject_request = function (frm) {
	//cur_frm.cscript.populate_child(cur_frm.doc.reference_doctype, cur_frm.doc.reference_docname);
	var selected = cur_frm.get_selected();
	if (selected['requested_funds']) {
		frappe.confirm(
			'Confirm: Reject selected requests?',
			function () {
				$.each(selected['requested_funds'], function (index, value) {
					frappe.call({
						method: "trans_ms.transport_management.doctype.requested_payments.requested_payments.reject_request",
						freeze: true,
						args: {
							request_doctype: "Requested Funds Details",
							request_docname: value,
							user: frappe.user.full_name()
						},
						callback: function (data) {
							//alert(JSON.stringify(data));
						}
					});
				});
				location.reload();
			},
			function () {
				//Do nothing
			}
		);
	} else {
		show_alert("Error: Please select requests to process.");
	}
};
