# -*- coding: utf-8 -*-
import base64
from datetime import timedelta
from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from odoo.tests import tagged

_SIG = base64.b64encode(b'return-signature-data')


@tagged('post_install', '-at_install')
class TestHourLog(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Log = cls.env['gr.hour.log']
        cls.partner = cls.env['res.partner'].create({'name': 'HL Customer'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'HL Site', 'partner_id': cls.partner.id})
        # Stateless role users, created once and reused (logins are globally
        # unique on res.users, so per-test creation would collide).
        cls.gm_user = cls.env['res.users'].create({
            'name': 'HL GM', 'login': 'hl_gm', 'email': 'hl_gm@example.com',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref('gr_security_base.group_generator_general_manager').id),
            ]})
        cls.basic_user = cls.env['res.users'].create({
            'name': 'HL User', 'login': 'hl_user', 'email': 'hl_user@example.com',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref('gr_security_base.group_generator_user').id),
            ]})

    def _gm(self):
        return self.gm_user

    def _basic_user(self):
        return self.basic_user

    def _contract(self, included=8.0, mx=12.0):
        c = self.env['gr.rental.contract'].create({
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': included, 'max_hours_per_day': mx,
            'base_daily_rate': 1000.0})
        c.action_submit()
        c.with_user(self._gm()).action_approve()
        c.action_activate()
        return c

    def _asset(self, meter=0.0, pm=250.0):
        return self.env['gr.generator.asset'].create({
            'name': 'HL Gen', 'pm_interval_hours': pm, 'current_hour_meter': meter})

    def _order_on_rent(self, asset, contract, start_meter=0.0):
        o = self.env['gr.rental.order'].create({
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_id': contract.id, 'asset_id': asset.id})
        o.action_confirm(); o.action_reserve()
        insp = self.env['gr.rental.inspection'].create({'rental_order_id': o.id, 'mode': 'delivery'})
        insp._populate_default_checklist(); insp.action_pass()
        o.action_dispatch()
        o.start_meter_reading = start_meter
        o.action_install(); o.action_start_rental()
        return o

    def _order_closed(self, asset, contract, start_meter=0.0, end_meter=0.0):
        o = self._order_on_rent(asset, contract, start_meter=start_meter)
        o.end_meter_reading = end_meter
        if 'rental_workflow_requires_return_signature' in o._fields:
            o.invalidate_recordset()
            if o.rental_workflow_requires_return_signature:
                o.customer_return_signature = _SIG
        o.action_return()
        ret = o.inspection_ids.filtered(lambda i: i.mode == 'return')
        ret.action_pass()
        o.action_start_inspection()
        o.action_close()
        return o

    def _make_log(self, order, current, day_offset=1, days_span=1, prev_meter=0.0):
        """Create a log relative to TODAY so it never predates the install date.
        day_offset = days after install for this reading.
        days_span  = whole days this reading covers (sets previous_reading_date).
        Previous values are passed into create() so they are set before the
        date/meter constraints run."""
        base = fields.Date.context_today(self.Log)
        reading_date = base + timedelta(days=day_offset)
        prev_date = reading_date - timedelta(days=days_span)
        log = self.Log.create({
            'rental_order_id': order.id,
            'current_meter_reading': current,
            'reading_date': reading_date,
            'previous_meter_reading': prev_meter,
            'previous_reading_date': prev_date,
        })
        return log

    # ---------- calculation: single day ----------
    def test_regular_only(self):
        c = self._contract(8.0, 12.0)
        a = self._asset(meter=100.0)
        o = self._order_on_rent(a, c, start_meter=100.0)
        # used 6h in 1 day: all regular
        log = self._make_log(o, 106.0, days_span=1, prev_meter=100.0)
        self.assertEqual(log.days_covered, 1)
        self.assertEqual(log.used_hours, 6.0)
        self.assertEqual(log.regular_hours, 6.0)
        self.assertEqual(log.overtime_hours, 0.0)
        self.assertEqual(log.violation_hours, 0.0)
        self.assertFalse(log.has_violation)

    def test_closed_order_can_seed_final_log(self):
        c = self._contract(8.0, 12.0)
        a = self._asset(meter=200.0)
        o = self._order_closed(a, c, start_meter=200.0, end_meter=250.0)
        self.assertEqual(o.state, 'closed')

        log_form = self.Log.new({'rental_order_id': o.id})
        log_form._onchange_rental_order_id_seed_readings()
        self.assertEqual(log_form.previous_meter_reading, 200.0)
        self.assertEqual(log_form.current_meter_reading, 250.0)
        self.assertEqual(log_form.previous_reading_date, o.actual_install_datetime.date())

        log = self.Log.create({
            'rental_order_id': o.id,
            'reading_date': fields.Date.context_today(self.Log),
            'current_meter_reading': 250.0,
        })
        self.assertEqual(log.previous_meter_reading, 200.0)
        self.assertEqual(log.used_hours, 50.0)

    def test_overtime_band(self):
        c = self._contract(8.0, 12.0)
        a = self._asset(meter=0.0)
        o = self._order_on_rent(a, c, start_meter=0.0)
        # used 10h: 8 regular + 2 overtime, 0 violation
        log = self._make_log(o, 10.0, days_span=1, prev_meter=0.0)
        self.assertEqual(log.regular_hours, 8.0)
        self.assertEqual(log.overtime_hours, 2.0)
        self.assertEqual(log.violation_hours, 0.0)

    def test_violation_band(self):
        c = self._contract(8.0, 12.0)
        a = self._asset(meter=0.0)
        o = self._order_on_rent(a, c, start_meter=0.0)
        # used 15h: 8 regular + 4 overtime + 3 violation
        log = self._make_log(o, 15.0, days_span=1, prev_meter=0.0)
        self.assertEqual(log.regular_hours, 8.0)
        self.assertEqual(log.overtime_hours, 4.0)
        self.assertEqual(log.violation_hours, 3.0)
        self.assertTrue(log.has_violation)

    # ---------- calculation: multi-day scaling ----------
    def test_multiday_scaling(self):
        c = self._contract(8.0, 12.0)
        a = self._asset(meter=0.0)
        o = self._order_on_rent(a, c, start_meter=0.0)
        # 3 days: included 24, max 36. used 40h -> 24 reg + 12 ot + 4 violation
        log = self._make_log(o, 40.0, days_span=3, prev_meter=0.0)
        self.assertEqual(log.days_covered, 3)
        self.assertEqual(log.included_allowance, 24.0)
        self.assertEqual(log.max_allowance, 36.0)
        self.assertEqual(log.regular_hours, 24.0)
        self.assertEqual(log.overtime_hours, 12.0)
        self.assertEqual(log.violation_hours, 4.0)

    # ---------- meter constraints ----------
    def test_meter_below_previous_blocked(self):
        c = self._contract()
        a = self._asset(meter=50.0)
        o = self._order_on_rent(a, c, start_meter=50.0)
        with self.assertRaises(ValidationError):
            self._make_log(o, 40.0, days_span=1, prev_meter=50.0)

    def test_reading_date_before_previous_blocked(self):
        c = self._contract()
        a = self._asset(meter=0.0)
        o = self._order_on_rent(a, c, start_meter=0.0)
        base = fields.Date.context_today(self.Log)
        with self.assertRaises(ValidationError):
            # reading_date deliberately earlier than previous_reading_date
            self.Log.create({
                'rental_order_id': o.id,
                'current_meter_reading': 10.0,
                'reading_date': base + timedelta(days=1),
                'previous_meter_reading': 0.0,
                'previous_reading_date': base + timedelta(days=5),
            })

    # ---------- violation approval gate ----------
    def test_violation_requires_manager(self):
        c = self._contract(8.0, 12.0)
        a = self._asset(meter=0.0)
        o = self._order_on_rent(a, c, start_meter=0.0)
        log = self._make_log(o, 20.0, days_span=1, prev_meter=0.0)
        log.action_submit()
        self.assertTrue(log.has_violation)
        # basic user cannot approve a violating log
        with self.assertRaises(UserError):
            log.with_user(self._basic_user()).action_approve()
        # GM can
        log.with_user(self._gm()).action_approve()
        self.assertEqual(log.state, 'approved')

    def test_non_violation_any_user_approves(self):
        c = self._contract(8.0, 12.0)
        a = self._asset(meter=0.0)
        o = self._order_on_rent(a, c, start_meter=0.0)
        log = self._make_log(o, 6.0, days_span=1, prev_meter=0.0)
        log.action_submit()
        self.assertFalse(log.has_violation)
        log.action_approve()  # current admin user fine
        self.assertEqual(log.state, 'approved')

    # ---------- asset integration on approval ----------
    def test_approval_advances_asset_meter(self):
        c = self._contract()
        a = self._asset(meter=100.0, pm=250.0)
        o = self._order_on_rent(a, c, start_meter=100.0)
        log = self._make_log(o, 108.0, days_span=1, prev_meter=100.0)
        log.action_submit(); log.action_approve()
        self.assertEqual(a.current_hour_meter, 108.0)

    def test_approval_auto_maintenance_due(self):
        # pm interval 250, asset at 240; a log to 260 crosses the PM threshold.
        # 20h used also breaches the 12h/day max, so a manager approves it.
        c = self._contract()
        a = self._asset(meter=240.0, pm=250.0)
        self.assertEqual(a.status, 'available')
        o = self._order_on_rent(a, c, start_meter=240.0)
        # After install the asset is on_rent (the auto-flip only affects an
        # 'available' asset); here we verify the meter advances and the asset
        # becomes maintenance-overdue (computed) after crossing the PM hour.
        log = self._make_log(o, 260.0, days_span=1, prev_meter=240.0)
        log.action_submit()
        log.with_user(self._gm()).action_approve()
        self.assertEqual(a.current_hour_meter, 260.0)
        self.assertTrue(a.maintenance_overdue)

    def test_approval_meter_no_rollback(self):
        # The asset meter is AHEAD of this log's reading; approval must not roll
        # it back. PM interval large so the asset is not overdue (stays available).
        c = self._contract()
        a = self._asset(meter=500.0, pm=2000.0)
        o = self._order_on_rent(a, c, start_meter=500.0)
        # Asset advanced further (e.g. another rental/meter event) to 600.
        a.with_context(gr_meter_correction=True).write({'current_hour_meter': 600.0})
        # This log reads 520 (below the asset's 600).
        log = self._make_log(o, 520.0, days_span=1, prev_meter=500.0)
        log.action_submit()
        log.with_user(self._gm()).action_approve()
        # asset stays at 600 (no rollback to 520)
        self.assertEqual(a.current_hour_meter, 600.0)

    # ---------- approval lock + correction ----------
    def test_approved_log_locked(self):
        c = self._contract()
        a = self._asset(meter=0.0)
        o = self._order_on_rent(a, c, start_meter=0.0)
        log = self._make_log(o, 6.0, days_span=1, prev_meter=0.0)
        log.action_submit(); log.action_approve()
        with self.assertRaises(UserError):
            log.write({'current_meter_reading': 9.0})

    def test_correction_wizard_applies(self):
        c = self._contract()
        a = self._asset(meter=0.0)
        o = self._order_on_rent(a, c, start_meter=0.0)
        log = self._make_log(o, 6.0, days_span=1, prev_meter=0.0)
        log.action_submit(); log.action_approve()
        wiz = self.env['gr.hour.log.correction.wizard'].create({
            'log_id': log.id, 'current_meter_reading': 7.0,
            'reading_date': log.reading_date, 'reason': 'meter misread'})
        wiz.action_apply()
        self.assertEqual(log.current_meter_reading, 7.0)

    # ---------- sequence ----------
    def test_sequence_assigned(self):
        c = self._contract()
        a = self._asset(meter=0.0)
        o = self._order_on_rent(a, c, start_meter=0.0)
        log = self._make_log(o, 5.0, days_span=1, prev_meter=0.0)
        self.assertTrue(log.name.startswith('GR/HLOG/'))

    # ---------- cancel rules ----------
    def test_cannot_cancel_approved(self):
        c = self._contract()
        a = self._asset(meter=0.0)
        o = self._order_on_rent(a, c, start_meter=0.0)
        log = self._make_log(o, 5.0, days_span=1, prev_meter=0.0)
        log.action_submit(); log.action_approve()
        with self.assertRaises(UserError):
            log.action_cancel()
