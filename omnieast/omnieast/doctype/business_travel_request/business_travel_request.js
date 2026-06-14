// Copyright (c) 2026, Shahzad Naser and contributors
// For license information, please see license.txt

frappe.ui.form.on("Business Travel Request", {  
    // Trigger this function when any of these fields change
    grade: function(frm) { fetch_policy(frm); },
    diem_type: function(frm) { fetch_policy(frm); },
    travel_type: function(frm) { fetch_policy(frm); },
    estimated_km_for_the_business_trip: function(frm) { calculate_car_trip_amount(frm)},
    required_cash: function(frm) { set_total_amount(frm)}
});

function calculate_car_trip_amount(frm){
    if(frm.doc.car_trip_allowance == "Yes" && frm.doc.estimated_km_for_the_business_trip){
        frm.set_value("car_trip_amount", frm.doc.estimated_km_for_the_business_trip * 0.5);
    }

    set_total_amount(frm);
}

function set_total_amount(frm){
    total_amount = frm.doc.diem_amount;
    if(frm.doc.car_trip_amount){
        total_amount = total_amount + frm.doc.car_trip_amount;
    }
    if(frm.doc.required_cash){
        total_amount = total_amount - frm.doc.required_cash;
    }

    frm.set_value("total_amount", total_amount);
}

function fetch_policy(frm) {
    let grade_num = parseInt(frm.doc.grade.replace('Grade ', ''));
    
    // 1. Fetch ALL policies where the min_grade matches
    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Travel Policy",
            filters: {
                "diem_type": frm.doc.diem_type,
                "travel_type": frm.doc.travel_type
            },
            fields: ["name", "min_grade", "max_grade", "amount", "flight_class", "remarks"]
        },
        callback: function(r) {
            if (r.message) {
                // 2. Iterate through records and apply logic in JavaScript
                let matched_policy = r.message.find(policy => {
                    let min = parseInt(policy.min_grade);
                    let max = (policy.max_grade.toLowerCase() === 'above') ? 99 : parseInt(policy.max_grade);
                    
                    return grade_num >= min && grade_num <= max;
                });
                console.log(matched_policy)
                if (matched_policy) {
                    frm.set_value("diem_amount", matched_policy.amount);
                    frm.set_value("flight_class", matched_policy.flight_class);
                    frm.set_value("remarks", matched_policy.remarks);
                } else {
                    frappe.msgprint(__("No matching policy for this Grade."));
                }
            }
        }
    });
}
