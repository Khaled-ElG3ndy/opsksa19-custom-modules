# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class GrRentalOrderReturn(models.Model):
    """Expected-return countdown shown as a smart button on the rental order.

    The expected return date source is the EXISTING ``planned_return_datetime``
    (Datetime) field on ``gr.rental.order``. The item lines
    (``gr.rental.order.line``) do not carry their own return dates, so an order
    always has a single expected return date; "nearest upcoming / earliest
    overdue" therefore reduces to the order-level planned return date.

    States considered "fully returned": ``returned``, ``inspection``, ``closed``.
    ``cancelled`` orders hide the button entirely. The countdown is shown for
    any other state (draft -> off_hire_requested) that has a planned return
    date, matching the requirement "active = not cancelled, not fully returned,
    has a valid expected return date".
    """
    _inherit = 'gr.rental.order'

    _RENTAL_RETURNED_STATES = ('returned', 'inspection', 'closed')

    # Non-stored computed fields (recomputed at read time, see read()):
    # the day count must reflect the CURRENT date without an editing event,
    # so storing them would go stale at midnight unless a cron rewrote them.
    rental_return_status = fields.Selection([
        ('none', 'No Return Date'),
        ('ok', 'Return Far'),
        ('soon', 'Return Soon'),
        ('tomorrow', 'Return Tomorrow'),
        ('today', 'Return Today'),
        ('overdue', 'Overdue'),
        ('done', 'Returned'),
    ], string='Return Countdown Status', compute='_compute_rental_return',
        help="Drives the colour of the return smart button. "
             "ok=green, soon=amber, tomorrow=orange, today=red-orange, "
             "overdue=red, done=gray.")
    rental_return_primary = fields.Char(
        string='Return Primary Text', compute='_compute_rental_return',
        help="Large value of the smart button, e.g. \"7 days\" or "
             "\"Overdue by 3 days\".")
    rental_return_secondary = fields.Char(
        string='Return Secondary Text', compute='_compute_rental_return',
        help="Small status line of the smart button.")

    _RENTAL_RETURN_FIELDS = (
        'rental_return_status',
        'rental_return_primary',
        'rental_return_secondary')

    @api.depends('state', 'planned_return_datetime',
                 'actual_return_datetime')
    def _compute_rental_return(self):
        """Calendar-day countdown to the planned return.

        The date is compared in the user/company timezone:
        - ``today`` = ``fields.Date.context_today``
        - ``due``   = planned return datetime converted to the user's local
          calendar date via ``context_timestamp``.
        """
        for o in self:
            if o.state == 'cancelled':
                o.rental_return_status = 'none'
                o.rental_return_primary = False
                o.rental_return_secondary = False
                continue
            if o.state in self._RENTAL_RETURNED_STATES:
                o.rental_return_status = 'done'
                o.rental_return_primary = _('Returned')
                o.rental_return_secondary = _('Return completed')
                continue
            if not o.planned_return_datetime:
                o.rental_return_status = 'none'
                o.rental_return_primary = False
                o.rental_return_secondary = False
                continue
            today = fields.Date.context_today(o)
            due = fields.Datetime.context_timestamp(
                o, o.planned_return_datetime).date()
            remaining = (due - today).days
            if remaining > 3:
                o.rental_return_status = 'ok'
                o.rental_return_primary = o._day_count_label(remaining)
                o.rental_return_secondary = _('Still time before return')
            elif remaining in (2, 3):
                o.rental_return_status = 'soon'
                o.rental_return_primary = o._day_count_label(remaining)
                o.rental_return_secondary = _('Return is due soon')
            elif remaining == 1:
                o.rental_return_status = 'tomorrow'
                o.rental_return_primary = _('One day')
                o.rental_return_secondary = _('Return is due tomorrow')
            elif remaining == 0:
                o.rental_return_status = 'today'
                o.rental_return_primary = _('Today')
                o.rental_return_secondary = _('Return is due today')
            else:
                o.rental_return_status = 'overdue'
                o.rental_return_primary = _('Overdue by %s') % o._day_count_label(
                    -remaining)
                o.rental_return_secondary = _('Past the return date')

    @api.model
    def _day_count_label(self, count):
        """Localised "N days" for a (non-negative) count.

        Arabic distinguishes one/two/few/many, so the branches stay; each
        branch is a separate catalogue term rather than a hardcoded string.
        """
        count = int(round(abs(count)))
        if count == 0:
            return _('Today')
        if count == 1:
            return _('One day')
        if count == 2:
            return _('Two days')
        if count <= 10:
            return _('%s days') % count
        return _('%s day(s)') % count

    def read(self, fields=None, load='_classic_read'):
        """Refresh the day-count fields on every read.

        A computed field depending only on ``@api.depends`` is not recomputed
        automatically when the calendar day changes and no record is edited,
        which would leave the smart button stale at midnight. Instead of a daily
        cron (and without writing anything), we invalidate the three display
        fields before every read so the next access recomputes them with the
        current date. The computation is cheap and touches no stored data.
        """
        if self and (fields is None or any(
                f in fields for f in self._RENTAL_RETURN_FIELDS)):
            self.invalidate_recordset(fnames=self._RENTAL_RETURN_FIELDS)
        return super().read(fields, load)

    def action_view_rental_return_info(self):
        """Open a small read-only summary of the return timing."""
        self.ensure_one()
        return {
            'name': _('Expected Return Info'),
            'type': 'ir.actions.act_window',
            'res_model': 'gr.rental.order.return.info.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id},
        }