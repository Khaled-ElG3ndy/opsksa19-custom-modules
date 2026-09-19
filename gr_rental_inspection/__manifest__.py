# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Rental Inspection Lock",
    'summary': "Pre-dispatch readiness gate and return inspection lock, with "
               "hours capture and ABSAL's machine-condition checklist",
    'description': "Pre/post-rental maintenance lock (gr.rental.inspection). "
                   "Mirrors ABSAL's Unified Delivery/Return/Replacement Note. A "
                   "unit cannot be DISPATCHED to a customer until a passed "
                   "DELIVERY inspection is recorded (readiness gate), and a "
                   "returned unit cannot be CLOSED/released back to Available "
                   "until a passed RETURN inspection is signed off (return lock). "
                   "Current running hours are captured at delivery and return "
                   "(feeding the hours-based PM trigger), alongside the exact "
                   "machine-condition checklist from ABSAL's form. Part of the "
                   "Generator Rental ERP vertical (gr_* suite) for Odoo 18 "
                   "Community.",
    'version': '19.0.1.0.0',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_fleet_base', 'gr_rental_order',
                'gr_equipment', 'gr_maintenance'],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_rental_inspection_rules.xml',
        'data/ir_sequence.xml',
        'data/gr_checklist_data.xml',
        'views/gr_rental_inspection_views.xml',
        'views/gr_rental_order_inspection_views.xml',
        'views/gr_rental_inspection_menus.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
