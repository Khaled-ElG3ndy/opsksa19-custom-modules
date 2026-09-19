# -*- coding: utf-8 -*-
from odoo import models, _


class GrRentalContractHistory(models.Model):
    _inherit = 'gr.rental.contract'

    def _history_preferred_assets(self, event_type, title, description):
        History = self.env['rental.asset.history']
        for contract in self:
            assets = contract.line_ids.mapped('preferred_asset_id')
            for asset in assets:
                History.record_event(
                    asset,
                    event_type=event_type,
                    name=title,
                    description=description,
                    partner=contract.partner_id,
                    location=contract.site_id,
                    location_label=contract.site_id.display_name if contract.site_id else False,
                    technical_key='gr.rental.contract:%s:%s:asset:%s' % (
                        contract.id, event_type, asset.id),
                    source=contract,
                )

    def action_approve(self):
        res = super().action_approve()
        self._history_preferred_assets(
            'contract_approved',
            _("Contract approved"),
            _("Contract containing this asset was approved."))
        return res

    def action_activate(self):
        res = super().action_activate()
        self._history_preferred_assets(
            'contract_activated',
            _("Contract activated"),
            _("Contract containing this asset was activated."))
        return res
