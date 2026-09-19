# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class GrSubletAgreementHistory(models.Model):
    _inherit = 'gr.sublet.agreement'

    def _history_record(self, event_type, title, description=False):
        History = self.env['rental.asset.history']
        for agreement in self:
            History.record_event(
                agreement.asset_id,
                event_type=event_type,
                name=title,
                description=description or agreement.display_name,
                partner=agreement.vendor_id,
                event_datetime=False,
                technical_key='gr.sublet.agreement:%s:%s:asset:%s' % (
                    agreement.id, event_type, agreement.asset_id.id),
                source=agreement,
            )

    @api.model_create_multi
    def create(self, vals_list):
        agreements = super().create(vals_list)
        agreements._history_record(
            'sublet_created',
            _("Rent-in agreement created"),
            _("Rented-in asset agreement was created."))
        return agreements

    def action_generate_rent_in_po(self):
        res = super().action_generate_rent_in_po()
        self._history_record(
            'vendor_received',
            _("Received / committed from vendor"),
            _("Rent-in purchase order was raised; vendor commitment is active."))
        return res

    def action_mark_returned(self):
        res = super().action_mark_returned()
        self._history_record(
            'vendor_returned',
            _("Returned to vendor"),
            _("Rented-in asset was marked returned to the vendor."))
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self._history_record(
            'vendor_cancelled',
            _("Vendor rent-in cancelled"),
            _("Rented-in agreement was cancelled."))
        return res


class GrSubletDirectCostHistory(models.Model):
    _inherit = 'gr.sublet.direct.cost'

    @api.model_create_multi
    def create(self, vals_list):
        costs = super().create(vals_list)
        costs._history_record_direct_cost()
        return costs

    def _history_record_direct_cost(self):
        History = self.env['rental.asset.history']
        for cost in self.filtered('agreement_id.asset_id'):
            event_dt = fields.Datetime.to_datetime(cost.cost_date) \
                if cost.cost_date else fields.Datetime.now()
            History.record_event(
                cost.agreement_id.asset_id,
                event_type='sublet_direct_cost',
                name=_("Sublet direct cost recorded"),
                description=_(
                    "%(type)s cost %(amount)s recorded on %(agreement)s: %(name)s",
                    type=dict(cost._fields['cost_type'].selection).get(
                        cost.cost_type, cost.cost_type),
                    amount=cost.amount,
                    agreement=cost.agreement_id.display_name,
                    name=cost.name),
                partner=cost.agreement_id.vendor_id,
                event_datetime=event_dt,
                technical_key='gr.sublet.direct.cost:%s:sublet_direct_cost:asset:%s' % (
                    cost.id, cost.agreement_id.asset_id.id),
                source=cost,
            )
