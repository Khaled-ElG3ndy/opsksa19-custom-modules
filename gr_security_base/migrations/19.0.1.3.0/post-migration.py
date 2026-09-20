# -*- coding: utf-8 -*-
"""Keep Settings administrators from being locked out of Generator Rental."""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    group = env.ref(
        'gr_security_base.group_generator_administrator',
        raise_if_not_found=False)
    settings_group = env.ref('base.group_system', raise_if_not_found=False)
    if not group or not settings_group:
        _logger.warning(
            "Generator admin or Settings group missing; cannot refresh admin access")
        return

    if group.all_user_ids.filtered(lambda user: user.active):
        return

    admins = settings_group.all_user_ids.filtered(lambda user: user.active)
    if admins:
        admins.write({'group_ids': [(4, group.id)]})
        _logger.info(
            "Granted Generator Administrator to %s active Settings admin(s)",
            len(admins))
