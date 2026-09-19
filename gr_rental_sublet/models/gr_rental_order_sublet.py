# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date

from .gr_sublet_buffer import BUFFER_LEVEL_SELECTION


class GrRentalOrderSublet(models.Model):
    """Link a rent-out order to its sublet agreement (the rent-in side)."""
    _inherit = 'gr.rental.order'

    sublet_agreement_id = fields.Many2one(
        'gr.sublet.agreement', string='Supplier Rental Agreement', index=True,
        help="If this rental is of a third-party unit, the agreement covering "
             "the rent-in side. Links the rent-out revenue to the rent-in cost, "
             "and defines the period in which the unit may be re-rented.")

    # Ownership of the booked unit, mirrored onto the order so the form can
    # badge it: the user is never one click away from knowing whose generator
    # they are committing to a customer.
    asset_owner_type = fields.Selection(
        related='asset_id.owner_type', string='Equipment Ownership',
        readonly=True)
    asset_is_third_party = fields.Boolean(
        related='asset_id.is_third_party', string='Third-Party Equipment',
        readonly=True)
    asset_supplier_id = fields.Many2one(
        related='asset_id.owner_partner_id', string='Equipment Supplier',
        readonly=True)
    supplier_rental_start = fields.Date(
        related='sublet_agreement_id.date_start',
        string='Supplier Rental Start', readonly=True)
    supplier_rental_end = fields.Date(
        related='sublet_agreement_id.date_end',
        string='Supplier Rental End', readonly=True)

    # ------------------------------------------------------------------
    # Supplier-return buffer: legal, but is it comfortable?
    # ------------------------------------------------------------------
    supplier_return_buffer_days = fields.Integer(
        string='Supplier Return Buffer (days)',
        compute='_compute_supplier_return_buffer', store=True,
        help="Whole days between the customer returning the unit and the date "
             "it is due back to the supplier. The time available to collect, "
             "inspect and transport it.")
    supplier_buffer_level = fields.Selection(
        BUFFER_LEVEL_SELECTION, string='Return Buffer',
        compute='_compute_supplier_return_buffer', store=True, index=True,
        help="How much slack there is before the unit must be back with the "
             "supplier. Not set for owned equipment or when the supplier "
             "rental has no end date.")
    supplier_buffer_message = fields.Char(
        string='Return Buffer Warning',
        compute='_compute_supplier_return_buffer',
        help="The operator-facing warning, empty when the buffer is comfortable.")

    @api.depends('asset_id', 'asset_id.owner_type', 'sublet_agreement_id',
                 'sublet_agreement_id.date_end', 'state',
                 'planned_return_datetime', 'actual_return_datetime')
    def _compute_supplier_return_buffer(self):
        Buffer = self.env['gr.sublet.buffer']
        for order in self:
            supplier_end = order.sublet_agreement_id.date_end
            _start, customer_end = order._customer_rental_window()
            applicable = bool(
                order.asset_id
                and order.asset_id.owner_type == 'rented_in'
                and supplier_end and customer_end
                and order.state not in ('cancelled', 'closed'))
            if not applicable:
                order.supplier_return_buffer_days = 0
                order.supplier_buffer_level = False
                order.supplier_buffer_message = False
                continue
            days = (supplier_end - customer_end).days
            level = Buffer._buffer_level(days)
            order.supplier_return_buffer_days = days
            order.supplier_buffer_level = level
            order.supplier_buffer_message = Buffer._buffer_message(days, level)

    def _post_supplier_buffer_warning(self):
        """Leave the warning in the order's chatter as well as on the form, so
        it survives as a record of what the operator was told at the moment
        the unit was committed."""
        for order in self.filtered(
                lambda o: o.supplier_buffer_level in ('warning', 'critical')):
            order.message_post(
                body=order.supplier_buffer_message,
                message_type='comment', subtype_xmlid='mail.mt_note')

    def _sublet_agreement_lookup_date(self):
        self.ensure_one()
        dt = self.date_requested or fields.Datetime.now()
        return fields.Datetime.to_datetime(dt).date()

    def _find_active_sublet_agreement(self):
        self.ensure_one()
        if not self.asset_id or self.asset_id.owner_type != 'rented_in':
            return self.env['gr.sublet.agreement']

        lookup_date = self._sublet_agreement_lookup_date()
        base_domain = [
            ('asset_id', '=', self.asset_id.id),
            ('company_id', '=', self.company_id.id),
            ('date_start', '<=', lookup_date),
            '|', ('date_end', '=', False), ('date_end', '>=', lookup_date),
        ]
        Agreement = self.env['gr.sublet.agreement']
        for state in ('committed', 'draft'):
            agreement = Agreement.search(
                base_domain + [('state', '=', state)],
                order='date_start desc, id desc', limit=1)
            if agreement:
                return agreement
        return Agreement

    def _sync_sublet_agreement_from_asset(self):
        for order in self:
            agreement = order._find_active_sublet_agreement()
            if order.sublet_agreement_id == agreement:
                continue
            if not order.sublet_agreement_id or \
                    order.sublet_agreement_id.asset_id != order.asset_id:
                order.with_context(gr_skip_sublet_autolink=True).write({
                    'sublet_agreement_id': agreement.id if agreement else False,
                })

    @api.onchange('asset_id', 'date_requested')
    def _onchange_asset_sublet_agreement(self):
        for order in self:
            agreement = order._find_active_sublet_agreement()
            if not order.sublet_agreement_id or \
                    order.sublet_agreement_id.asset_id != order.asset_id:
                order.sublet_agreement_id = agreement

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        to_sync = orders.filtered(
            lambda order: not order.sublet_agreement_id and order.asset_id)
        to_sync._sync_sublet_agreement_from_asset()
        return orders

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('gr_skip_sublet_autolink') and \
                'sublet_agreement_id' not in vals and \
                ({'asset_id', 'date_requested'} & set(vals)):
            self._sync_sublet_agreement_from_asset()
        return result

    def action_confirm(self):
        self.filtered(lambda order: not order.sublet_agreement_id) \
            ._sync_sublet_agreement_from_asset()
        return super().action_confirm()

    @api.model
    def _autolink_missing_sublet_agreements(self):
        orders = self.search([
            ('sublet_agreement_id', '=', False),
            ('asset_id.owner_type', '=', 'rented_in'),
            ('state', 'not in', ('cancelled', 'closed')),
        ])
        linked = self.browse()
        for order in orders:
            agreement = order._find_active_sublet_agreement()
            if agreement:
                order.with_context(gr_skip_sublet_autolink=True).write({
                    'sublet_agreement_id': agreement.id,
                })
                linked |= order
        return linked

    # ------------------------------------------------------------------
    # Third-party availability rule
    #
    # A unit we do not own may only be re-rented inside the period the
    # supplier has given us. The customer window must sit completely within
    # the supplier window - renting past the rent-in end date would put the
    # company in possession of somebody else's generator with no right to it.
    # ------------------------------------------------------------------
    def _customer_rental_window(self):
        """(start, end) of the customer rental as dates, actuals winning over
        plans. Either side may be False when the order is not dated yet; the
        window check then simply has nothing to compare on that side."""
        self.ensure_one()

        def as_date(value):
            return fields.Datetime.to_datetime(value).date() if value else False

        start = (as_date(self.actual_dispatch_datetime)
                 or as_date(self.planned_dispatch_datetime)
                 or as_date(self.actual_install_datetime)
                 or as_date(self.planned_install_datetime)
                 or as_date(self.date_requested))
        end = (as_date(self.actual_return_datetime)
               or as_date(self.planned_return_datetime))
        return start, end

    @api.model
    def _agreement_covers(self, agreement, start, end):
        """True when [start, end] sits completely inside the supplier period.
        A missing end date on either side means that side is open, so there is
        nothing on it to fall outside of."""
        if start and agreement.date_start and start < agreement.date_start:
            return False
        if end and agreement.date_end and end > agreement.date_end:
            return False
        return True

    def _check_within_supplier_window(self):
        """Raise if a third-party rental runs outside the supplier's period."""
        for order in self:
            if not order.asset_id or order.asset_id.owner_type != 'rented_in':
                continue
            if order.state in ('cancelled', 'closed'):
                continue
            start, end = order._customer_rental_window()
            agreement = order.sublet_agreement_id
            if not agreement:
                # No agreement is linked, which happens precisely when the
                # requested dates fall outside every rent-in period: the
                # auto-link searches for an agreement covering the order date
                # and finds none. Falling through here would let the worst
                # case - a booking entirely outside the supplier window -
                # pass unchecked, so validate against what the unit does have.
                candidates = order.asset_id.sublet_agreement_ids.filtered(
                    lambda ag: ag.state != 'cancelled')
                if not candidates:
                    # Nothing recorded to validate against at all. The
                    # commitment point is guarded by
                    # _check_supplier_rental_rights instead.
                    continue
                if any(order._agreement_covers(ag, start, end)
                       for ag in candidates):
                    continue
                # Report against the period the user most likely meant: the
                # unit's current agreement, else the latest one.
                agreement = order.asset_id.current_sublet_agreement_id or \
                    candidates.sorted(
                        key=lambda ag: (ag.date_start or fields.Date.today(), ag.id),
                        reverse=True)[0]
            asset_label = order.asset_id.display_name
            if start and agreement.date_start and start < agreement.date_start:
                raise ValidationError(_(
                    "This generator cannot be rented out before the start of "
                    "its rental from the supplier.\n\n"
                    "Equipment: %(asset)s\n"
                    "Supplier: %(supplier)s\n"
                    "Supplier rental period: %(sup_start)s → %(sup_end)s\n"
                    "Requested customer rental starts: %(start)s",
                    asset=asset_label,
                    supplier=agreement.vendor_id.display_name,
                    sup_start=format_date(self.env, agreement.date_start),
                    sup_end=(format_date(self.env, agreement.date_end)
                             if agreement.date_end else _("open-ended")),
                    start=format_date(self.env, start)))
            if end and agreement.date_end and end > agreement.date_end:
                raise ValidationError(_(
                    "This generator cannot be rented out beyond the end date of "
                    "its rental from the supplier.\n\n"
                    "Equipment: %(asset)s\n"
                    "Supplier: %(supplier)s\n"
                    "Supplier rental ends: %(sup_end)s\n"
                    "Requested customer rental ends: %(end)s",
                    asset=asset_label,
                    supplier=agreement.vendor_id.display_name,
                    sup_end=format_date(self.env, agreement.date_end),
                    end=format_date(self.env, end)))

    def _check_supplier_rental_rights(self):
        """Guard the commitment point: the company may not promise a
        supplier's unit to a customer without a live right to hold it."""
        for order in self:
            asset = order.asset_id
            if not asset or asset.owner_type != 'rented_in':
                continue
            if not order.sublet_agreement_id:
                raise UserError(_(
                    "Equipment %(asset)s is Third-Party equipment rented from "
                    "%(supplier)s, but no supplier rental agreement covers this "
                    "order. Record the supplier rental agreement (period and "
                    "cost) before reserving the unit for a customer.",
                    asset=asset.display_name,
                    supplier=asset.owner_partner_id.display_name or _("a supplier")))
            if asset.supplier_rental_status in ('expired', 'returned'):
                raise UserError(_(
                    "Equipment %(asset)s can no longer be rented out: its "
                    "rental from %(supplier)s is %(status)s.",
                    asset=asset.display_name,
                    supplier=asset.owner_partner_id.display_name or _("the supplier"),
                    status=dict(
                        asset._fields['supplier_rental_status'].selection
                    )[asset.supplier_rental_status]))

    @api.constrains('asset_id', 'sublet_agreement_id', 'date_requested',
                    'planned_dispatch_datetime', 'planned_install_datetime',
                    'planned_return_datetime', 'actual_dispatch_datetime',
                    'actual_install_datetime', 'actual_return_datetime')
    def _check_supplier_window_constraint(self):
        self._check_within_supplier_window()

    def action_reserve(self):
        # Ordered deliberately: prove the right to hold the unit, then prove
        # the dates fit inside it, then let the normal reservation run.
        # The buffer warning comes last and never blocks - a tight return is
        # a problem to plan around, not an illegal booking.
        self._check_supplier_rental_rights()
        self._check_within_supplier_window()
        res = super().action_reserve()
        self._post_supplier_buffer_warning()
        return res

    @api.constrains('sublet_agreement_id', 'asset_id')
    def _check_sublet_asset_match(self):
        for order in self:
            ag = order.sublet_agreement_id
            if ag and order.asset_id and ag.asset_id != order.asset_id:
                raise ValidationError(_(
                    "Rent-out order %s is linked to sublet agreement %s, but its "
                    "equipment (%s) does not match the agreement's unit (%s).")
                    % (order.name, ag.name, order.asset_id.display_name,
                       ag.asset_id.display_name))
