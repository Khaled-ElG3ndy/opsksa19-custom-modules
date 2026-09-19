# -*- coding: utf-8 -*-
from datetime import date, datetime, timedelta
from unittest.mock import patch
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.addons.gr_return_alerts.models.gr_rental_order_alert import _working_days_between


@tagged('post_install', '-at_install')
class TestReturnAlerts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Order = cls.env['gr.rental.order']
        cls.Asset = cls.env['gr.generator.asset']
        cls.partner = cls.env['res.partner'].create({'name': 'Return Cust'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'Return Site', 'partner_id': cls.partner.id})
        cls.gm = cls.env['res.users'].create({
            'name': 'Ret GM', 'login': 'ret_gm', 'email': 'rgm@example.com',
            'group_ids': [(4, cls.env.ref('base.group_user').id),
                          (4, cls.env.ref('gr_security_base.group_generator_general_manager').id)]})
        cls.ops = cls.env['res.users'].create({
            'name': 'Ret Ops', 'login': 'ret_ops',
            'email': 'return.ops@example.com',
            'lang': 'en_US',
            'group_ids': [(4, cls.env.ref('base.group_user').id),
                          (4, cls.env.ref('gr_security_base.group_generator_operations_officer').id)]})
        cls.ops_ar = cls.env['res.users'].create({
            'name': 'Ret Ops Arabic', 'login': 'ret_ops_ar',
            'email': 'return.ops.ar@example.com',
            'lang': 'ar_001',
            'group_ids': [(4, cls.env.ref('base.group_user').id),
                          (4, cls.env.ref('gr_security_base.group_generator_operations_officer').id)]})

    def _order(self, state='on_rent', return_dt=None, user=False):
        a = self.Asset.create({'name': 'Ret Gen', 'pm_interval_hours': 2000.0})
        c = self.env['gr.rental.contract'].create({
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0, 'max_hours_per_day': 12.0,
            'base_daily_rate': 500.0})
        c.action_submit(); c.with_user(self.gm).action_approve(); c.action_activate()
        Order = self.Order.with_user(user) if user else self.Order
        o = Order.create({
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_id': c.id, 'asset_id': a.id,
            'planned_return_datetime': return_dt})
        o.write({'state': state})
        return o

    def _run_cron_on(self, today):
        patch_path = (
            'odoo.addons.gr_return_alerts.models.gr_rental_order_alert.'
            'fields.Date.context_today'
        )
        with patch(patch_path, return_value=today):
            return self.Order._cron_evaluate_returns()

    def _return_activities(self, order):
        return self.env['mail.activity'].search([
            ('res_model', '=', 'gr.rental.order'),
            ('res_id', '=', order.id),
        ])

    def _return_mails(self, order):
        return self.env['mail.mail'].search([
            ('model', '=', 'gr.rental.order'),
            ('res_id', '=', order.id),
        ])

    def _return_mail_recipient_count(self):
        users = self.env.ref(
            'gr_security_base.group_generator_operations_officer').user_ids
        return len(users.filtered(lambda user: user.email))

    # ---------- working-day math (Friday excluded) ----------
    def test_working_days_simple(self):
        # Mon 2026-01-05 to Wed 2026-01-07 = 2 working days
        self.assertEqual(_working_days_between(date(2026,1,5), date(2026,1,7)), 2)

    def test_working_days_skips_friday(self):
        # Thu 2026-01-08 to Sat 2026-01-10: Fri excluded -> Thu->Sat = 1 working day
        # days: Fri(skip), Sat(count) => 1
        self.assertEqual(_working_days_between(date(2026,1,8), date(2026,1,10)), 1)

    def test_working_days_overdue_negative(self):
        self.assertEqual(_working_days_between(date(2026,1,7), date(2026,1,5)), -2)

    def test_working_days_same_day(self):
        self.assertEqual(_working_days_between(date(2026,1,5), date(2026,1,5)), 0)

    # ---------- bucketing ----------
    def test_bucket_due_today(self):
        today = date(2026,1,6)  # Tuesday
        o = self._order(return_dt=datetime(2026,1,6,12,0))
        b,wd = o._compute_return_bucket_value(today)
        self.assertEqual(b, 'due_today')

    def test_bucket_due_3(self):
        today = date(2026,1,5)  # Monday
        o = self._order(return_dt=datetime(2026,1,7,12,0))  # Wed, 2 wd away
        b,wd = o._compute_return_bucket_value(today)
        self.assertEqual(b, 'due_3')

    def test_bucket_overdue(self):
        today = date(2026,1,8)
        o = self._order(return_dt=datetime(2026,1,5,12,0))
        b,wd = o._compute_return_bucket_value(today)
        self.assertEqual(b, 'overdue')
        self.assertLess(wd, 0)

    def test_bucket_none_when_far(self):
        today = date(2026,1,5)
        o = self._order(return_dt=datetime(2026,1,20,12,0))
        b,wd = o._compute_return_bucket_value(today)
        self.assertEqual(b, 'none')

    def test_bucket_none_when_not_out(self):
        today = date(2026,1,5)
        o = self._order(state='draft', return_dt=datetime(2026,1,6,12,0))
        b,wd = o._compute_return_bucket_value(today)
        self.assertEqual(b, 'none')

    def test_bucket_none_without_return_date(self):
        o = self._order(return_dt=False)
        b,wd = o._compute_return_bucket_value(date(2026,1,5))
        self.assertEqual(b, 'none')

    # ---------- cron end-to-end ----------
    def test_cron_writes_bucket_and_activity(self):
        o = self._order(return_dt=datetime.combine(date.today(), datetime.min.time()))
        self.Order._cron_evaluate_returns()
        o.invalidate_recordset()
        self.assertIn(o.return_bucket, ('due_today','due_3','overdue'))
        # an activity should be raised
        act = self.env['mail.activity'].search([
            ('res_model','=','gr.rental.order'),('res_id','=',o.id)])
        self.assertTrue(act)

    def test_cron_twice_same_hour_does_not_duplicate_activity_or_email(self):
        today = date(2026, 1, 6)
        o = self._order(return_dt=datetime(2026, 1, 6, 12, 0))
        self._run_cron_on(today)
        self._run_cron_on(today)
        o.invalidate_recordset()

        self.assertEqual(o.return_bucket, 'due_today')
        self.assertEqual(len(self._return_activities(o)), 1)
        self.assertEqual(
            len(self._return_mails(o)), self._return_mail_recipient_count())

    def test_cron_classifies_due_3_due_today_and_overdue(self):
        due3 = self._order(return_dt=datetime(2026, 1, 7, 12, 0))
        due_today = self._order(return_dt=datetime(2026, 1, 5, 12, 0))
        overdue = self._order(return_dt=datetime(2026, 1, 4, 12, 0))

        self._run_cron_on(date(2026, 1, 5))
        due3.invalidate_recordset()
        due_today.invalidate_recordset()
        overdue.invalidate_recordset()

        self.assertEqual(due3.return_bucket, 'due_3')
        self.assertEqual(due_today.return_bucket, 'due_today')
        self.assertEqual(overdue.return_bucket, 'overdue')

    def test_cron_transition_creates_each_stage_once(self):
        o = self._order(return_dt=datetime(2026, 1, 7, 12, 0))

        self._run_cron_on(date(2026, 1, 5))
        self._run_cron_on(date(2026, 1, 5))
        o.invalidate_recordset()
        self.assertEqual(o.return_bucket, 'due_3')
        self.assertEqual(len(self._return_activities(o)), 1)
        self.assertEqual(len(self._return_mails(o)), 0)

        self._run_cron_on(date(2026, 1, 7))
        self._run_cron_on(date(2026, 1, 7))
        o.invalidate_recordset()
        self.assertEqual(o.return_bucket, 'due_today')
        self.assertEqual(len(self._return_activities(o)), 2)
        expected_recipients = self._return_mail_recipient_count()
        self.assertEqual(len(self._return_mails(o)), expected_recipients)

        self._run_cron_on(date(2026, 1, 8))
        self._run_cron_on(date(2026, 1, 8))
        o.invalidate_recordset()
        self.assertEqual(o.return_bucket, 'overdue')
        self.assertEqual(len(self._return_activities(o)), 3)
        self.assertEqual(len(self._return_mails(o)), expected_recipients * 2)

    def test_activity_texts_follow_english_user_language(self):
        today = date(2026, 1, 5)
        o = self._order(
            return_dt=datetime(2026, 1, 7, 12, 0),
            user=self.ops)
        self._run_cron_on(today)
        activity = self._return_activities(o).filtered(
            lambda act: act.user_id == self.ops)
        self.assertEqual(len(activity), 1)
        self.assertEqual(
            activity.summary, 'Asset return due within 3 business days')
        self.assertIn(o.name, activity.note)
        self.assertIn(self.partner.display_name, activity.note)
        self.assertIn(o.asset_id.display_name, activity.note)
        self.assertIn(o.with_context(lang='en_US')._return_alert_due_date(),
                      activity.note)

    def test_activity_texts_follow_arabic_user_language(self):
        today = date(2026, 1, 6)
        o = self._order(
            return_dt=datetime(2026, 1, 6, 12, 0),
            user=self.ops_ar)
        self._run_cron_on(today)
        activity = self._return_activities(o).filtered(
            lambda act: act.user_id == self.ops_ar)
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.summary, 'الأصل مستحق الإرجاع اليوم')
        self.assertIn(o.name, activity.note)
        self.assertIn(self.partner.display_name, activity.note)
        self.assertIn(o.asset_id.display_name, activity.note)
        self.assertIn(o.with_context(lang='ar_001')._return_alert_due_date(),
                      activity.note)

    def test_clear_texts_for_all_return_stages(self):
        due3 = self._order(return_dt=datetime(2026, 1, 7, 12, 0))
        due_today = self._order(return_dt=datetime(2026, 1, 5, 12, 0))
        overdue = self._order(return_dt=datetime(2026, 1, 4, 12, 0))

        self._run_cron_on(date(2026, 1, 5))
        due3.invalidate_recordset()
        due_today.invalidate_recordset()
        overdue.invalidate_recordset()

        self.assertEqual(
            due3._return_alert_texts('due_3')['title'],
            'Asset return due within 3 business days')
        self.assertEqual(
            due_today._return_alert_texts('due_today')['title'],
            'Asset return is due today')
        overdue_texts = overdue._return_alert_texts('overdue')
        self.assertEqual(overdue_texts['title'], 'Asset return is overdue')
        self.assertIn(str(abs(overdue.working_days_to_return)),
                      overdue_texts['description'])

    def test_overdue_days_skip_friday(self):
        # Thu 2026-01-08 against Wed 2026-01-07 is one business day overdue.
        o = self._order(return_dt=datetime(2026, 1, 7, 12, 0))
        self._run_cron_on(date(2026, 1, 8))
        o.invalidate_recordset()
        self.assertEqual(o.return_bucket, 'overdue')
        self.assertEqual(abs(o.working_days_to_return), 1)

        # Sat 2026-01-10 against Thu 2026-01-08 skips Friday, so still one.
        o2 = self._order(return_dt=datetime(2026, 1, 8, 12, 0))
        self._run_cron_on(date(2026, 1, 10))
        o2.invalidate_recordset()
        self.assertEqual(o2.return_bucket, 'overdue')
        self.assertEqual(abs(o2.working_days_to_return), 1)
