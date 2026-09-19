# -*- coding: utf-8 -*-
"""The supplier-return buffer: one definition, used everywhere.

Two different questions are asked about a third-party rental, and they must
not be confused:

  * "May we rent it out at all?"  - the hard rule. A customer rental that runs
    past the supplier rental end is refused outright (see
    gr.rental.order._check_within_supplier_window).

  * "How comfortable is the return?" - this file. The rental is legal, but the
    gap between getting the unit back from the customer and handing it back to
    the supplier may be too small to collect, inspect and transport it. That
    is an operational warning, never a block.

The thresholds are policy, not physics, so they live in ir.config_parameter
the same way the dashboard's readiness target does, and every screen reads
them through the one helper below.
"""
from odoo import api, models, _

# Whole days of slack between the customer return and the supplier due-back
# date. Defaults only: an administrator overrides them under
# Settings > Technical > System Parameters.
DEFAULT_CRITICAL_DAYS = 2
DEFAULT_WARNING_DAYS = 5

PARAM_CRITICAL_DAYS = 'gr_rental_sublet.supplier_buffer_critical_days'
PARAM_WARNING_DAYS = 'gr_rental_sublet.supplier_buffer_warning_days'

# Shown wherever the buffer is displayed. False (not set) means the question
# does not apply: an owned unit, or a rental with no supplier end date.
BUFFER_LEVEL_SELECTION = [
    ('critical', 'Critical - No Return Buffer'),
    ('warning', 'Tight Return Buffer'),
    ('ok', 'Comfortable Return Buffer'),
]


class GrSubletBuffer(models.AbstractModel):
    """Holder for the buffer policy so any model can reach it through the
    registry without importing across modules."""
    _name = 'gr.sublet.buffer'
    _description = 'Supplier Return Buffer Policy'

    @api.model
    def _buffer_thresholds(self):
        """(critical_days, warning_days), read once from configuration.

        A malformed parameter falls back to the default rather than raising:
        a bad setting must not be able to break a rental order form.
        """
        Param = self.env['ir.config_parameter'].sudo()

        def whole_days(key, default):
            try:
                return max(0, int(float(Param.get_param(key, default))))
            except (TypeError, ValueError):
                return default

        critical = whole_days(PARAM_CRITICAL_DAYS, DEFAULT_CRITICAL_DAYS)
        warning = whole_days(PARAM_WARNING_DAYS, DEFAULT_WARNING_DAYS)
        # A warning band below the critical band would leave a gap no level
        # describes, so keep them ordered whatever the parameters say.
        return critical, max(critical, warning)

    @api.model
    def _buffer_level(self, buffer_days):
        """Classify a buffer in whole days.

        Negative days are outside the supplier period, which is a blocking
        condition handled elsewhere; classified as critical here so that if a
        record ever reaches a screen in that state it shows as the worst case
        rather than as comfortable.
        """
        if buffer_days is None:
            return False
        critical, warning = self._buffer_thresholds()
        if buffer_days <= critical:
            return 'critical'
        if buffer_days <= warning:
            return 'warning'
        return 'ok'

    @api.model
    def _buffer_message(self, buffer_days, level):
        """The operator-facing sentence for a buffer, or False when calm."""
        if not level or level == 'ok':
            return False
        if buffer_days < 0:
            return _(
                "The customer rental ends after the unit is due back to the "
                "supplier.")
        if buffer_days == 0:
            return _(
                "Warning: the generator is returned by the customer on the "
                "same day it is due back to the supplier. There is no return "
                "buffer at all.")
        if buffer_days == 1:
            return _(
                "Warning: the customer return date is very close to the date "
                "the generator is due back to the supplier. Only one day "
                "remains.")
        return _(
            "Warning: the customer return date is close to the date the "
            "generator is due back to the supplier. Only %s days remain.",
            buffer_days)
