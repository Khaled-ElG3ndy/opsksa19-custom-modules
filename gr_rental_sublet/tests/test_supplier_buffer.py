# -*- coding: utf-8 -*-
"""The supplier-return buffer warning.

Two rules that must never be confused, and these tests exist mostly to keep
them apart:

  * outside the supplier period  -> BLOCK   (a ValidationError, no rental)
  * inside it but no slack       -> WARN    (a level and a message, rental
                                             proceeds normally)

The buffer is the gap between the customer handing the unit back and the date
it is due back to the supplier: the time available to collect, inspect and
transport it.
"""
from datetime import date

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.gr_rental_sublet.models.gr_sublet_buffer import (
    PARAM_CRITICAL_DAYS, PARAM_WARNING_DAYS)


@tagged('post_install', '-at_install')
class TestSupplierReturnBuffer(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Asset = cls.env['gr.generator.asset']
        cls.Agreement = cls.env['gr.sublet.agreement']
        cls.Order = cls.env['gr.rental.order']
        cls.Buffer = cls.env['gr.sublet.buffer']

        cls.supplier = cls.env['res.partner'].create({'name': 'Buffer Supplier'})
        cls.customer = cls.env['res.partner'].create({'name': 'Buffer Customer'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'Buffer Site', 'partner_id': cls.customer.id})
        cls.gm = cls.env['res.users'].create({
            'name': 'Buffer GM', 'login': 'buffer_gm',
            'email': 'buffer_gm@example.com',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref(
                    'gr_security_base.group_generator_general_manager').id),
            ]})
        cls.rent_service = cls.env['product.product'].create({
            'name': 'Buffer Rent-in', 'type': 'service', 'purchase_ok': True,
            'standard_price': 1000.0})

        # Supplier period 01/08/2026 -> 31/08/2026 throughout.
        cls.supplier_end = date(2026, 8, 31)
        cls.third_party = cls.Asset.create({
            'name': 'GEN-BUF-001', 'pm_interval_hours': 2000.0,
            'owner_type': 'rented_in', 'owner_partner_id': cls.supplier.id})
        cls.owned = cls.Asset.create({
            'name': 'GEN-BUF-OWN', 'pm_interval_hours': 2000.0,
            'owner_type': 'owned'})
        cls.agreement = cls.Agreement.create({
            'asset_id': cls.third_party.id, 'vendor_id': cls.supplier.id,
            'rent_in_product_id': cls.rent_service.id, 'rent_in_amount': 1000.0,
            'date_start': date(2026, 8, 1), 'date_end': cls.supplier_end})

    def _order(self, asset, start, end):
        contract = self.env['gr.rental.contract'].create({
            'partner_id': self.customer.id, 'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0, 'max_hours_per_day': 12.0,
            'base_daily_rate': 500.0})
        contract.action_submit()
        contract.with_user(self.gm).action_approve()
        contract.action_activate()
        return self.Order.create({
            'partner_id': self.customer.id,
            'site_id': self.site.id,
            'contract_id': contract.id,
            'asset_id': asset.id,
            'date_requested': fields.Datetime.to_datetime(start),
            'planned_dispatch_datetime': fields.Datetime.to_datetime(start),
            'planned_return_datetime': fields.Datetime.to_datetime(end),
        })

    # ------------------------------------------------------------------
    # Test A - a comfortable buffer says nothing
    # ------------------------------------------------------------------
    def test_a_safe_buffer_is_silent(self):
        order = self._order(self.third_party, date(2026, 8, 5), date(2026, 8, 20))
        self.assertEqual(order.supplier_return_buffer_days, 11)
        self.assertEqual(order.supplier_buffer_level, 'ok')
        self.assertFalse(order.supplier_buffer_message,
                         "a comfortable buffer must not nag")

    # ------------------------------------------------------------------
    # Test B - two days of slack warns
    # ------------------------------------------------------------------
    def test_b_two_day_buffer_warns(self):
        order = self._order(self.third_party, date(2026, 8, 5), date(2026, 8, 29))
        self.assertEqual(order.supplier_return_buffer_days, 2)
        # Two days sits in the configured 0-2 critical band.
        self.assertEqual(order.supplier_buffer_level, 'critical')
        self.assertTrue(order.supplier_buffer_message)
        self.assertIn('2', order.supplier_buffer_message)

    def test_b2_mid_band_buffer_is_a_plain_warning(self):
        """Four days exercises the 3-5 band that Test B's two days skips."""
        order = self._order(self.third_party, date(2026, 8, 5), date(2026, 8, 27))
        self.assertEqual(order.supplier_return_buffer_days, 4)
        self.assertEqual(order.supplier_buffer_level, 'warning')
        self.assertTrue(order.supplier_buffer_message)

    # ------------------------------------------------------------------
    # Test C - same-day return is the strongest warning, but still legal
    # ------------------------------------------------------------------
    def test_c_zero_buffer_warns_hardest_without_blocking(self):
        order = self._order(self.third_party, date(2026, 8, 5), self.supplier_end)
        self.assertEqual(order.supplier_return_buffer_days, 0)
        self.assertEqual(order.supplier_buffer_level, 'critical')
        self.assertTrue(order.supplier_buffer_message)
        # Legal: the rental ends inside the supplier period, so it reserves.
        order.with_context(skip_customer_approval_lock=True).state = 'confirmed'
        order.action_reserve()
        self.assertEqual(order.state, 'reserved')
        # And the warning is left in the chatter, not only on the form.
        bodies = ' '.join(order.message_ids.mapped('body'))
        self.assertIn('no return buffer', bodies.lower())

    # ------------------------------------------------------------------
    # Test D - past the supplier end date is still a hard block
    # ------------------------------------------------------------------
    def test_d_beyond_supplier_end_is_blocked_not_warned(self):
        with self.assertRaises(ValidationError) as caught:
            self._order(self.third_party, date(2026, 8, 5), date(2026, 9, 5))
        self.assertIn('beyond the end date', str(caught.exception))

    # ------------------------------------------------------------------
    # Test E - owned equipment has no supplier to return anything to
    # ------------------------------------------------------------------
    def test_e_owned_generator_never_warns(self):
        order = self._order(self.owned, date(2026, 8, 5), date(2026, 8, 31))
        self.assertFalse(order.supplier_buffer_level)
        self.assertFalse(order.supplier_buffer_message)
        self.assertEqual(order.supplier_return_buffer_days, 0)
        self.assertFalse(order.asset_is_third_party)

    def test_e2_open_ended_supplier_period_has_no_buffer_to_judge(self):
        self.agreement.date_end = False
        order = self._order(self.third_party, date(2026, 8, 5), date(2026, 12, 1))
        self.assertFalse(order.supplier_buffer_level,
                         "with no supplier end date there is nothing to warn about")

    # ------------------------------------------------------------------
    # The thresholds are policy, and policy is configurable
    # ------------------------------------------------------------------
    def test_thresholds_come_from_configuration(self):
        self.assertEqual(self.Buffer._buffer_thresholds(), (2, 5))
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param(PARAM_CRITICAL_DAYS, '5')
        Param.set_param(PARAM_WARNING_DAYS, '10')
        self.assertEqual(self.Buffer._buffer_thresholds(), (5, 10))
        # A four-day buffer was a plain warning above; under the wider policy
        # the same rental is critical.
        order = self._order(self.third_party, date(2026, 8, 5), date(2026, 8, 27))
        self.assertEqual(order.supplier_buffer_level, 'critical')

    def test_broken_configuration_falls_back_to_defaults(self):
        """A bad parameter must not be able to break a rental order form."""
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param(PARAM_CRITICAL_DAYS, 'not-a-number')
        self.assertEqual(self.Buffer._buffer_thresholds(), (2, 5))

    def test_warning_band_never_falls_below_critical_band(self):
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param(PARAM_CRITICAL_DAYS, '7')
        Param.set_param(PARAM_WARNING_DAYS, '3')
        critical, warning = self.Buffer._buffer_thresholds()
        self.assertGreaterEqual(warning, critical)
        self.assertEqual(self.Buffer._buffer_level(5), 'critical')

    # ------------------------------------------------------------------
    # The unit shows the buffer of whichever rental currently holds it
    # ------------------------------------------------------------------
    def test_buffer_is_visible_on_the_equipment_record(self):
        order = self._order(self.third_party, date(2026, 8, 5), date(2026, 8, 29))
        order.with_context(skip_customer_approval_lock=True).state = 'confirmed'
        order.action_reserve()
        self.third_party.invalidate_recordset()
        self.assertEqual(self.third_party.current_rental_order_id, order)
        self.assertEqual(self.third_party.supplier_buffer_level, 'critical')
        self.assertTrue(self.third_party.supplier_buffer_message)

    def test_extending_the_customer_return_recomputes_the_buffer(self):
        order = self._order(self.third_party, date(2026, 8, 5), date(2026, 8, 10))
        self.assertEqual(order.supplier_buffer_level, 'ok')
        order.planned_return_datetime = fields.Datetime.to_datetime(
            date(2026, 8, 30))
        self.assertEqual(order.supplier_return_buffer_days, 1)
        self.assertEqual(order.supplier_buffer_level, 'critical')
