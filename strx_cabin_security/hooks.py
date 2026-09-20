# -*- coding: utf-8 -*-


def _grant_cabin_admin_to_settings_admins(env):
    group = env.ref(
        'strx_cabin_security.group_cabin_administrator',
        raise_if_not_found=False)
    settings_group = env.ref('base.group_system', raise_if_not_found=False)
    if not group or not settings_group:
        return

    admins = settings_group.all_user_ids.filtered(lambda user: user.active)
    if admins:
        admins.write({'group_ids': [(4, group.id)]})


def post_init_hook(env):
    _grant_cabin_admin_to_settings_admins(env)
