# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    generator_type = env.ref(
        'gr_equipment.equipment_type_generator', raise_if_not_found=False)
    if generator_type:
        env['gr.generator.asset'].search([
            ('equipment_type_id', '=', False),
        ]).write({'equipment_type_id': generator_type.id})
