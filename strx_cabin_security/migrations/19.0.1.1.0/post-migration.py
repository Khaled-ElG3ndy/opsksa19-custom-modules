# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    group = env.ref(
        'strx_cabin_security.group_cabin_administrator',
        raise_if_not_found=False)
    settings_group = env.ref('base.group_system', raise_if_not_found=False)
    if not group or not settings_group:
        return

    active_cabin_admins = group.all_user_ids.filtered(lambda user: user.active)
    if active_cabin_admins:
        return

    admins = settings_group.all_user_ids.filtered(lambda user: user.active)
    if admins:
        admins.write({'group_ids': [(4, group.id)]})
        _logger.info(
            "Granted Cabin Administrator to active Settings admins during migration.")
