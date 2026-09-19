# -*- coding: utf-8 -*-
from datetime import date, timedelta
from markupsafe import Markup
from odoo import api, fields, models, tools
from odoo.tools import LazyTranslate


_lt = LazyTranslate(__name__)


# active "unit is out with the customer" states
_OUT_STATES = ('dispatched', 'installed', 'on_rent', 'off_hire_requested')


def _working_days_between(start, end):
    """Count working days from start to end (exclusive of Friday).
    Positive if end is after start; negative if end is before start.
    Working days = all days except Friday (weekday() == 4)."""
    if not start or not end:
        return None
    step = 1 if end >= start else -1
    days = 0
    d = start
    while d != end:
        d = d + timedelta(days=step)
        if d.weekday() != 4:  # skip Friday
            days += step
    return days


class GrRentalOrderReturnAlert(models.Model):
    _inherit = 'gr.rental.order'

    return_bucket = fields.Selection([
        ('none', 'Not due soon'),
        ('due_3', 'Due within 3 working days'),
        ('due_today', 'Due today'),
        ('overdue', 'Overdue'),
    ], string='Return Status', default='none', index=True, copy=False,
        help="Working-day-aware classification of the planned return date.")
    working_days_to_return = fields.Integer(
        string='Working Days to Return', copy=False,
        help="Working days (Friday excluded) until the planned return. "
             "Negative = days overdue.")
    return_alert_sent_for = fields.Char(
        string='Last Alert Bucket Sent', copy=False,
        help="Guards against sending the same alert twice for the same return "
             "stage and planned return date.")

    def _compute_return_bucket_value(self, today=None):
        """Return (bucket, working_days) for this order without writing."""
        self.ensure_one()
        today = today or fields.Date.context_today(self)
        if self.state not in _OUT_STATES or not self.planned_return_datetime:
            return ('none', 0)
        due = fields.Datetime.to_datetime(self.planned_return_datetime).date()
        wd = _working_days_between(today, due)
        if wd is None:
            return ('none', 0)
        if wd < 0:
            return ('overdue', wd)
        if wd == 0:
            return ('due_today', 0)
        if wd <= 3:
            return ('due_3', wd)
        return ('none', wd)

    @api.model
    def _cron_evaluate_returns(self):
        """Hourly: classify active rentals, raise one alert per return stage."""
        today = fields.Date.context_today(self)
        orders = self.search([('state', 'in', _OUT_STATES),
                              ('planned_return_datetime', '!=', False)])
        # Odoo 19 renamed res.groups.users to user_ids.
        Managers = self.env.ref(
            'gr_security_base.group_generator_operations_officer').user_ids
        template = self.env.ref(
            'gr_return_alerts.mail_template_return_due', raise_if_not_found=False)
        for o in orders:
            bucket, wd = o._compute_return_bucket_value(today)
            o.write({'return_bucket': bucket, 'working_days_to_return': wd})
            if bucket in ('due_3', 'due_today', 'overdue'):
                o._raise_return_activity(bucket)
                # Email once per bucket for the planned return date. This keeps
                # hourly cron runs from repeating the same due/overdue email.
                due_date = fields.Datetime.to_datetime(
                    o.planned_return_datetime).date()
                stamp = '%s:%s' % (bucket, due_date)
                if o.return_alert_sent_for != stamp:
                    if template and bucket in ('due_today', 'overdue'):
                        for mgr in Managers:
                            if mgr.email:
                                template.with_context(
                                    lang=mgr.lang or self.env.lang).send_mail(
                                    o.id, force_send=False,
                                    email_values={'email_to': mgr.email})
                    o.return_alert_sent_for = stamp
        return True

    def _return_alert_asset_names(self):
        self.ensure_one()
        assets = []
        if self.asset_id:
            assets.append(self.asset_id.display_name)
        if 'item_line_ids' in self._fields:
            for line in self.item_line_ids:
                item = line.item_unit_id or line.item_type_id
                if item:
                    assets.append(item.display_name)
        assets = list(dict.fromkeys(filter(None, assets)))
        return ', '.join(assets) if assets else self.env._(_lt('Not specified'))

    def _return_alert_due_date(self):
        self.ensure_one()
        if not self.planned_return_datetime:
            return self.env._(_lt('Not specified'))
        due_date = fields.Datetime.to_datetime(
            self.planned_return_datetime).date()
        return tools.format_date(self.env, due_date)

    def _return_alert_values(self, bucket=False):
        self.ensure_one()
        bucket = bucket or self.return_bucket
        return {
            'order': self.name or '',
            'customer': self.partner_id.display_name or '',
            'asset': self._return_alert_asset_names(),
            'return_date': self._return_alert_due_date(),
            'overdue_days': abs(self.working_days_to_return or 0),
            'bucket': bucket,
        }

    def _return_alert_texts(self, bucket=False):
        self.ensure_one()
        vals = self._return_alert_values(bucket)
        bucket = vals['bucket']
        if bucket == 'due_3':
            return {
                'title': self.env._(
                    _lt('Asset return due within 3 business days')),
                'description': self.env._(
                    _lt('Rental order %(order)s for customer %(customer)s and '
                        'asset %(asset)s is expected to be returned on '
                        '%(return_date)s. There are 3 business days remaining. '
                        'Please contact the customer and confirm that the asset '
                        'will be ready for return on time.', **vals)),
                'subject': self.env._(
                    _lt('Alert: Asset return due within 3 business days - '
                        '%(order)s', **vals)),
            }
        if bucket == 'due_today':
            return {
                'title': self.env._(_lt('Asset return is due today')),
                'description': self.env._(
                    _lt('Rental order %(order)s for customer %(customer)s and '
                        'asset %(asset)s is due for return today, '
                        '%(return_date)s. Please follow up with the customer '
                        'and confirm collection of the asset today.', **vals)),
                'subject': self.env._(
                    _lt('Alert: Asset return due today - %(order)s', **vals)),
            }
        if bucket == 'overdue':
            return {
                'title': self.env._(_lt('Asset return is overdue')),
                'description': self.env._(
                    _lt('Rental order %(order)s for customer %(customer)s and '
                        'asset %(asset)s was due for return on %(return_date)s '
                        'and is now overdue by %(overdue_days)s business '
                        'day(s). Please take the required action and contact '
                        'the customer immediately.', **vals)),
                'subject': self.env._(
                    _lt('Alert: Asset return is overdue - %(order)s', **vals)),
            }
        return {
            'title': self.env._(_lt('Asset return reminder')),
            'description': '',
            'subject': self.env._(
                _lt('Alert: Asset return reminder - %(order)s', **vals)),
        }

    def _return_alert_email_subject(self):
        self.ensure_one()
        return self._return_alert_texts().get('subject')

    def _return_alert_url(self):
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', default='')
        return '%s/web#id=%s&model=gr.rental.order&view_type=form' % (
            base_url.rstrip('/'), self.id)

    def _return_alert_email_body_html(self):
        self.ensure_one()
        texts = self._return_alert_texts()
        vals = self._return_alert_values()
        return Markup(
            '<div style="font-family:Arial,sans-serif;">'
            '<p>%s</p>'
            '<ul>'
            '<li><strong>%s</strong> %s</li>'
            '<li><strong>%s</strong> %s</li>'
            '<li><strong>%s</strong> %s</li>'
            '<li><strong>%s</strong> %s</li>'
            '</ul>'
            '<p><a href="%s">%s</a></p>'
            '</div>'
        ) % (
            tools.html_escape(texts.get('description') or ''),
            tools.html_escape(self.env._(_lt('Rental Order:'))),
            tools.html_escape(vals['order']),
            tools.html_escape(self.env._(_lt('Customer:'))),
            tools.html_escape(vals['customer']),
            tools.html_escape(self.env._(_lt('Asset(s):'))),
            tools.html_escape(vals['asset']),
            tools.html_escape(self.env._(_lt('Planned Return:'))),
            tools.html_escape(vals['return_date']),
            tools.html_escape(self._return_alert_url()),
            tools.html_escape(self.env._(_lt('Open rental order'))),
        )

    def _raise_return_activity(self, bucket):
        """Raise a to-do activity on the salesperson / responsible user."""
        self.ensure_one()
        act_type = self.env.ref('mail.mail_activity_data_todo',
                                raise_if_not_found=False)
        if not act_type:
            return
        user = self.create_uid or self.env.user
        order_for_user = self.with_context(lang=user.lang or self.env.lang)
        texts = order_for_user._return_alert_texts(bucket)
        summary = texts['title']
        due_date = fields.Datetime.to_datetime(
            self.planned_return_datetime).date()
        # Keep one open activity per return stage. A rental can therefore move
        # due_3 -> due_today -> overdue and get one alert for each stage, while
        # repeated hourly cron runs do not create duplicates in the same stage.
        existing = self.env['mail.activity'].search([
            ('res_model', '=', 'gr.rental.order'),
            ('res_id', '=', self.id),
            ('activity_type_id', '=', act_type.id),
            ('summary', '=', summary),
            ('date_deadline', '=', due_date),
        ], limit=1)
        if not existing:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=summary,
                note=texts['description'],
                date_deadline=due_date,
                user_id=user.id)
        return True
