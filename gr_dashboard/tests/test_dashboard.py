# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestDashboardMetrics(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Asset = cls.env['gr.generator.asset']
        cls.Log = cls.env['gr.hour.log']
        cls.partner = cls.env['res.partner'].create({'name': 'Dash Customer'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'Dash Site', 'partner_id': cls.partner.id})
        cls.gm = cls.env['res.users'].create({
            'name': 'Dash GM', 'login': 'dash_gm', 'email': 'dgm@example.com',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref('gr_security_base.group_generator_general_manager').id),
            ]})

    def _contract(self):
        c = self.env['gr.rental.contract'].create({
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0, 'max_hours_per_day': 12.0,
            'base_daily_rate': 1000.0, 'overtime_hour_rate': 50.0})
        c.action_submit(); c.with_user(self.gm).action_approve(); c.action_activate()
        return c

    def _order(self, contract, asset, start=0.0):
        o = self.env['gr.rental.order'].create({
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_id': contract.id, 'asset_id': asset.id})
        o.action_confirm(); o.action_reserve()
        insp = self.env['gr.rental.inspection'].create({'rental_order_id': o.id, 'mode': 'delivery'})
        insp._populate_default_checklist(); insp.action_pass()
        o.action_dispatch()
        o.start_meter_reading = start
        o.action_install(); o.action_start_rental()
        return o

    def _approved_log(self, order, current, prev_meter=0.0):
        base = fields.Date.context_today(self.Log)
        log = self.Log.create({
            'rental_order_id': order.id,
            'current_meter_reading': current,
            'reading_date': base + timedelta(days=1),
            'previous_meter_reading': prev_meter,
            'previous_reading_date': base,
        })
        log.action_submit(); log.with_user(self.gm).action_approve()
        return log

    def _fleet_metrics(self):
        return self.env['gr.dashboard.card']._fleet_data()

    @staticmethod
    def _metric_count(value):
        return int((value or '0 / 0').split(' / ', 1)[0].replace(',', ''))

    @staticmethod
    def _metric_total(value):
        return int((value or '0 / 0').split(' / ', 1)[1].split(' ', 1)[0].replace(',', ''))

    @classmethod
    def _arabic_env(cls):
        """Arabic has to be active AND the module retranslated: activating a
        language does not backfill catalogues for modules installed before it."""
        cls.env['res.lang']._activate_lang('ar_001')
        cls.env['ir.module.module'].search([
            ('name', '=', 'gr_dashboard'), ('state', '=', 'installed'),
        ])._update_translations(['ar_001'])
        return cls.env(context=dict(cls.env.context, lang='ar_001'))

    def test_fleet_card_arabic_title(self):
        env = self._arabic_env()
        card = env['gr.dashboard.card'].search([('card_key', '=', 'fleet')], limit=1)
        self.assertEqual(card.title, 'حالة المولدات')

    def test_sublet_margin_card_replaces_duplicate_distribution(self):
        cards = self.env['gr.dashboard.card'].search([])
        keys = cards.mapped('card_key')
        self.assertIn('sublet_margin', keys)
        self.assertNotIn('distribution', keys)
        sublet_card = cards.filtered(lambda card: card.card_key == 'sublet_margin')
        self.assertEqual(
            sublet_card.action_xml_id,
            'gr_rental_sublet.action_gr_sublet_margin')

    def test_sublet_margin_card_arabic_terms(self):
        env = self._arabic_env()
        card = env['gr.dashboard.card'].search(
            [('card_key', '=', 'sublet_margin')], limit=1)
        self.assertEqual(card.title, 'ملخص هامش التأجير من الغير')
        self.assertEqual(card.primary_label, 'صافي الهامش')
        self.assertEqual(card.metric_1_label, 'الإيراد الخارج')
        self.assertEqual(card.trend_label, 'عرض تحليل الهامش')

    def test_forecast_missing_dates_text_is_readable(self):
        Dashboard = self.env['gr.dashboard.card']
        self.assertEqual(
            Dashboard._fmt('%s of %s contracts missing start dates', 2, 9),
            '2 of 9 contracts missing start dates')
        env = self._arabic_env()
        self.assertEqual(
            env['gr.dashboard.card']._fmt(
                env._('%s of %s contracts missing start dates'), 2, 9),
            '2 من 9 عقود بدون تاريخ بداية')

    def test_money_uses_currency_suffix(self):
        Dashboard = self.env['gr.dashboard.card']
        currency = self.env.company.currency_id
        is_sar = (currency.symbol or '').upper() in ('RS', 'SAR') or currency.name == 'SAR'
        expected_symbol = 'SR' if is_sar else (currency.symbol or currency.name or '')
        self.assertEqual(Dashboard._money(5010.0, currency), '5.01K %s' % expected_symbol)

    def test_fleet_card_status_buckets_are_complete(self):
        before = self._fleet_metrics()
        before_utilized = self._metric_count(before['metric_1_value'])
        before_available = self._metric_count(before['metric_2_value'])
        before_maintenance = self._metric_count(before['metric_3_value'])
        before_out = self._metric_count(before['metric_4_value'])
        before_total = self._metric_total(before['metric_1_value'])

        for status in (
                'reserved', 'in_transit', 'installed', 'on_rent',
                'available',
                'maintenance_due', 'under_maintenance', 'returned_pending_inspection',
                'breakdown', 'unavailable',
                'retired'):
            self.Asset.create({'name': 'Dash Fleet %s' % status, 'status': status})
        self.Asset.create({
            'name': 'Dash Fleet archived',
            'status': 'on_rent',
            'active': False,
        })

        after = self._fleet_metrics()
        after_utilized = self._metric_count(after['metric_1_value'])
        after_available = self._metric_count(after['metric_2_value'])
        after_maintenance = self._metric_count(after['metric_3_value'])
        after_out = self._metric_count(after['metric_4_value'])
        after_total = self._metric_total(after['metric_1_value'])

        self.assertEqual(after_utilized - before_utilized, 4)
        self.assertEqual(after_available - before_available, 1)
        self.assertEqual(after_maintenance - before_maintenance, 3)
        self.assertEqual(after_out - before_out, 2)
        self.assertEqual(after_total - before_total, 10)
        self.assertEqual(
            after_total,
            after_utilized + after_available + after_maintenance + after_out)

    def test_utilization_from_logs(self):
        a = self.Asset.create({'name': 'D1', 'pm_interval_hours': 2000.0,
                               'current_hour_meter': 0.0})
        c = self._contract()
        o = self._order(c, a, start=0.0)
        self._approved_log(o, 10.0, prev_meter=0.0)  # 10 used hours
        a.invalidate_recordset()
        self.assertEqual(a.live_utilization_hours, 10.0)

    def test_revenue_from_invoices(self):
        a = self.Asset.create({'name': 'D2', 'pm_interval_hours': 2000.0,
                               'current_hour_meter': 0.0})
        c = self._contract()
        o = self._order(c, a, start=0.0)
        self._approved_log(o, 10.0, prev_meter=0.0)
        # generate a draft invoice via a billing run
        base = fields.Date.context_today(self.env['gr.billing.run'])
        run = self.env['gr.billing.run'].create({
            'date_from': base - timedelta(days=2),
            'date_to': base + timedelta(days=2)})
        run.action_generate()
        a.invalidate_recordset()
        # revenue should be the invoice's untaxed total (base daily + overtime)
        self.assertGreater(a.live_revenue, 0.0)

    def test_cost_zero_until_parts(self):
        a = self.Asset.create({'name': 'D3', 'pm_interval_hours': 2000.0})
        self.assertEqual(a.live_cost, 0.0)
        self.assertEqual(a.live_profit_estimate, a.live_revenue)

    def test_open_job_count(self):
        a = self.Asset.create({'name': 'D4', 'pm_interval_hours': 2000.0})
        job = self.env['gr.maintenance.job'].create({
            'asset_id': a.id, 'job_type': 'preventive'})
        a.invalidate_recordset()
        self.assertEqual(a.open_job_count, 1)
        job.scheduled_date = fields.Datetime.now()
        job.action_schedule(); job.action_start(); job.action_complete()
        a.invalidate_recordset()
        self.assertEqual(a.open_job_count, 0)

    def test_m1_profitability_untouched(self):
        # The M1 placeholder fields must still be manually settable (regression).
        a = self.Asset.create({'name': 'D5', 'pm_interval_hours': 2000.0,
                               'revenue_total': 10000.0, 'cost_total': 3500.0})
        self.assertEqual(a.profitability, 6500.0)

    # ------------------------------------------------------------------
    # Header KPI strip
    # ------------------------------------------------------------------

    def _delta(self, *args, **kwargs):
        return self.env['gr.dashboard.card']._delta(*args, **kwargs)

    def test_delta_zero_change_is_neutral(self):
        # Was rendering as a green up-arrow: _trend_class had no zero branch.
        text, css = self._delta(100.0, 100.0)
        self.assertEqual(css, 'o_gr_chip_flat')
        self.assertNotIn('%', text)

    def test_delta_no_records_explains_itself(self):
        # Was rendering as "-100% ▼" in red whenever the period had no rows.
        text, css = self._delta(
            0.0, 53000.0, has_records=False, empty_message='Nothing posted')
        self.assertEqual(css, 'o_gr_chip_flat')
        self.assertEqual(text, 'Nothing posted')

    def test_delta_real_movement_is_directional(self):
        up_text, up_css = self._delta(120.0, 100.0)
        self.assertEqual(up_css, 'o_gr_chip_up o_gr_chip_num')
        self.assertEqual(up_text, '+20% ▲')
        down_text, down_css = self._delta(80.0, 100.0)
        self.assertEqual(down_css, 'o_gr_chip_down o_gr_chip_num')
        self.assertEqual(down_text, '-20% ▼')

    def test_delta_direction_is_a_parameter_not_a_constant(self):
        # Nothing in the header strip is lower-is-better today. The seam is
        # tested anyway so the first cost or downtime metric cannot inherit
        # the wrong semantics by default.
        _text, css = self._delta(80.0, 100.0, higher_is_better=False)
        self.assertEqual(css, 'o_gr_chip_up o_gr_chip_num')
        _text, css = self._delta(120.0, 100.0, higher_is_better=False)
        self.assertEqual(css, 'o_gr_chip_down o_gr_chip_num')

    def test_delta_from_zero_baseline_reports_no_percentage(self):
        # Growth from nothing has no defined percentage; the old code called
        # it "+100%". Direction only, and still coloured as a real increase.
        text, css = self._delta(53000.0, 0.0)
        self.assertEqual(text, '▲')
        self.assertEqual(css, 'o_gr_chip_up o_gr_chip_num')
        _text, css = self._delta(53000.0, 0.0, higher_is_better=False)
        self.assertEqual(css, 'o_gr_chip_down o_gr_chip_num')

    def test_delta_ltr_pin_only_on_numeric_chips(self):
        # o_gr_chip_num forces LTR. A translated sentence must not carry it.
        _text, numeric = self._delta(120.0, 100.0)
        self.assertIn('o_gr_chip_num', numeric)
        _text, neutral = self._delta(100.0, 100.0)
        self.assertNotIn('o_gr_chip_num', neutral)
        _text, empty = self._delta(0.0, 0.0, has_records=False,
                                   empty_message='لا توجد فواتير')
        self.assertNotIn('o_gr_chip_num', empty)

    def test_revenue_domain_excludes_drafts(self):
        # `state != 'cancel'` counted draft invoices as revenue.
        domain = dict(
            (term[0], term[2])
            for term in self.env['gr.dashboard.card']._posted_invoice_domain())
        self.assertEqual(domain['state'], 'posted')

    def test_period_bounds_follow_the_selected_granularity(self):
        Dashboard = self.env['gr.dashboard.card']
        day = fields.Date.to_date('2026-08-07')
        starts = {}
        for key in ('month', 'quarter', 'year'):
            start, end, prev_start, prev_end = Dashboard._period_bounds(day, key)
            starts[key] = (start, end, prev_start, prev_end)
            self.assertLessEqual(start, day)
            self.assertGreaterEqual(end, day)
            # the previous window ends the day before the current one starts
            self.assertEqual(prev_end, start - timedelta(days=1))
            self.assertLess(prev_start, prev_end)
        self.assertEqual(starts['month'][0], fields.Date.to_date('2026-08-01'))
        self.assertEqual(starts['quarter'][0], fields.Date.to_date('2026-07-01'))
        self.assertEqual(starts['year'][0], fields.Date.to_date('2026-01-01'))

    def test_period_key_falls_back_to_month(self):
        Dashboard = self.env['gr.dashboard.card']
        self.assertEqual(Dashboard._period_key(), 'month')
        self.assertEqual(
            Dashboard.with_context(gr_dash_period='quarter')._period_key(), 'quarter')
        self.assertEqual(
            Dashboard.with_context(gr_dash_period='fortnight')._period_key(), 'month')

    def test_contract_value_between_prorates_the_overlap(self):
        contract = self.env['gr.rental.contract'].new({
            'date_start': fields.Date.to_date('2026-07-07'),
            'date_end': fields.Date.to_date('2026-08-07'),
            'base_monthly_rate': 30000.0,
        })
        Dashboard = self.env['gr.dashboard.card']
        # 7 of August's days fall inside the contract: 30000 / 30 * 7
        value = Dashboard._contract_value_between(
            contract, fields.Date.to_date('2026-08-01'),
            fields.Date.to_date('2026-08-31'))
        self.assertAlmostEqual(value, 7000.0, places=2)
        # a window entirely after the contract contributes nothing
        self.assertEqual(Dashboard._contract_value_between(
            contract, fields.Date.to_date('2026-09-01'),
            fields.Date.to_date('2026-09-30')), 0.0)

    def test_contract_value_between_skips_undated_contracts(self):
        contract = self.env['gr.rental.contract'].new({'base_monthly_rate': 30000.0})
        self.assertEqual(self.env['gr.dashboard.card']._contract_value_between(
            contract, fields.Date.to_date('2026-08-01'),
            fields.Date.to_date('2026-08-31')), 0.0)

    def test_readiness_target_comes_from_config(self):
        Dashboard = self.env['gr.dashboard.card']
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param('gr_dashboard.readiness_target', '75')
        self.assertEqual(Dashboard._readiness_target(), 75)
        Param.set_param('gr_dashboard.readiness_target', 'not a number')
        self.assertEqual(Dashboard._readiness_target(), 90)

    def test_toolbar_survives_a_company_with_no_records(self):
        empty = self.env['res.company'].create({'name': 'Zero Records Co'})
        card = self.env['gr.dashboard.card'].with_company(empty).with_context(
            allowed_company_ids=[empty.id]).search([('card_key', '=', 'toolbar')])
        for period in ('month', 'quarter', 'year'):
            scoped = card.with_context(gr_dash_period=period)
            self.assertTrue(scoped.header_range)
            self.assertEqual(scoped.primary_value, '0')
            # every chip neutral: nothing to compare is not a 100% drop
            self.assertEqual(scoped.primary_delta_class, 'o_gr_chip_flat')
            self.assertEqual(scoped.metric_1_delta_class, 'o_gr_chip_flat')
            self.assertEqual(scoped.metric_2_foot_tone, 'flat')
            # overdue receivables are neutral when there are no invoices
            self.assertEqual(scoped.metric_3_tone, 'flat')
            self.assertFalse(scoped.hero_foot_4_label)

    def test_toolbar_card_renders_every_declared_field(self):
        card = self.env['gr.dashboard.card'].search([('card_key', '=', 'toolbar')])
        self.assertTrue(card.header_range)
        self.assertEqual(card.period_key, 'month')
        self.assertTrue(card.primary_label)
        self.assertTrue(card.primary_delta_class.startswith('o_gr_chip_'))
        quarter = card.with_context(gr_dash_period='quarter')
        self.assertEqual(quarter.period_key, 'quarter')
