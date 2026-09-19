# -*- coding: utf-8 -*-
"""Upgrade-safe configuration of the spare-parts category.

A post_init_hook only fires on uninstalled->installed, so it does not re-run on
-u. This post-migration re-applies the AVCO costing (and automated valuation
where possible) on every upgrade to this version, which lets a plain
`-u gr_parts_consumption` reconcile a category that was left unconfigured by an
earlier failed/partial install.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # import the shared configurator from the module package
    from odoo.addons.gr_parts_consumption import _configure_parts_category
    _configure_parts_category(env)
