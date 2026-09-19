# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID


WORKFLOW_BY_CODE = {
    'GEN': {
        'rental_requires_dispatch': True,
        'rental_requires_installation': True,
        'rental_requires_meter_readings': True,
        'rental_requires_delivery_inspection': True,
        'rental_requires_return_inspection': True,
        'rental_requires_delivery_signature': True,
        'rental_requires_return_signature': True,
        'rental_standalone_ok': True,
        'rental_accessory_ok': False,
    },
    'CBL': {
        'rental_requires_dispatch': True,
        'rental_requires_installation': False,
        'rental_requires_meter_readings': False,
        'rental_requires_delivery_inspection': False,
        'rental_requires_return_inspection': False,
        'rental_requires_delivery_signature': True,
        'rental_requires_return_signature': True,
        'rental_standalone_ok': True,
        'rental_accessory_ok': True,
    },
    'TNK': {
        'rental_requires_dispatch': True,
        'rental_requires_installation': False,
        'rental_requires_meter_readings': False,
        'rental_requires_delivery_inspection': True,
        'rental_requires_return_inspection': True,
        'rental_requires_delivery_signature': True,
        'rental_requires_return_signature': True,
        'rental_standalone_ok': True,
        'rental_accessory_ok': True,
    },
    'PNL': {
        'rental_requires_dispatch': True,
        'rental_requires_installation': True,
        'rental_requires_meter_readings': False,
        'rental_requires_delivery_inspection': True,
        'rental_requires_return_inspection': True,
        'rental_requires_delivery_signature': True,
        'rental_requires_return_signature': True,
        'rental_standalone_ok': True,
        'rental_accessory_ok': True,
    },
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for code, values in WORKFLOW_BY_CODE.items():
        env['gr.equipment.type'].search([('code', '=', code)]).write(values)
