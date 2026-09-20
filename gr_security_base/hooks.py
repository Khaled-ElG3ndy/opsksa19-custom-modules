# -*- coding: utf-8 -*-


def _grant_generator_admin_to_settings_admins(env):
    group = env.ref(
        'gr_security_base.group_generator_administrator',
        raise_if_not_found=False)
    settings_group = env.ref('base.group_system', raise_if_not_found=False)
    if not group or not settings_group:
        return
    admins = settings_group.all_user_ids.filtered(lambda user: user.active)
    if admins:
        admins.write({'group_ids': [(4, group.id)]})


def post_init_hook(env):
    _grant_generator_admin_to_settings_admins(env)
