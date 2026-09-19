# -*- coding: utf-8 -*-
from . import models


def post_init_assign_generator_type(env):
    generator_type = env.ref(
        'gr_equipment.equipment_type_generator', raise_if_not_found=False)
    if generator_type:
        env['gr.generator.asset'].search([
            ('equipment_type_id', '=', False),
        ]).write({'equipment_type_id': generator_type.id})
