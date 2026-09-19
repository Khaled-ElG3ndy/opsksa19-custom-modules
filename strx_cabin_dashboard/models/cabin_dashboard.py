# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.tools import format_date, format_datetime


class StrxCabinDashboard(models.AbstractModel):
    """Read-only operational snapshot for the Cabin Control client action."""

    _name = 'strx.cabin.dashboard'
    _description = 'Cabin Operations Dashboard'

    @api.model
    def _assert_dashboard_access(self):
        if not self.env.user.has_group('strx_cabin_security.group_cabin_user'):
            raise AccessError(_(
                "You need a Cabin Rental role to view the Cabin Operations "
                "Dashboard."))

    @api.model
    def _format_date(self, value):
        return format_date(self.env, value) if value else '—'

    @api.model
    def _format_datetime(self, value):
        return format_datetime(self.env, value) if value else '—'

    @api.model
    def _selection_labels(self, model_name, field_name):
        field = self.env[model_name]._fields[field_name]
        return dict(field._description_selection(self.env))

    @api.model
    def get_dashboard_data(self):
        """Return one localized, company-aware dashboard payload.

        Searches deliberately run without sudo so existing record rules and allowed
        companies remain the source of truth. The only elevated reads below are names
        of records already reached through an allowed dashboard record.
        """
        self._assert_dashboard_access()

        Lot = self.env['stock.lot']
        Allocation = self.env['strx.cabin.allocation']
        Shipping = self.env['strx.cabin.shipping.order']
        Substitution = self.env['strx.cabin.substitution']

        cabin_domain = [('strx_is_cabin', '=', True)]
        today = fields.Date.context_today(self)
        horizon = today + timedelta(days=7)

        readiness_labels = self._selection_labels(
            'stock.lot', 'strx_readiness_state')
        allocation_labels = self._selection_labels(
            'strx.cabin.allocation', 'state')
        shipping_labels = self._selection_labels(
            'strx.cabin.shipping.order', 'state')

        status_buckets = [
            {
                'key': 'available',
                'label': _('Available'),
                'states': ['available'],
                'color': '#22B573',
            },
            {
                'key': 'committed',
                'label': _('Committed'),
                'states': ['held', 'reserved', 'allocated', 'staged', 'dispatched'],
                'color': '#5B61D6',
            },
            {
                'key': 'on_rent',
                'label': _('On Rent'),
                'states': ['on_rent'],
                'color': '#2397A5',
            },
            {
                'key': 'service',
                'label': _('Inspection & Service'),
                'states': ['returned', 'in_inspection', 'in_cleaning',
                           'in_maintenance'],
                'color': '#F4A340',
            },
            {
                'key': 'attention',
                'label': _('Needs Attention'),
                'states': ['return_due', 'damaged'],
                'color': '#EE6672',
            },
            {
                'key': 'retired',
                'label': _('Retired'),
                'states': ['retired'],
                'color': '#A6ADBB',
            },
        ]

        total_cabins = Lot.search_count(cabin_domain)
        for bucket in status_buckets:
            bucket['count'] = Lot.search_count(
                cabin_domain + [('strx_readiness_state', 'in', bucket.pop('states'))])
            bucket['percent'] = round(
                100 * bucket['count'] / total_cabins, 1) if total_cabins else 0

        status_by_key = {bucket['key']: bucket['count'] for bucket in status_buckets}
        active_fleet = max(total_cabins - status_by_key['retired'], 0)
        utilization_count = status_by_key['on_rent'] + Lot.search_count(
            cabin_domain + [('strx_readiness_state', '=', 'dispatched')])
        utilization_rate = round(
            100 * utilization_count / active_fleet) if active_fleet else 0

        live_allocation_states = ['draft', 'allocated', 'dispatched', 'on_rent']
        return_states = ['allocated', 'dispatched', 'on_rent']
        overdue_domain = [
            ('state', 'in', return_states),
            ('strx_expected_return_date', '<', today),
        ]
        due_soon_domain = [
            ('state', 'in', return_states),
            ('strx_expected_return_date', '>=', today),
            ('strx_expected_return_date', '<=', horizon),
        ]
        active_shipping_states = ['issued', 'loaded', 'shipped']

        overdue_count = Allocation.search_count(overdue_domain)
        due_soon_count = Allocation.search_count(due_soon_domain)
        pending_substitutions = Substitution.search_count([
            ('state', '=', 'submitted'),
        ])
        active_shipments = Shipping.search_count([
            ('state', 'in', active_shipping_states),
        ])

        recent_allocations = Allocation.search(
            [('state', 'in', live_allocation_states)],
            order='id desc',
            limit=6,
        )
        allocation_rows = []
        for allocation in recent_allocations:
            allocation_rows.append({
                'id': allocation.id,
                'name': allocation.name,
                'order': allocation.order_id.sudo().name or '—',
                'customer': allocation.partner_id.sudo().display_name or '—',
                'serial': ", ".join(allocation.lot_ids.sudo().mapped('name'))
                          or _('Not assigned'),
                'specification': (
                    allocation.strx_cabin_spec
                    or allocation.product_id.sudo().display_name
                    or '—'
                ),
                'state': allocation.state,
                'state_label': allocation_labels.get(
                    allocation.state, allocation.state),
                'return_date': self._format_date(
                    allocation.strx_expected_return_date),
            })

        upcoming_returns = Allocation.search(
            [('state', 'in', return_states),
             ('strx_expected_return_date', '!=', False)],
            order='strx_expected_return_date asc, id desc',
            limit=6,
        )
        return_rows = []
        for allocation in upcoming_returns:
            days = (allocation.strx_expected_return_date - today).days
            if days < 0:
                timing = _(
                    "%(count)s days overdue", count=abs(days))
                timing_tone = 'danger'
            elif days == 0:
                timing = _('Due today')
                timing_tone = 'warning'
            else:
                timing = _(
                    "Due in %(count)s days", count=days)
                timing_tone = 'normal'
            return_rows.append({
                'id': allocation.id,
                'serial': ", ".join(allocation.lot_ids.sudo().mapped('name'))
                          or _('Not assigned'),
                'customer': allocation.partner_id.sudo().display_name or '—',
                'date': self._format_date(allocation.strx_expected_return_date),
                'timing': timing,
                'timing_tone': timing_tone,
            })

        recent_shipments = Shipping.search([], order='id desc', limit=5)
        shipping_rows = []
        for shipment in recent_shipments:
            shipping_rows.append({
                'id': shipment.id,
                'name': shipment.name,
                'order': shipment.order_id.sudo().name or '—',
                'broker': shipment.broker_id.sudo().display_name or '—',
                'origin': shipment.route_origin or '—',
                'destination': shipment.route_destination or '—',
                'state': shipment.state,
                'state_label': shipping_labels.get(
                    shipment.state, shipment.state),
                'scheduled_date': self._format_datetime(shipment.scheduled_date),
            })

        return {
            'company_name': self.env.company.display_name,
            'user_name': self.env.user.name,
            'generated_at': self._format_datetime(fields.Datetime.now()),
            'kpis': {
                'total_cabins': total_cabins,
                'available': status_by_key['available'],
                'on_rent': status_by_key['on_rent'],
                'needs_attention': (
                    status_by_key['service'] + status_by_key['attention']),
                'active_allocations': Allocation.search_count([
                    ('state', 'in', live_allocation_states),
                ]),
                'utilization_rate': utilization_rate,
            },
            'distribution': status_buckets,
            'alerts': {
                'overdue_returns': overdue_count,
                'due_soon_returns': due_soon_count,
                'pending_substitutions': pending_substitutions,
                'active_shipments': active_shipments,
            },
            'recent_allocations': allocation_rows,
            'upcoming_returns': return_rows,
            'recent_shipments': shipping_rows,
            'permissions': {
                'create_allocation': Allocation.browse().has_access('create'),
                'create_shipping': Shipping.browse().has_access('create'),
            },
            'filters': {
                'today': fields.Date.to_string(today),
                'horizon': fields.Date.to_string(horizon),
            },
            'readiness_labels': readiness_labels,
        }
