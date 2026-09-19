# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api, _


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    History = env['rental.asset.history']
    RentalHistory = env['rental.asset.rental.history']

    for asset in env['gr.generator.asset'].search([]):
        History.record_event(
            asset,
            event_type='asset_created',
            name=_("Asset %s created") % asset.display_name,
            description=_("Asset %s was registered in the system.")
            % asset.display_name,
            technical_key='gr.generator.asset:%s:asset_created' % asset.id,
            source=asset,
        )

    for order in env['gr.rental.order'].search([]):
        RentalHistory.sync_from_order(order)
