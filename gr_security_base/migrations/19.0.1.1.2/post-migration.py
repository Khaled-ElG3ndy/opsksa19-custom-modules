# -*- coding: utf-8 -*-
"""Link the GenRental security groups to their Odoo 19 privilege.

Odoo 19 replaced res.groups.category_id with privilege_id pointing at the new
res.groups.privilege model. The module's security XML sets privilege_id and
sequence, but the nine group records carry ir.model.data.noupdate = True on
databases coming from Odoo 18, so a module upgrade leaves them untouched and
the roles would render as loose checkboxes on the user form instead of the
single "GenRental" selection they had under Odoo 18's category.

Idempotent: only fills in values that are still missing.
"""
import logging

_logger = logging.getLogger(__name__)

# xml_id -> sequence, mirroring security/gr_security_groups.xml
GROUP_SEQUENCES = {
    'gr_security_base.group_generator_user': 10,
    'gr_security_base.group_generator_sales_officer': 20,
    'gr_security_base.group_generator_operations_officer': 30,
    'gr_security_base.group_generator_maint_technician': 40,
    'gr_security_base.group_generator_maint_manager': 50,
    'gr_security_base.group_generator_finance_officer': 60,
    'gr_security_base.group_generator_finance_manager': 70,
    'gr_security_base.group_generator_general_manager': 80,
    'gr_security_base.group_generator_administrator': 90,
}


def migrate(cr, version):
    if not version:
        return

    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    privilege = env.ref(
        'gr_security_base.res_groups_privilege_generator_rental',
        raise_if_not_found=False)
    if not privilege:
        _logger.warning(
            "GenRental privilege not found; leaving group privileges untouched")
        return

    updated = 0
    for xml_id, sequence in GROUP_SEQUENCES.items():
        group = env.ref(xml_id, raise_if_not_found=False)
        if not group:
            _logger.warning("Missing security group %s", xml_id)
            continue
        values = {}
        if not group.privilege_id:
            values['privilege_id'] = privilege.id
        if not group.sequence:
            values['sequence'] = sequence
        if values:
            group.write(values)
            updated += 1

    _logger.info(
        "Linked %s GenRental group(s) to privilege %s", updated, privilege.name)
