# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Purchase-to-Install Traceability",
    'summary': "Closed loop: request a part for a specific generator, purchase it "
               "born-linked to that unit, receive, install by Asset No, reconcile",
    'description': "Purchase-to-install traceability (gr.parts.request): the "
                   "control ABSAL asked for - a part ordered 'for generator X' "
                   "must be provably required and provably installed on X. The "
                   "loop: (1) Request a part against a maintenance job, which "
                   "already carries the equipment/Asset No; (2) Purchase - a PO "
                   "is generated from the request so it is born linked to the "
                   "unit, not floating free; (3) Receive into stock; (4) Install "
                   "and verify by Asset No - consumption links back to its "
                   "originating request/PO; (5) Reconcile - a part ordered for a "
                   "unit but never consumed on it shows as unreconciled, the "
                   "parts-leakage early warning. Extends the M8 parts consumption "
                   "line with a purchase/request origin. Part of the Generator "
                   "Rental ERP vertical (gr_* suite) for Odoo 18 Community.",
    'version': '19.0.1.0.2',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_fleet_base', 'gr_maintenance',
                'gr_parts_consumption', 'purchase', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_parts_request_rules.xml',
        'data/ir_sequence.xml',
        'views/gr_parts_request_views.xml',
        'views/gr_parts_consumption_origin_views.xml',
        'views/gr_maintenance_job_request_views.xml',
        'views/gr_parts_purchase_menus.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
