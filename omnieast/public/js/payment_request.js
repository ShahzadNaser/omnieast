// JHR/HT/00615: hide the email message box (Message / Message Examples) on Payment Request
frappe.ui.form.on('Payment Request', {
    refresh: function(frm) {
        frm.toggle_display(["section_break_10", "message", "message_examples"], false);
    }
});
