# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, tools, _
from odoo.tools import date_utils
from odoo.tools.misc import format_date


class GrDashboardCard(models.Model):
    _name = 'gr.dashboard.card'
    _description = 'Generator Rental Dashboard Card'
    _auto = False
    _order = 'sequence, id'

    _FLEET_UTILIZED_STATUSES = ('reserved', 'in_transit', 'installed', 'on_rent')
    _FLEET_MAINTENANCE_STATUSES = (
        'maintenance_due', 'under_maintenance', 'returned_pending_inspection')
    _FLEET_OUT_OF_SERVICE_STATUSES = ('breakdown', 'unavailable')


    sequence = fields.Integer(readonly=True)
    card_key = fields.Char(readonly=True)
    title = fields.Char(compute='_compute_title', readonly=True)
    icon_class = fields.Char(readonly=True)
    action_xml_id = fields.Char(readonly=True)

    primary_label = fields.Char(compute='_compute_dashboard_metrics')
    primary_value = fields.Char(compute='_compute_dashboard_metrics')
    primary_meta = fields.Char(compute='_compute_dashboard_metrics')
    primary_percent = fields.Integer(compute='_compute_dashboard_metrics')
    primary_delta = fields.Char(compute='_compute_dashboard_metrics')
    primary_delta_class = fields.Char(compute='_compute_dashboard_metrics')
    primary_currency = fields.Char(compute='_compute_dashboard_metrics')
    primary_is_empty = fields.Boolean(compute='_compute_dashboard_metrics')
    primary_mixed = fields.Boolean(compute='_compute_dashboard_metrics')

    # Header row of the KPI strip: title/date range and the period control.
    header_range = fields.Char(compute='_compute_dashboard_metrics')
    header_compare = fields.Char(compute='_compute_dashboard_metrics')
    period_key = fields.Char(compute='_compute_dashboard_metrics')
    period_month_label = fields.Char(compute='_compute_dashboard_metrics')
    period_quarter_label = fields.Char(compute='_compute_dashboard_metrics')
    period_year_label = fields.Char(compute='_compute_dashboard_metrics')
    # Odoo's kanban view-button compiler drops unknown attributes, so
    # aria-pressed never reaches the DOM. The selected period is announced
    # with visually-hidden text inside the active button instead.
    period_selected_label = fields.Char(compute='_compute_dashboard_metrics')

    # Hero footer: one label/value pair per item, rendered on a single line.
    hero_foot_1_label = fields.Char(compute='_compute_dashboard_metrics')
    hero_foot_1_value = fields.Char(compute='_compute_dashboard_metrics')
    hero_foot_2_label = fields.Char(compute='_compute_dashboard_metrics')
    hero_foot_2_value = fields.Char(compute='_compute_dashboard_metrics')
    hero_foot_3_label = fields.Char(compute='_compute_dashboard_metrics')
    hero_foot_3_value = fields.Char(compute='_compute_dashboard_metrics')
    hero_foot_4_label = fields.Char(compute='_compute_dashboard_metrics')
    hero_foot_4_value = fields.Char(compute='_compute_dashboard_metrics')
    trend_label = fields.Char(compute='_compute_dashboard_metrics')
    trend_tone = fields.Char(compute='_compute_dashboard_metrics')
    empty_message = fields.Char(compute='_compute_dashboard_metrics')
    can_create_asset = fields.Boolean(compute='_compute_dashboard_metrics')

    metric_1_label = fields.Char(compute='_compute_dashboard_metrics')
    metric_1_value = fields.Char(compute='_compute_dashboard_metrics')
    metric_1_percent = fields.Integer(compute='_compute_dashboard_metrics')
    metric_1_delta = fields.Char(compute='_compute_dashboard_metrics')
    metric_1_delta_class = fields.Char(compute='_compute_dashboard_metrics')
    metric_1_tone = fields.Char(compute='_compute_dashboard_metrics')
    metric_1_foot = fields.Char(compute='_compute_dashboard_metrics')
    metric_2_label = fields.Char(compute='_compute_dashboard_metrics')
    metric_2_value = fields.Char(compute='_compute_dashboard_metrics')
    metric_2_percent = fields.Integer(compute='_compute_dashboard_metrics')
    metric_2_delta = fields.Char(compute='_compute_dashboard_metrics')
    metric_2_delta_class = fields.Char(compute='_compute_dashboard_metrics')
    metric_2_tone = fields.Char(compute='_compute_dashboard_metrics')
    metric_2_foot = fields.Char(compute='_compute_dashboard_metrics')
    metric_2_foot_tone = fields.Char(compute='_compute_dashboard_metrics')
    metric_2_foot_2 = fields.Char(compute='_compute_dashboard_metrics')
    metric_2_foot_2_tone = fields.Char(compute='_compute_dashboard_metrics')
    metric_3_label = fields.Char(compute='_compute_dashboard_metrics')
    metric_3_value = fields.Char(compute='_compute_dashboard_metrics')
    metric_3_percent = fields.Integer(compute='_compute_dashboard_metrics')
    metric_3_delta = fields.Char(compute='_compute_dashboard_metrics')
    metric_3_delta_class = fields.Char(compute='_compute_dashboard_metrics')
    metric_3_tone = fields.Char(compute='_compute_dashboard_metrics')
    metric_3_foot = fields.Char(compute='_compute_dashboard_metrics')
    metric_3_target = fields.Integer(compute='_compute_dashboard_metrics')
    metric_4_label = fields.Char(compute='_compute_dashboard_metrics')
    metric_4_value = fields.Char(compute='_compute_dashboard_metrics')
    metric_4_percent = fields.Integer(compute='_compute_dashboard_metrics')
    metric_4_delta = fields.Char(compute='_compute_dashboard_metrics')
    metric_4_delta_class = fields.Char(compute='_compute_dashboard_metrics')
    metric_4_tone = fields.Char(compute='_compute_dashboard_metrics')
    metric_4_foot = fields.Char(compute='_compute_dashboard_metrics')
    metric_4_unit = fields.Char(compute='_compute_dashboard_metrics')

    # Fleet mix segments for the generators card's stacked bar.
    mix_rented_percent = fields.Integer(compute='_compute_dashboard_metrics')
    mix_available_percent = fields.Integer(compute='_compute_dashboard_metrics')
    mix_maintenance_percent = fields.Integer(compute='_compute_dashboard_metrics')

    item_1_name = fields.Char(compute='_compute_dashboard_metrics')
    item_1_meta = fields.Char(compute='_compute_dashboard_metrics')
    item_1_badge = fields.Char(compute='_compute_dashboard_metrics')
    item_1_badge_tone = fields.Char(compute='_compute_dashboard_metrics')
    item_1_value = fields.Char(compute='_compute_dashboard_metrics')
    item_2_name = fields.Char(compute='_compute_dashboard_metrics')
    item_2_meta = fields.Char(compute='_compute_dashboard_metrics')
    item_2_badge = fields.Char(compute='_compute_dashboard_metrics')
    item_2_badge_tone = fields.Char(compute='_compute_dashboard_metrics')
    item_2_value = fields.Char(compute='_compute_dashboard_metrics')
    item_3_name = fields.Char(compute='_compute_dashboard_metrics')
    item_3_meta = fields.Char(compute='_compute_dashboard_metrics')
    item_3_badge = fields.Char(compute='_compute_dashboard_metrics')
    item_3_badge_tone = fields.Char(compute='_compute_dashboard_metrics')
    item_3_value = fields.Char(compute='_compute_dashboard_metrics')
    item_count = fields.Integer(compute='_compute_dashboard_metrics')

    bar_1_label = fields.Char(compute='_compute_dashboard_metrics')
    bar_1_value = fields.Char(compute='_compute_dashboard_metrics')
    bar_1_percent = fields.Integer(compute='_compute_dashboard_metrics')
    bar_2_label = fields.Char(compute='_compute_dashboard_metrics')
    bar_2_value = fields.Char(compute='_compute_dashboard_metrics')
    bar_2_percent = fields.Integer(compute='_compute_dashboard_metrics')
    bar_3_label = fields.Char(compute='_compute_dashboard_metrics')
    bar_3_value = fields.Char(compute='_compute_dashboard_metrics')
    bar_3_percent = fields.Integer(compute='_compute_dashboard_metrics')
    bar_4_label = fields.Char(compute='_compute_dashboard_metrics')
    bar_4_value = fields.Char(compute='_compute_dashboard_metrics')
    bar_4_percent = fields.Integer(compute='_compute_dashboard_metrics')
    # bar_5..7 extend the existing bar series so the revenue sparkline has its
    # seven buckets. Other cards keep using bar_1..4 as before.
    bar_5_label = fields.Char(compute='_compute_dashboard_metrics')
    bar_5_value = fields.Char(compute='_compute_dashboard_metrics')
    bar_5_percent = fields.Integer(compute='_compute_dashboard_metrics')
    bar_6_label = fields.Char(compute='_compute_dashboard_metrics')
    bar_6_value = fields.Char(compute='_compute_dashboard_metrics')
    bar_6_percent = fields.Integer(compute='_compute_dashboard_metrics')
    bar_7_label = fields.Char(compute='_compute_dashboard_metrics')
    bar_7_value = fields.Char(compute='_compute_dashboard_metrics')
    bar_7_percent = fields.Integer(compute='_compute_dashboard_metrics')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW gr_dashboard_card AS (
                SELECT 1 AS id, 1 AS sequence, 'toolbar' AS card_key,
                       'Rental Performance' AS title,
                       'fa fa-dashboard' AS icon_class,
                       NULL AS action_xml_id
                UNION ALL
                SELECT 2 AS id, 10 AS sequence, 'fleet' AS card_key,
                       'Fleet Utilization & Status' AS title,
                       'fa fa-pie-chart' AS icon_class,
                       'gr_dashboard.action_dash_fleet_detail' AS action_xml_id
                UNION ALL
                SELECT 3, 20, 'hours', 'Billable Hours',
                       'fa fa-clock-o', 'gr_dashboard.action_dash_hours'
                UNION ALL
                SELECT 4, 30, 'maintenance', 'Maintenance Overview',
                       'fa fa-wrench', 'gr_dashboard.action_dash_maint_jobs'
                UNION ALL
                SELECT 5, 40, 'needs_maintenance', 'Assets Needing Maintenance',
                       'fa fa-exclamation-triangle', 'gr_dashboard.action_dash_overdue_assets'
                UNION ALL
                SELECT 6, 50, 'profitability', 'Asset Profitability',
                       'fa fa-bar-chart', 'gr_dashboard.action_dash_profit'
                UNION ALL
                SELECT 7, 60, 'sublet_margin', 'Sublet Margin Snapshot',
                       'fa fa-exchange', 'gr_rental_sublet.action_gr_sublet_margin'
                UNION ALL
                SELECT 8, 70, 'quick_access', 'Quick Access',
                       'fa fa-bolt', NULL
            )
        """)

    @api.depends('card_key')
    @api.depends_context('lang')
    def _compute_title(self):
        titles = {
            'toolbar': _('Rental Performance'),
            'fleet': _('Fleet Utilization & Status'),
            'hours': _('Billable Hours'),
            'maintenance': _('Maintenance Overview'),
            'needs_maintenance': _('Assets Needing Maintenance'),
            'profitability': _('Asset Profitability'),
            'sublet_margin': _('Sublet Margin Snapshot'),
            'quick_access': _('Quick Access'),
        }
        for card in self:
            card.title = titles.get(card.card_key, card.card_key or '')

    def _fmt(self, source, *args):
        """Apply placeholders to an already-translated string.

        Kept as a helper only because several call sites spread their arguments
        over multiple lines; the translation itself is a plain ``_()`` at the
        call site, so the terms are exported and translated like any other.
        """
        return source % args

    @api.depends_context(
        'company', 'allowed_company_ids', 'uid', 'lang', 'gr_dash_period')
    def _compute_dashboard_metrics(self):
        data = self._dashboard_data()
        field_names = [
            name for name, field in self._fields.items()
            if field.compute == '_compute_dashboard_metrics'
        ]
        for card in self:
            values = data.get(card.card_key, {})
            for name in field_names:
                field = self._fields[name]
                default = False
                if field.type == 'integer':
                    default = 0
                elif field.type == 'boolean':
                    default = False
                setattr(card, name, values.get(name, default))

    def _dashboard_data(self):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        month_end = month_start + relativedelta(months=1, days=-1)
        currency = self.env.company.currency_id
        fleet_data = self._fleet_data()

        return {
            'toolbar': self._toolbar_data(today, currency, fleet_data),
            'fleet': fleet_data,
            'hours': self._hours_data(month_start, month_end),
            'maintenance': self._maintenance_data(),
            'needs_maintenance': self._needs_maintenance_data(),
            'profitability': self._profitability_data(currency),
            'sublet_margin': self._sublet_margin_data(currency),
            'quick_access': self._quick_access_data(),
        }

    # ------------------------------------------------------------------
    # Header strip
    #
    # The header KPIs are period-aware: `gr_dash_period` in the context picks
    # month / quarter / year, and the segmented control at the top of the
    # strip re-runs the action with a different value (_action_for_period).
    # _compute_dashboard_metrics depends on that context key, so switching
    # period genuinely re-queries instead of restyling the same numbers.
    # ------------------------------------------------------------------

    _PERIOD_KEYS = ('month', 'quarter', 'year')
    _SPARK_BUCKETS = 7
    _EXPIRY_WINDOW_DAYS = 30
    _DEFAULT_READINESS_TARGET = 90
    # A non-zero period still gets a visible stub, so "small" never looks
    # like "none" on the sparkline.
    _SPARK_MIN_BAR_PERCENT = 3
    # Monthly rates are prorated on a flat 30-day month, the convention
    # _contract_value already uses. Not calendar days.
    _DAYS_PER_BILLING_MONTH = 30.0

    def _period_terms(self):
        return {
            'month': {
                'compare': _('vs last month'),
                'previous': _('Last month'),
                'empty': _('No posted invoices this month'),
                'bucket': 'MMM y',
            },
            'quarter': {
                'compare': _('vs last quarter'),
                'previous': _('Last quarter'),
                'empty': _('No posted invoices this quarter'),
                'bucket': 'QQQ y',
            },
            'year': {
                'compare': _('vs last year'),
                'previous': _('Last year'),
                'empty': _('No posted invoices this year'),
                'bucket': 'y',
            },
        }

    def _toolbar_data(self, today, currency, fleet_data):
        key = self._period_key()
        terms = self._period_terms()[key]
        start, end, prev_start, prev_end = self._period_bounds(today, key)
        Asset = self.env['gr.generator.asset']
        Contract = self.env['gr.rental.contract']
        Move = self.env['account.move']
        counts = fleet_data.get('_counts', {})
        total_assets = counts.get('total', 0)

        values = {
            'period_key': key,
            'period_month_label': _('Month'),
            'period_quarter_label': _('Quarter'),
            'period_year_label': _('Year'),
            'period_selected_label': _('Selected'),
            'header_range': self._format_range(start, end, key),
            'header_compare': terms['compare'],
            'can_create_asset': Asset.has_access('create'),
        }

        # -- hero: revenue for the selected period ----------------------
        revenue, invoice_count, mixed = self._revenue_in(start, end)
        previous_revenue, _previous_count, previous_mixed = self._revenue_in(
            prev_start, prev_end)
        amount, symbol = self._money_split(revenue, currency)
        delta, delta_class = self._delta(
            revenue, previous_revenue,
            has_records=bool(invoice_count),
            empty_message=terms['empty'])
        if mixed or previous_mixed:
            # Nothing here converts currencies, so a sum across two of them
            # would be a number with no unit. Say so instead of printing it.
            delta, delta_class = _('Mixed currencies'), 'o_gr_chip_warn'
        values.update({
            'primary_label': _('Total Revenue'),
            'primary_value': amount,
            'primary_currency': symbol,
            'primary_delta': delta,
            'primary_delta_class': delta_class,
            'primary_is_empty': not invoice_count,
            'primary_mixed': mixed or previous_mixed,
        })

        # -- hero sparkline: one bar per period, oldest first ------------
        series = self._revenue_series(start, key, self._SPARK_BUCKETS)
        peak = max((bucket_total for _bucket, bucket_total in series), default=0.0)
        for index, (bucket, bucket_total) in enumerate(series, start=1):
            values['bar_%s_label' % index] = format_date(
                self.env, bucket, date_format=terms['bucket'])
            values['bar_%s_value' % index] = self._money_suffix(bucket_total, currency)
            values['bar_%s_percent' % index] = (
                max(self._SPARK_MIN_BAR_PERCENT,
                    int(round(bucket_total / peak * 100)))
                if peak and bucket_total else 0)

        # -- hero footer -------------------------------------------------
        contract_domain = [
            ('company_id', '=', self.env.company.id),
            ('active', '=', True),
            ('state', '=', 'active'),
        ]
        window_contracts = Contract.search(
            contract_domain + self._contract_window_domain(start, end))
        previous_contracts = Contract.search(
            contract_domain + self._contract_window_domain(prev_start, prev_end))
        active_contracts_count = Contract.search_count(contract_domain)
        missing_start_dates = Contract.search_count(
            contract_domain + [('date_start', '=', False)])
        forecast = sum(
            self._contract_value_between(contract, start, end)
            for contract in window_contracts)
        forecast_text = self._money_suffix(forecast, currency)
        if missing_start_dates:
            # A contract with no start date cannot be placed on a timeline, so
            # it contributes nothing here. Show how many, rather than quietly
            # under-reporting the forecast.
            forecast_text = '%s (%s)' % (
                forecast_text,
                self._fmt(
                    _('%s of %s contracts missing start dates'),
                    missing_start_dates,
                    active_contracts_count))
        last_invoice = Move.search(
            self._posted_invoice_domain(), order='invoice_date desc', limit=1)
        draft_count = Move.search_count([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'draft'),
            ('company_id', '=', self.env.company.id),
        ])
        values.update({
            'hero_foot_1_label': terms['previous'],
            'hero_foot_1_value': self._money_suffix(previous_revenue, currency),
            'hero_foot_2_label': _('Expected from active contracts'),
            'hero_foot_2_value': forecast_text,
            'hero_foot_3_label': _('Last invoice'),
            'hero_foot_3_value': (
                format_date(self.env, last_invoice.invoice_date, date_format='d MMMM y')
                if last_invoice.invoice_date else _('None')),
        })
        if draft_count:
            # Unposted work exists even when posted revenue is zero, so the
            # empty state reads as "nothing posted yet", not "nothing happened".
            values.update({
                'hero_foot_4_label': _('Draft invoices'),
                'hero_foot_4_value': self._compact_number(draft_count),
            })

        # -- card 1: average contract value ------------------------------
        average = self._average_contract_value(window_contracts)
        previous_average = self._average_contract_value(previous_contracts)
        highest = max(
            (self._contract_value(contract) for contract in window_contracts),
            default=0.0)
        average_delta, average_delta_class = self._delta(
            average, previous_average,
            has_records=bool(window_contracts or previous_contracts),
            empty_message=_('No dated contracts'))
        values.update({
            'metric_1_label': _('Average Contract Value'),
            'metric_1_value': self._money_suffix(average, currency),
            'metric_1_delta': average_delta,
            'metric_1_delta_class': average_delta_class,
            'metric_1_foot': '%s %s' % (
                _('Highest contract'), self._money_suffix(highest, currency)),
        })

        # -- card 2: active contracts ------------------------------------
        expiring = Contract.search_count(contract_domain + [
            ('date_end', '>=', today),
            ('date_end', '<=', today + relativedelta(days=self._EXPIRY_WINDOW_DAYS)),
        ])
        past_end = Contract.search_count(contract_domain + [
            ('date_end', '!=', False),
            ('date_end', '<', today),
        ])
        values.update({
            'metric_2_label': _('Active Contracts'),
            'metric_2_value': self._compact_number(active_contracts_count),
            'metric_2_foot': (
                self._fmt(_('%s ending within %s days'),
                          expiring, self._EXPIRY_WINDOW_DAYS)
                if expiring else _('None ending soon')),
            'metric_2_foot_tone': 'warn' if expiring else 'flat',
        })
        if past_end:
            # Still 'active' with an end date already behind us. A data problem
            # rather than an operational one, so it gets its own chip instead
            # of displacing the expiry signal the card exists to show.
            values.update({
                'metric_2_foot_2': self._fmt(_('%s past its end date'), past_end),
                'metric_2_foot_2_tone': 'down',
            })

        # -- card 3: overdue receivables --------------------------------
        # This is a more actionable executive signal than fleet readiness in
        # the rental-performance header: it tells the user whether revenue
        # already earned is stuck in collection.
        overdue_moves = Move.search(self._posted_invoice_domain() + [
            ('invoice_date_due', '!=', False),
            ('invoice_date_due', '<', today),
            ('amount_residual', '>', 0),
        ])
        overdue_amount = sum(
            abs(move.amount_residual_signed or move.amount_residual or 0.0)
            for move in overdue_moves)
        overdue_count = len(overdue_moves)
        values.update({
            'metric_3_label': _('Overdue Receivables'),
            'metric_3_value': self._money_suffix(overdue_amount, currency),
            'metric_3_foot': (
                self._fmt(_('%s overdue invoice(s)'), overdue_count)
                if overdue_count else _('No overdue receivables')),
            'metric_3_tone': 'warn' if overdue_count else 'flat',
        })

        # -- card 4: fleet mix -------------------------------------------
        # The headline number is the company's OWN fleet. Third-party units are
        # rented in from suppliers and are not company assets, so they are
        # reported alongside rather than folded into the fleet size. The mix
        # bars stay on the deployable pool, which is what they measure.
        owned_assets = counts.get('owned', 0)
        third_party_assets = counts.get('third_party', 0)
        mix_foot = [
            self._fmt(_('%s rented'), counts.get('utilized', 0)),
            self._fmt(_('%s available'), counts.get('available', 0)),
            self._fmt(_('%s maintenance'), counts.get('maintenance', 0)),
        ]
        if third_party_assets:
            mix_foot.append(self._fmt(_('%s third-party'), third_party_assets))
        values.update({
            'metric_4_label': _('Owned Generators'),
            'metric_4_value': self._compact_number(owned_assets),
            'metric_4_unit': _('unit(s)'),
            'metric_4_foot': ' · '.join(mix_foot),
            'mix_rented_percent': self._percent(counts.get('utilized', 0), total_assets),
            'mix_available_percent': self._percent(counts.get('available', 0), total_assets),
            'mix_maintenance_percent': self._percent(
                counts.get('maintenance', 0) + counts.get('out', 0), total_assets),
        })
        return values

    # -- period plumbing -------------------------------------------------

    def _period_key(self):
        key = self.env.context.get('gr_dash_period')
        return key if key in self._PERIOD_KEYS else 'month'

    @staticmethod
    def _period_step(key, count):
        if key == 'month':
            return relativedelta(months=count)
        if key == 'quarter':
            return relativedelta(months=3 * count)
        return relativedelta(years=count)

    def _period_bounds(self, today, key):
        start = date_utils.start_of(today, key)
        end = date_utils.end_of(today, key)
        previous_end = start - relativedelta(days=1)
        return start, end, date_utils.start_of(previous_end, key), previous_end

    def _format_range(self, start, end, key):
        if key == 'year':
            return format_date(self.env, start, date_format='y')
        if (start.year, start.month) == (end.year, end.month):
            return '%s – %s' % (
                format_date(self.env, start, date_format='d'),
                format_date(self.env, end, date_format='d MMMM y'))
        return '%s – %s' % (
            format_date(self.env, start, date_format='d MMMM'),
            format_date(self.env, end, date_format='d MMMM y'))

    def _action_for_period(self, period):
        action = self.env.ref('gr_dashboard.action_dash_fleet').read()[0]
        action['context'] = {
            'create': False,
            'edit': False,
            'delete': False,
            'gr_dash_period': period,
        }
        # 'main' replaces the current action rather than stacking a breadcrumb,
        # so switching period repeatedly does not grow the trail.
        action['target'] = 'main'
        return action

    def action_period_month(self):
        return self._action_for_period('month')

    def action_period_quarter(self):
        return self._action_for_period('quarter')

    def action_period_year(self):
        return self._action_for_period('year')

    # -- revenue ---------------------------------------------------------

    def _posted_invoice_domain(self):
        """Posted customer invoices for the active company.

        Was `state != 'cancel'`, which counted drafts as revenue. Drafts are
        reported separately in the hero footer instead of being summed in.
        """
        return [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('company_id', '=', self.env.company.id),
        ]

    def _revenue_groups(self, start, end):
        """[(currency, total, count)] for posted invoices dated in [start, end].

        Grouped by currency on purpose. Nothing on this dashboard converts
        between currencies, so more than one group means the totals cannot be
        added together and the caller has to surface that instead of printing
        a sum with no unit.
        """
        return [
            (group_currency, group_total or 0.0, group_count)
            for group_currency, group_total, group_count
            in self.env['account.move']._read_group(
                self._posted_invoice_domain() + [
                    ('invoice_date', '>=', start),
                    ('invoice_date', '<=', end),
                ],
                ['currency_id'],
                ['amount_untaxed:sum', '__count'],
            )
        ]

    def _revenue_in(self, start, end):
        """(total, invoice_count, mixed_currencies) for one window."""
        groups = self._revenue_groups(start, end)
        return (
            sum(row[1] for row in groups),
            sum(row[2] for row in groups),
            len(groups) > 1,
        )

    def _revenue_series(self, current_start, key, buckets):
        """[(bucket_start, total)] for the `buckets` periods ending at the current one."""
        starts = [
            date_utils.start_of(current_start - self._period_step(key, offset), key)
            for offset in range(buckets - 1, -1, -1)
        ]
        rows = self.env['account.move']._read_group(
            self._posted_invoice_domain() + [
                ('invoice_date', '>=', starts[0]),
                ('invoice_date', '<=', date_utils.end_of(starts[-1], key)),
            ],
            ['invoice_date:%s' % key],
            ['amount_untaxed:sum'],
        )
        totals = {bucket: bucket_total or 0.0 for bucket, bucket_total in rows if bucket}
        return [(bucket, totals.get(bucket, 0.0)) for bucket in starts]

    # -- comparison ------------------------------------------------------

    def _delta(self, current, previous, higher_is_better=True,
               has_records=True, empty_message=None):
        """Comparison chip text and CSS class for one metric.

        Four states, because three of them used to come out as a green
        up-arrow or a red -100%:

        * nothing to compare (no underlying records) -> neutral, explained
        * no movement                                -> neutral, 'No change'
        * movement in the good direction             -> success
        * movement in the bad direction              -> danger

        `higher_is_better` is what makes the last two directional. Every
        metric in the header strip is higher-is-better today; a cost, downtime
        or overdue metric is not, and has to pass False rather than inherit
        the default.
        """
        if not has_records:
            return (empty_message or _('No change'), 'o_gr_chip_flat')
        if previous:
            change = ((current - previous) / abs(previous)) * 100.0
        elif current:
            # Growth from a zero baseline has no defined percentage. Show the
            # direction only -- the footer carries the absolute figures --
            # rather than inventing the "+100%" the old code reported.
            rose = current > 0
            return (
                '▲' if rose else '▼',
                ('o_gr_chip_up' if rose == higher_is_better else 'o_gr_chip_down')
                + ' o_gr_chip_num',
            )
        else:
            change = 0.0
        change = int(round(change))
        if change == 0:
            return (_('No change'), 'o_gr_chip_flat')
        good = (change > 0) if higher_is_better else (change < 0)
        # o_gr_chip_num pins this chip left-to-right. Only the two numeric
        # branches get it: the neutral ones carry a translated sentence, which
        # must follow the UI direction like any other text.
        return (
            '%s%s%% %s' % ('+' if change > 0 else '-', abs(change),
                           '▲' if change > 0 else '▼'),
            'o_gr_chip_up o_gr_chip_num' if good else 'o_gr_chip_down o_gr_chip_num',
        )

    # -- contracts -------------------------------------------------------

    def _contract_window_domain(self, start, end):
        """Contracts whose own date range overlaps [start, end].

        Replaces the previous `create_date < period_start` baseline, which
        compared the *current* state of older records and so was not a time
        comparison at all. A contract with no start date cannot be placed on a
        timeline and drops out of both sides; the count of those is surfaced
        in the hero footer so the omission is visible.
        """
        return [
            ('date_start', '!=', False),
            ('date_start', '<=', end),
            '|', ('date_end', '=', False), ('date_end', '>=', start),
        ]

    @staticmethod
    def _contract_value_between(contract, start, end):
        """Expected billing from one contract over its overlap with [start, end].

        Same rate ladder as _contract_value, prorated across the overlapping
        days. One-off charges (mobilisation, demobilisation, deposit) are left
        out: they are not earned per day and would inflate every period they
        touch.

        Rates are read at their current values -- a contract carries no rate
        history -- so if a rate changed mid-period this drifts from what was
        actually billed.
        """
        if not contract.date_start:
            return 0.0
        window_start = max(contract.date_start, start)
        window_end = min(contract.date_end, end) if contract.date_end else end
        if window_end < window_start:
            return 0.0
        days = (window_end - window_start).days + 1
        if contract.base_monthly_rate:
            return (contract.base_monthly_rate * days
                    / GrDashboardCard._DAYS_PER_BILLING_MONTH)
        if contract.base_daily_rate:
            return contract.base_daily_rate * days
        if contract.hourly_rate and contract.included_hours_per_day:
            return contract.hourly_rate * contract.included_hours_per_day * days
        return 0.0

    # -- configuration ---------------------------------------------------

    def _readiness_target(self):
        """Fleet readiness target, in whole percent.

        A policy number, so it lives in ir.config_parameter
        (gr_dashboard.readiness_target) rather than being hardcoded here or
        invented per render.
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'gr_dashboard.readiness_target', self._DEFAULT_READINESS_TARGET)
        try:
            return max(0, min(100, int(float(raw))))
        except (TypeError, ValueError):
            return self._DEFAULT_READINESS_TARGET

    def _fleet_data(self):
        Asset = self.env['gr.generator.asset']
        # The fleet card is about the rentable pool: the units the company can
        # actually deploy. Customer-owned equipment is serviced, never rented,
        # so counting it here deflated every utilization percentage.
        # Owned and third-party are counted separately below, because a unit
        # rented in from a supplier is not a company asset and must never be
        # presented as fleet size.
        active_fleet_domain = [
            ('company_id', '=', self.env.company.id),
            ('active', '=', True),
            ('status', '!=', 'retired'),
            ('is_rentable', '=', True),
        ]
        owned_domain = active_fleet_domain + [('owner_type', '=', 'owned')]
        third_party_domain = active_fleet_domain + [('owner_type', '=', 'rented_in')]
        owned_total = Asset.search_count(owned_domain)
        third_party_total = Asset.search_count(third_party_domain)
        total = Asset.search_count(active_fleet_domain)
        utilized = Asset.search_count(active_fleet_domain + [
            ('status', 'in', self._FLEET_UTILIZED_STATUSES)])
        available = Asset.search_count(active_fleet_domain + [('status', '=', 'available')])
        maintenance = Asset.search_count(active_fleet_domain + [
            ('status', 'in', self._FLEET_MAINTENANCE_STATUSES)])
        out = Asset.search_count(active_fleet_domain + [
            ('status', 'in', self._FLEET_OUT_OF_SERVICE_STATUSES)])
        percent = self._percent(utilized, total)

        return {
            'primary_label': _('Utilized'),
            'primary_value': _('%s%%') % percent if total else _('0%'),
            'primary_percent': percent,
            'metric_1_label': _('Utilized'),
            'metric_1_value': self._count_percent(utilized, total),
            'metric_1_percent': percent,
            'metric_1_tone': 'purple',
            'metric_2_label': _('Available'),
            'metric_2_value': self._count_percent(available, total),
            'metric_2_percent': self._percent(available, total),
            'metric_2_tone': 'pink',
            'metric_3_label': _('Maintenance'),
            'metric_3_value': self._count_percent(maintenance, total),
            'metric_3_percent': self._percent(maintenance, total),
            'metric_3_tone': 'orange',
            'metric_4_label': _('Out of Service'),
            'metric_4_value': self._count_percent(out, total),
            'metric_4_percent': self._percent(out, total),
            'metric_4_tone': 'gray',
            'primary_meta': _('View Details'),
            # Raw buckets for the header strip's generator card, so it reuses
            # this query instead of counting the fleet a second time. The
            # leading underscore keeps it out of the field-name loop in
            # _compute_dashboard_metrics.
            '_counts': {
                'total': total,
                'utilized': utilized,
                'available': available,
                'maintenance': maintenance,
                'out': out,
                # Ownership split. 'owned' is the only number that may be
                # presented as the company's own fleet size.
                'owned': owned_total,
                'third_party': third_party_total,
            },
        }

    def _hours_data(self, month_start, month_end):
        Log = self.env['gr.hour.log']
        domain = [
            ('company_id', '=', self.env.company.id),
            ('reading_date', '>=', month_start),
            ('reading_date', '<=', month_end),
            ('state', '=', 'approved'),
        ]
        used = self._sum_records(Log, 'used_hours', domain)
        overtime = self._sum_records(Log, 'overtime_hours', domain)
        violation = self._sum_records(Log, 'violation_hours', domain)
        pending = 0.0
        if 'billed' in Log._fields:
            pending = self._sum_records(Log, 'used_hours', domain + [('billed', '=', False)])
        return {
            'primary_label': _('This Month'),
            'primary_value': self._compact_number(used),
            'primary_meta': _('Approved hour logs'),
            'metric_1_label': _('Unbilled'),
            'metric_1_value': self._compact_number(pending),
            'metric_1_tone': 'green',
            'metric_2_label': _('Overtime'),
            'metric_2_value': self._compact_number(overtime),
            'metric_2_tone': 'orange',
            'metric_3_label': _('Violation'),
            'metric_3_value': self._compact_number(violation),
            'metric_3_tone': 'red',
            'trend_label': _('View Hours'),
            'bar_1_label': _('h'),
        }

    def _maintenance_data(self):
        Job = self.env['gr.maintenance.job']
        base = [('company_id', '=', self.env.company.id)]
        planned = Job.search_count(base + [('state', 'in', ('draft', 'scheduled'))])
        in_progress = Job.search_count(base + [('state', '=', 'in_progress')])
        overdue = Job.search_count(base + [
            ('state', 'not in', ('done', 'cancelled')),
            ('scheduled_date', '<', fields.Datetime.now()),
        ])
        done = Job.search_count(base + [('state', '=', 'done')])
        total_jobs = done + planned + in_progress + overdue
        completion = self._percent(done, total_jobs)
        return {
            'primary_label': _('Completion Rate'),
            'primary_value': _('%s%%') % completion,
            'primary_percent': completion,
            'primary_meta': _('View Maintenance Orders'),
            'metric_1_label': _('Planned'),
            'metric_1_value': str(planned),
            'metric_1_tone': 'purple',
            'metric_2_label': _('In Progress'),
            'metric_2_value': str(in_progress),
            'metric_2_tone': 'pink',
            'metric_3_label': _('Overdue'),
            'metric_3_value': str(overdue),
            'metric_3_tone': 'red',
            'metric_4_label': _('Completed'),
            'metric_4_value': str(done),
            'metric_4_tone': 'green',
        }

    def _needs_maintenance_data(self):
        Asset = self.env['gr.generator.asset']
        domain = [
            ('company_id', '=', self.env.company.id),
            ('active', '=', True),
            '|',
            ('maintenance_overdue', '=', True),
            ('status', 'in', ('maintenance_due', 'breakdown', 'under_maintenance')),
        ]
        assets = Asset.search(domain, order='maintenance_overdue desc, current_hour_meter desc, name', limit=3)
        count = Asset.search_count(domain)
        values = {
            'item_count': count,
            'empty_message': _('No assets need maintenance right now') if not count else '',
            'primary_meta': self._fmt(_('View all (%s)'), count),
        }
        for idx, asset in enumerate(assets, start=1):
            overdue = asset.maintenance_overdue or asset.status == 'breakdown'
            badge = _('Overdue') if overdue else _('Due Soon')
            diff = (asset.current_hour_meter or 0.0) - (asset.next_pm_hour or 0.0)
            if asset.next_pm_hour:
                detail = self._fmt(_('Over by %s h'), self._compact_number(abs(diff))) if diff >= 0 else self._fmt(_('Due in %s h'), self._compact_number(abs(diff)))
            else:
                detail = dict(asset._fields['status'].selection).get(asset.status, asset.status or '')
            values.update({
                f'item_{idx}_name': asset.name,
                f'item_{idx}_meta': asset.code,
                f'item_{idx}_badge': badge,
                f'item_{idx}_badge_tone': 'overdue' if overdue else 'due_soon',
                f'item_{idx}_value': detail,
            })
        return values

    def _profitability_data(self, currency):
        Asset = self.env['gr.generator.asset']
        assets = Asset.search([
            ('company_id', '=', self.env.company.id),
            ('active', '=', True),
        ])
        scored = []
        for asset in assets:
            revenue = asset.live_revenue or asset.revenue_total or 0.0
            cost = asset.live_cost or asset.cost_total or 0.0
            profit = asset.live_profit_estimate if asset.live_revenue else asset.profitability
            profit = profit or 0.0
            if revenue or cost or profit:
                scored.append((asset, revenue, cost, profit))
        if not scored:
            return {'empty_message': _('No profitability data available yet')}

        scored.sort(key=lambda row: row[3], reverse=True)
        top_asset, revenue, cost, profit = scored[0]
        margin = self._percent(profit, revenue) if revenue else 0
        max_profit = max(abs(row[3]) for row in scored[:4]) or 1.0
        values = {
            'primary_label': _('Top Asset'),
            'primary_value': top_asset.name,
            'primary_meta': self._fmt(_('Profit margin %s%%'), margin) if revenue else _('Profit estimate'),
            'trend_label': _('View Profitability Analysis'),
            'metric_1_label': _('Revenue'),
            'metric_1_value': self._money(revenue, currency),
            'metric_1_tone': 'green',
            'metric_2_label': _('Cost'),
            'metric_2_value': self._money(cost, currency),
            'metric_2_tone': 'orange',
            'metric_3_label': _('Profit'),
            'metric_3_value': self._money(profit, currency),
            'metric_3_tone': 'purple',
        }
        for idx, (asset, _revenue, _cost, asset_profit) in enumerate(scored[:4], start=1):
            values.update({
                f'bar_{idx}_label': asset.name,
                f'bar_{idx}_value': self._money(asset_profit, currency),
                f'bar_{idx}_percent': max(4, min(100, int(abs(asset_profit) / max_profit * 100))),
            })
        return values

    def _sublet_margin_data(self, currency):
        if 'gr.sublet.agreement' not in self.env.registry.models:
            return {
                'empty_message': _('No sublet margin data yet'),
                'trend_label': _('View Margin Analysis'),
            }
        Agreement = self.env['gr.sublet.agreement']
        agreements = Agreement.search([
            ('company_id', '=', self.env.company.id),
            ('state', '!=', 'cancelled'),
        ])
        if not agreements:
            return {
                'empty_message': _('No sublet margin data yet'),
                'trend_label': _('View Margin Analysis'),
            }

        revenue = sum(agreements.mapped('revenue_out'))
        cost_in = sum(agreements.mapped('cost_in'))
        extra_cost = sum(agreements.mapped('extra_direct_cost'))
        margin = sum(agreements.mapped('margin'))
        margin_rate = self._percent(margin, revenue) if revenue else 0
        exposed_count = len(agreements.filtered('exposure_flagged'))
        active_count = len(agreements.filtered(lambda ag: ag.state == 'committed'))

        meta = (
            self._fmt(_('%s exposed agreement(s)'), exposed_count)
            if exposed_count
            else self._fmt(_('%s active agreement(s)'), active_count)
        )
        return {
            'primary_label': _('Net Margin'),
            'primary_value': self._money(margin, currency),
            'primary_meta': meta,
            'trend_label': _('View Margin Analysis'),
            'metric_1_label': _('Revenue Out'),
            'metric_1_value': self._money(revenue, currency),
            'metric_1_tone': 'green',
            'metric_2_label': _('Rent-in Cost'),
            'metric_2_value': self._money(cost_in, currency),
            'metric_2_tone': 'orange',
            'metric_3_label': _('Extra Direct Cost'),
            'metric_3_value': self._money(extra_cost, currency),
            'metric_3_tone': 'red',
            'metric_4_label': _('Margin Rate'),
            'metric_4_value': _('%s%%') % margin_rate,
            'metric_4_tone': 'purple',
        }

    def _quick_access_data(self):
        Asset = self.env['gr.generator.asset']
        return {
            'primary_label': _('Quick Access'),
            'metric_1_label': _('Custom Report'),
            'metric_2_label': _('New Invoice'),
            'metric_3_label': _('New Customer'),
            'metric_4_label': _('New Contract'),
            'item_1_name': _('New Maintenance Order'),
            'item_2_name': _('New Generator'),
            'can_create_asset': Asset.has_access('create'),
        }

    def action_open_detail(self):
        self.ensure_one()
        if not self.action_xml_id:
            return self.action_refresh()
        action = self.env.ref(self.action_xml_id, raise_if_not_found=False)
        if not action:
            return False
        return action.read()[0]

    def action_refresh(self):
        return self.env.ref('gr_dashboard.action_dash_fleet').read()[0]

    def action_new_asset(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Generator Asset'),
            'res_model': 'gr.generator.asset',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_status': 'available'},
        }

    def action_new_maintenance(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Maintenance Order'),
            'res_model': 'gr.maintenance.job',
            'view_mode': 'form',
            'target': 'current',
        }

    def action_new_contract(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Contract'),
            'res_model': 'gr.rental.contract',
            'view_mode': 'form',
            'target': 'current',
        }

    def action_new_customer(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Customer'),
            'res_model': 'res.partner',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_customer_rank': 1},
        }

    def action_new_invoice(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Invoice'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_move_type': 'out_invoice'},
        }

    def action_open_report(self):
        return self.env.ref('gr_dashboard.action_dash_profit').read()[0]

    @staticmethod
    def _percent(value, total):
        return int(round((value / total) * 100)) if total else 0

    def _count_percent(self, value, total):
        percent = self._percent(value, total)
        return self._fmt(_('%s / %s (%s%%)'), value, total, percent) if total else _('0 / 0')

    @staticmethod
    def _compact_number(value):
        value = value or 0.0
        if abs(value - int(value)) < 0.01:
            return f'{int(value):,}'
        return f'{value:,.1f}'

    def _hours(self, value):
        return self._fmt(_('%s h'), self._compact_number(value))

    def _money(self, value, currency):
        return self._money_suffix(value, currency)

    def _money_suffix(self, value, currency):
        symbol = self._currency_suffix(currency)
        amount = self._compact_money(value)
        return f'{amount} {symbol}'.strip()

    def _money_split(self, value, currency):
        """(amount, symbol) for the hero, which sizes the two differently.

        Same source as _money_suffix, so whatever the company currency is,
        every figure on the strip is labelled with it identically.
        """
        return self._compact_money(value), self._currency_suffix(currency)

    @staticmethod
    def _currency_suffix(currency):
        symbol = (currency.symbol or currency.name or '').strip()
        if symbol.upper() in ('RS', 'SAR') or currency.name == 'SAR':
            return 'SR'
        return symbol

    @staticmethod
    def _compact_percent(value):
        value = value or 0.0
        if abs(value - int(value)) < 0.05:
            return f'{int(round(value))}'
        return f'{value:.1f}'

    @staticmethod
    def _compact_money(value):
        value = value or 0.0
        abs_value = abs(value)
        if abs_value >= 1000000:
            return f'{value / 1000000:.2f}'.rstrip('0').rstrip('.') + 'M'
        if abs_value >= 1000:
            return f'{value / 1000:.2f}'.rstrip('0').rstrip('.') + 'K'
        if abs(value - int(value)) < 0.01:
            return f'{int(value):,}'
        return f'{value:,.2f}'

    def _average_contract_value(self, contracts):
        if not contracts:
            return 0.0
        return sum(self._contract_value(contract) for contract in contracts) / len(contracts)

    @staticmethod
    def _contract_value(contract):
        days = 1
        if contract.date_start and contract.date_end:
            days = max(1, (contract.date_end - contract.date_start).days + 1)
        if contract.base_monthly_rate:
            return contract.base_monthly_rate * max(
                1, days / GrDashboardCard._DAYS_PER_BILLING_MONTH)
        if contract.base_daily_rate:
            return contract.base_daily_rate * days
        if contract.hourly_rate and contract.included_hours_per_day:
            return contract.hourly_rate * contract.included_hours_per_day * days
        commercial_total = sum([
            contract.hourly_rate or 0.0,
            contract.overtime_hour_rate or 0.0,
            contract.violation_hour_rate or 0.0,
            contract.standby_rate or 0.0,
            contract.operator_daily_rate or 0.0,
            contract.mobilization_charge or 0.0,
            contract.demobilization_charge or 0.0,
            contract.security_deposit or 0.0,
        ])
        return commercial_total

    @staticmethod
    def _sum_records(model, field_name, domain):
        if field_name not in model._fields:
            return 0.0
        return sum(model.search(domain).mapped(field_name))
