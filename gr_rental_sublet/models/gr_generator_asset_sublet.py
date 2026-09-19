# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .gr_sublet_buffer import BUFFER_LEVEL_SELECTION


class GrGeneratorAssetSublet(models.Model):
    """Surface the supplier rent-in window on the third-party unit itself.

    The window is owned by gr.sublet.agreement - that model stays the single
    source of truth for the vendor, the dates, the rent-in PO and the cost.
    What is added here is a read-only projection onto the equipment record, so
    an operator looking at the unit can see until when the company is allowed
    to re-rent it without opening a second screen, and so availability logic
    has one cheap place to ask."""
    _inherit = 'gr.generator.asset'

    # Days before the rent-in end date at which the unit starts warning.
    _SUPPLIER_EXPIRY_WARNING_DAYS = 7

    sublet_agreement_ids = fields.One2many(
        'gr.sublet.agreement', 'asset_id', string='Supplier Rental Agreements')
    sublet_agreement_count = fields.Integer(
        string='Supplier Agreements', compute='_compute_sublet_agreement_count')

    current_sublet_agreement_id = fields.Many2one(
        'gr.sublet.agreement', string='Current Supplier Agreement',
        compute='_compute_current_sublet_agreement', store=True,
        help="The live rent-in agreement covering this unit today: the "
             "committed one if there is one, otherwise the latest draft.")

    supplier_contract_ref = fields.Char(
        string='Supplier Contract Reference',
        related='current_sublet_agreement_id.name', store=True, readonly=True)
    supplier_rental_start = fields.Date(
        string='Supplier Rental Start',
        related='current_sublet_agreement_id.date_start', store=True, readonly=True)
    supplier_rental_end = fields.Date(
        string='Supplier Rental End',
        related='current_sublet_agreement_id.date_end', store=True, readonly=True)
    supplier_rental_cost = fields.Monetary(
        string='Supplier Rental Cost', currency_field='currency_id',
        related='current_sublet_agreement_id.rent_in_amount', store=True,
        readonly=True)
    supplier_rental_note = fields.Text(
        string='Supplier Rental Notes',
        related='current_sublet_agreement_id.note', readonly=False)

    supplier_rental_status = fields.Selection([
        ('not_applicable', 'Not Applicable'),
        ('no_agreement', 'No Supplier Agreement'),
        ('active', 'Supplier Rental Active'),
        ('expiring_soon', 'Supplier Rental Expiring Soon'),
        ('expired', 'Supplier Rental Expired'),
        ('returned', 'Returned to Supplier'),
    ], string='Supplier Rental Status', compute='_compute_supplier_rental_status',
        store=True, index=True, default='not_applicable',
        help="Availability of the unit from the supplier's side. This is about "
             "our right to hold the unit, and is deliberately separate from "
             "Status, which is about where the unit physically is.")

    # The unit's own view of the return buffer, taken from whichever customer
    # rental currently holds it. A read-only projection of the order's value,
    # so the warning also reaches the equipment record - which is where an
    # operator planning collections actually looks.
    supplier_buffer_level = fields.Selection(
        BUFFER_LEVEL_SELECTION, string='Return Buffer',
        related='current_rental_order_id.supplier_buffer_level', readonly=True)
    supplier_buffer_message = fields.Char(
        string='Return Buffer Warning',
        related='current_rental_order_id.supplier_buffer_message', readonly=True)
    supplier_return_buffer_days = fields.Integer(
        string='Supplier Return Buffer (days)',
        related='current_rental_order_id.supplier_return_buffer_days',
        readonly=True)

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    def _compute_sublet_agreement_count(self):
        counts = dict.fromkeys(self.ids, 0)
        for asset, count in self.env['gr.sublet.agreement']._read_group(
                [('asset_id', 'in', self.ids)], ['asset_id'], ['__count']):
            counts[asset.id] = count
        for asset in self:
            asset.sublet_agreement_count = counts.get(asset.id, 0)

    @api.depends('owner_type', 'sublet_agreement_ids.state',
                 'sublet_agreement_ids.date_start', 'sublet_agreement_ids.date_end')
    def _compute_current_sublet_agreement(self):
        for asset in self:
            if asset.owner_type != 'rented_in':
                asset.current_sublet_agreement_id = False
                continue
            agreements = asset.sublet_agreement_ids
            # Committed wins over draft: a raised rent-in PO is the real
            # obligation. Within a state, the latest start date wins, which is
            # how a renewed rent-in supersedes the previous period.
            for state in ('committed', 'draft', 'returned'):
                candidates = agreements.filtered(lambda ag: ag.state == state)
                if candidates:
                    asset.current_sublet_agreement_id = candidates.sorted(
                        key=lambda ag: (ag.date_start or fields.Date.today(), ag.id),
                        reverse=True)[0]
                    break
            else:
                asset.current_sublet_agreement_id = False

    @api.depends('owner_type', 'current_sublet_agreement_id',
                 'current_sublet_agreement_id.state',
                 'current_sublet_agreement_id.date_start',
                 'current_sublet_agreement_id.date_end')
    def _compute_supplier_rental_status(self):
        today = fields.Date.context_today(self)
        for asset in self:
            if asset.owner_type != 'rented_in':
                asset.supplier_rental_status = 'not_applicable'
                continue
            agreement = asset.current_sublet_agreement_id
            if not agreement:
                asset.supplier_rental_status = 'no_agreement'
            elif agreement.state == 'returned':
                asset.supplier_rental_status = 'returned'
            elif agreement.date_end and agreement.date_end < today:
                asset.supplier_rental_status = 'expired'
            elif agreement.date_end and (agreement.date_end - today).days <= \
                    self._SUPPLIER_EXPIRY_WARNING_DAYS:
                asset.supplier_rental_status = 'expiring_soon'
            else:
                asset.supplier_rental_status = 'active'

    # ------------------------------------------------------------------
    # Cron: the status is date-relative, so a stored value goes stale at
    # midnight even though nothing was written. Recompute daily rather than
    # dropping the store, which would cost the filters and the group-by.
    # ------------------------------------------------------------------
    @api.model
    def _cron_refresh_supplier_rental_status(self):
        assets = self.search([('owner_type', '=', 'rented_in')])
        if not assets:
            return 0
        self.env.add_to_compute(
            self._fields['supplier_rental_status'], assets)
        assets.flush_recordset(['supplier_rental_status'])
        # The agreement's exposure flag is date-relative in the same way.
        agreements = assets.mapped('sublet_agreement_ids')
        if agreements:
            Agreement = self.env['gr.sublet.agreement']
            self.env.add_to_compute(
                Agreement._fields['exposure_flagged'], agreements)
            self.env.add_to_compute(
                Agreement._fields['exposure_reason'], agreements)
            agreements.flush_recordset(['exposure_flagged', 'exposure_reason'])
        return len(assets)

    # ------------------------------------------------------------------
    @api.constrains('owner_type', 'owner_partner_id')
    def _check_live_sublet_agreements_keep_supplier_ownership(self):
        for asset in self:
            agreements = asset.sublet_agreement_ids.filtered(
                lambda ag: ag.state in ('draft', 'committed'))
            if not agreements:
                continue
            if asset.owner_type != 'rented_in':
                raise ValidationError(_(
                    "Equipment %(asset)s has active supplier rental "
                    "agreement(s), so it must remain Third-Party until those "
                    "agreements are returned or cancelled.",
                    asset=asset.display_name))
            mismatched = agreements.filtered(
                lambda ag: ag.vendor_id and ag.vendor_id != asset.owner_partner_id)
            if mismatched:
                raise ValidationError(_(
                    "Equipment %(asset)s cannot use supplier %(supplier)s while "
                    "active supplier rental agreement(s) use %(vendors)s.",
                    asset=asset.display_name,
                    supplier=asset.owner_partner_id.display_name,
                    vendors=', '.join(mismatched.mapped('vendor_id.display_name'))))

    # ------------------------------------------------------------------
    def action_view_sublet_agreements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Supplier Rental Agreements'),
            'res_model': 'gr.sublet.agreement',
            'domain': [('asset_id', '=', self.id)],
            'view_mode': 'list,form',
            'context': {
                'default_asset_id': self.id,
                'default_vendor_id': self.owner_partner_id.id,
            },
        }
