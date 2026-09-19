# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Equipment Spine",
    'summary': "Owner dimension on the equipment spine: Owned / Rented-in / "
               "Customer-owned, with rental-pool enforcement",
    'description': "Establishes the equipment spine for ABSAL's three business "
                   "models on one shared fleet. Every physical generator is one "
                   "equipment record carrying an Asset No, a serial, and an owner "
                   "type (Owned, Rented-in from a vendor, or Customer-owned). "
                   "Customer-owned units are kept out of the rental availability "
                   "pool entirely - both hidden from rental selection and blocked "
                   "server-side - because ABSAL only services them. Owned and "
                   "rented-in units remain rentable; the owner flag drives the "
                   "different money flows (owned-fleet margin vs sublet margin) "
                   "surfaced in later milestones. Extends gr.generator.asset "
                   "non-destructively; every existing unit defaults to Owned. "
                   "Part of the Generator Rental ERP vertical (gr_* suite) for "
                   "Odoo 18 Community.",
    'version': '19.0.1.2.1',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_fleet_base', 'gr_rental_order'],
    'data': [
        'security/ir.model.access.csv',
        'data/gr_equipment_type_data.xml',
        'views/gr_equipment_views.xml',
    ],
    'post_init_hook': 'post_init_assign_generator_type',
    'application': False,
    'installable': True,
    'auto_install': False,
}
