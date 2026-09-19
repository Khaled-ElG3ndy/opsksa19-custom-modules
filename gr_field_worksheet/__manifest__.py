# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Technician Field Worksheet",
    'summary': "Tablet field worksheet (ABSAL Field Inspection Report) with "
               "verified proof: signature/PIN, serial-scan, GPS, and photos",
    'description': "Technician tablet worksheet (gr.field.worksheet) - the "
                   "paperless replacement for ABSAL's Field Inspection Report. A "
                   "standalone worksheet the technician fills on a tablet, which "
                   "can link to either an M7 maintenance job or an M13 rental "
                   "inspection. Mirrors the paper form field-for-field: header "
                   "(serial / job order / customer / hours / location / time "
                   "in-out), visiting mode, spare parts, the System Function "
                   "Panel (VAC/HZ/DCV/KPA/RPM readings + load at 5/10/15 min), the "
                   "mechanical checklist, and remarks. VERIFIED PROOF is a layered "
                   "evidence bundle: technician + customer signature capture, an "
                   "optional PIN second factor, a scanned serial confirming the "
                   "right unit, GPS coordinates confirming the right place, a "
                   "timestamp, and photo attachments. A worksheet cannot be marked "
                   "Verified until the evidence requirements are met - enforced "
                   "server-side. Part of the Generator Rental ERP vertical (gr_* "
                   "suite) for Odoo 18 Community.",
    'version': '19.0.1.0.0',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_fleet_base', 'gr_maintenance',
                'gr_rental_inspection'],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_field_worksheet_rules.xml',
        'data/ir_sequence.xml',
        'data/gr_worksheet_checklist_data.xml',
        'views/gr_field_worksheet_views.xml',
        'views/gr_field_worksheet_menus.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
