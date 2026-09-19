# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestRentalOrderReturn(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # These labels are asserted in Arabic. They used to be Arabic in the
        # source, which showed Arabic to English users too; they are English
        # terms now, so the suite runs in Arabic with the catalogue loaded.
        cls.env['res.lang']._activate_lang('ar_001')
        cls.env['ir.module.module'].search([
            ('name', '=', 'gr_rental_order'), ('state', '=', 'installed'),
        ])._update_translations(['ar_001'])
        cls.env = cls.env(context=dict(cls.env.context, lang='ar_001'))
        cls.Order = cls.env['gr.rental.order']
        cls.Asset = cls.env['gr.generator.asset']
        cls.Contract = cls.env['gr.rental.contract']
        cls.partner = cls.env['res.partner'].create({'name': 'ROR Customer'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'ROR Site', 'partner_id': cls.partner.id})

    def _contract(self):
        c = self.Contract.create({
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0, 'max_hours_per_day': 12.0,
            'base_daily_rate': 1000.0})
        return c

    def _order(self, **kw):
        vals = {
            'partner_id': self.partner.id,
            'site_id': self.site.id,
            'contract_id': self._contract().id,
            'asset_id': self.Asset.create({'name': 'ROR Gen'}).id,
        }
        vals.update(kw)
        return self.Order.create(vals)

    def _in_days(self, days):
        """A planned-return datetime N calendar days from today (user tz)."""
        today = fields.Date.context_today(self.env.user)
        return fields.Datetime.to_datetime(today) + timedelta(days=days)

    def test_far_ok_status(self):
        o = self._order(planned_return_datetime=self._in_days(7))
        self.assertEqual(o.rental_return_status, 'ok')
        self.assertEqual(o.rental_return_primary, '7 أيام')
        self.assertEqual(o.rental_return_secondary, 'لسه وقت على الإرجاع')

    def test_two_three_days_soon(self):
        o2 = self._order(planned_return_datetime=self._in_days(2))
        self.assertEqual(o2.rental_return_status, 'soon')
        self.assertEqual(o2.rental_return_primary, 'يومان')
        o3 = self._order(planned_return_datetime=self._in_days(3))
        self.assertEqual(o3.rental_return_status, 'soon')
        self.assertEqual(o3.rental_return_primary, '3 أيام')
        self.assertEqual(o3.rental_return_secondary, 'موعد الإرجاع قريب')

    def test_one_day_tomorrow(self):
        o = self._order(planned_return_datetime=self._in_days(1))
        self.assertEqual(o.rental_return_status, 'tomorrow')
        self.assertEqual(o.rental_return_primary, 'يوم واحد')
        self.assertEqual(o.rental_return_secondary, 'الإرجاع غدًا')

    def test_zero_days_today(self):
        o = self._order(planned_return_datetime=self._in_days(0))
        self.assertEqual(o.rental_return_status, 'today')
        self.assertEqual(o.rental_return_primary, 'اليوم')
        self.assertEqual(o.rental_return_secondary, 'موعد الإرجاع اليوم')

    def test_overdue(self):
        o = self._order(planned_return_datetime=self._in_days(-4))
        self.assertEqual(o.rental_return_status, 'overdue')
        self.assertEqual(o.rental_return_primary, 'متأخر 4 أيام')
        self.assertEqual(o.rental_return_secondary, 'متأخر عن موعد الإرجاع')

    def test_no_return_date_none(self):
        o = self._order()
        self.assertEqual(o.rental_return_status, 'none')
        self.assertFalse(o.rental_return_primary)

    def test_returned_done(self):
        o = self._order(planned_return_datetime=self._in_days(-2))
        o.state = 'returned'
        self.assertEqual(o.rental_return_status, 'done')
        self.assertEqual(o.rental_return_primary, 'تم الإرجاع')
        self.assertEqual(o.rental_return_secondary, 'اكتمل الإرجاع')

    def test_cancelled_hidden(self):
        o = self._order(planned_return_datetime=self._in_days(-2))
        o.state = 'cancelled'
        self.assertEqual(o.rental_return_status, 'none')

    def test_return_date_change_updates_status(self):
        o = self._order(planned_return_datetime=self._in_days(10))
        self.assertEqual(o.rental_return_status, 'ok')
        o.planned_return_datetime = self._in_days(1)
        self.assertEqual(o.rental_return_status, 'tomorrow')
        o.planned_return_datetime = self._in_days(-1)
        self.assertEqual(o.rental_return_status, 'overdue')

    def test_wizard_returns_info(self):
        o = self._order(planned_return_datetime=self._in_days(5))
        action = o.action_view_rental_return_info()
        self.assertEqual(
            action['res_model'], 'gr.rental.order.return.info.wizard')
        wiz = self.env['gr.rental.order.return.info.wizard'].with_context(
            default_order_id=o.id).create({'order_id': o.id})
        self.assertEqual(wiz.order_id, o)
        self.assertEqual(wiz.expected_return_date,
                         fields.Datetime.context_timestamp(
                             o, o.planned_return_datetime).date())
        self.assertEqual(wiz.current_date, fields.Date.context_today(o))
        self.assertEqual(wiz.remaining_days, o.rental_return_primary)
        self.assertEqual(wiz.return_status, o.rental_return_secondary)