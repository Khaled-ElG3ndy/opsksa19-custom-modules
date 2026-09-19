# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

from .rental_asset_history import history_text


class GrGeneratorAssetHistory(models.Model):
    _inherit = 'gr.generator.asset'

    history_ids = fields.One2many(
        'rental.asset.history', 'asset_id', string='Asset History',
        readonly=True)
    history_rental_line_ids = fields.One2many(
        'rental.asset.rental.history', 'asset_id',
        string='Rental Operations', readonly=True)
    history_event_count = fields.Integer(
        string='History Events', compute='_compute_history_counts')
    history_rental_order_count = fields.Integer(
        string='Rental Orders', compute='_compute_history_counts')
    history_contract_count = fields.Integer(
        string='Contracts', compute='_compute_history_counts')
    history_delivery_count = fields.Integer(
        string='Deliveries', compute='_compute_history_counts')
    history_return_count = fields.Integer(
        string='Returns', compute='_compute_history_counts')
    history_repair_count = fields.Integer(
        string='Repairs / Breakdowns', compute='_compute_history_counts')
    history_inspection_count = fields.Integer(
        string='Inspections', compute='_compute_history_counts')
    history_visit_count = fields.Integer(
        string='Visits', compute='_compute_history_counts')
    history_last_event_datetime = fields.Datetime(
        string='Last Movement', readonly=True, copy=False)
    history_total_rental_days = fields.Float(
        string='Total Rental Days', compute='_compute_history_summary')
    history_last_maintenance_id = fields.Many2one(
        'gr.maintenance.job', string='Last Maintenance',
        compute='_compute_history_summary')
    history_last_maintenance_date = fields.Datetime(
        string='Last Maintenance Date', compute='_compute_history_summary')
    history_breakdown_count = fields.Integer(
        string='Breakdowns / Repairs', compute='_compute_history_summary')
    history_total_parts_cost = fields.Monetary(
        string='Total Parts Cost', currency_field='currency_id',
        compute='_compute_history_summary')

    current_presence_type = fields.Selection([
        ('customer', 'At Customer'),
        ('warehouse', 'In Warehouse'),
        ('maintenance', 'In Maintenance'),
        ('inspection', 'Under Inspection'),
        ('transit', 'In Transit'),
        ('reserved', 'Reserved'),
        ('unavailable', 'Unavailable'),
        ('available', 'Available'),
        ('out_of_service', 'Damaged / Out of Service'),
    ], string='Current Presence', compute='_compute_current_presence',
        store=True, readonly=True)
    current_rental_order_id = fields.Many2one(
        'gr.rental.order', string='Current Rental Order', readonly=True,
        copy=False)
    current_contract_id = fields.Many2one(
        'gr.rental.contract', string='Current Contract', readonly=True,
        copy=False)
    current_site_id = fields.Many2one(
        'gr.customer.site', string='Current Site', readonly=True, copy=False)
    current_location_label = fields.Char(
        string='Current Location', compute='_compute_current_presence',
        store=True, readonly=True)
    expected_return_datetime = fields.Datetime(
        string='Expected Return', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        assets = super().create(vals_list)
        History = self.env['rental.asset.history']
        for asset in assets:
            History.record_event(
                asset,
                event_type='asset_created',
                name=history_text(
                    self.env,
                    _('Asset %(asset)s created'),
                    asset=asset.display_name),
                description=_("Asset %(asset)s was registered in the system.",
                              asset=asset.display_name),
                technical_key='gr.generator.asset:%s:asset_created' % asset.id,
                source=asset,
            )
        return assets

    def write(self, vals):
        tracked_fields = {
            'name', 'code', 'serial_number', 'brand', 'model_name',
            'kva_rating', 'status', 'depot_location_id',
            'current_customer_id', 'current_site_ref',
            'current_contract_ref', 'current_rental_order_ref',
            'owner_type', 'owner_partner_id', 'active',
        }
        old_values = {}
        if tracked_fields & set(vals) and not self.env.context.get(
                'gr_skip_history_asset_write'):
            for asset in self:
                old_values[asset.id] = {
                    field_name: asset[field_name]
                    for field_name in tracked_fields & set(vals)
                    if field_name in asset._fields
                }
        result = super().write(vals)
        if old_values:
            History = self.env['rental.asset.history']
            now_key = fields.Datetime.now()
            routine_fields = {
                'status', 'current_customer_id', 'current_site_ref',
                'current_contract_ref', 'current_rental_order_ref',
            }
            for asset in self:
                before = old_values.get(asset.id, {})
                changes = []
                business_changes = []
                event_type = 'asset_updated'
                old_state = False
                new_state = False
                for field_name, old_value in before.items():
                    new_value = asset[field_name]
                    old_label = self._history_display_value(old_value)
                    new_label = self._history_display_value(new_value)
                    if old_label == new_label:
                        continue
                    if field_name == 'status':
                        status_event_type = self._history_status_event_type(
                            old_value, new_value)
                        if not status_event_type:
                            continue
                        event_type = status_event_type
                        old_state = old_label
                        new_state = new_label
                    change_line = "%s: %s -> %s" % (
                        asset._fields[field_name].string, old_label or '-',
                        new_label or '-')
                    changes.append(change_line)
                    if field_name not in routine_fields:
                        business_changes.append(change_line)
                if event_type == 'asset_updated' and not business_changes:
                    continue
                if changes:
                    History.record_event(
                        asset,
                        event_type=event_type,
                        name=history_text(
                            self.env,
                            _('Asset %(asset)s data updated'),
                            asset=asset.display_name),
                        description='\n'.join(changes),
                        old_state=old_state,
                        new_state=new_state,
                        partner=asset.current_customer_id,
                        technical_key='gr.generator.asset:%s:write:%s:%s' % (
                            asset.id, now_key, self.env.user.id),
                        source=asset,
                    )
        return result

    def _history_display_value(self, value):
        if hasattr(value, 'display_name'):
            return value.display_name
        if isinstance(value, bool):
            return _('Yes') if value else _('No')
        return value or False

    def _history_status_event_type(self, old_status, new_status):
        if new_status == 'breakdown':
            return 'breakdown_reported'
        if new_status == 'retired':
            return 'asset_retired'
        if old_status == 'retired' and new_status == 'available':
            return 'asset_reactivated'
        return False

    def _compute_history_counts(self):
        History = self.env['rental.asset.history']
        RentalLine = self.env['rental.asset.rental.history']
        ids = self.ids
        base = {asset_id: 0 for asset_id in ids}
        total = dict(base)
        for asset, count in History._read_group(
                [('asset_id', 'in', ids), ('is_technical_event', '=', False)],
                ['asset_id'], ['__count']):
            total[asset.id] = count
        rental_orders = dict(base)
        rental_sets = {asset_id: set() for asset_id in ids}
        for asset, order in RentalLine._read_group([
                ('asset_id', 'in', ids),
                ('rental_order_id', '!=', False),
        ], ['asset_id', 'rental_order_id']):
            rental_sets[asset.id].add(order.id)
        for asset_id, order_ids in rental_sets.items():
            rental_orders[asset_id] = len(order_ids)
        by_type = {}
        type_groups = [
            ('history_delivery_count', ['delivery', 'installed']),
            ('history_return_count', ['return']),
            ('history_repair_count', [
                'breakdown_reported', 'damage_found', 'maintenance_opened',
                'maintenance_scheduled', 'maintenance_started',
                'maintenance_done', 'maintenance_cancelled', 'parts_used']),
            ('history_inspection_count', [
                'inspection_created', 'inspection_passed', 'inspection_failed',
                'inspection_started']),
            ('history_visit_count', [
                'visit_created', 'visit_submitted', 'visit_verified']),
        ]
        for field_name, event_types in type_groups:
            counts = dict(base)
            for asset, count in History._read_group([
                    ('asset_id', 'in', ids),
                    ('event_type', 'in', event_types),
            ], ['asset_id'], ['__count']):
                counts[asset.id] = count
            by_type[field_name] = counts

        contract_sets = {asset_id: set() for asset_id in ids}
        for asset, contract in RentalLine._read_group([
                ('asset_id', 'in', ids),
                ('contract_id', '!=', False),
        ], ['asset_id', 'contract_id']):
            contract_sets[asset.id].add(contract.id)
        for asset, contract in History._read_group([
                ('asset_id', 'in', ids),
                ('contract_id', '!=', False),
        ], ['asset_id', 'contract_id']):
            contract_sets[asset.id].add(contract.id)

        for asset in self:
            asset.history_event_count = total.get(asset.id, 0)
            asset.history_rental_order_count = rental_orders.get(asset.id, 0)
            asset.history_contract_count = len(contract_sets.get(asset.id, set()))
            for field_name, counts in by_type.items():
                asset[field_name] = counts.get(asset.id, 0)

    def _compute_history_summary(self):
        RentalLine = self.env['rental.asset.rental.history']
        Job = self.env['gr.maintenance.job']
        has_parts_cost = 'total_parts_cost' in Job._fields
        for asset in self:
            rental_lines = RentalLine.search([('asset_id', '=', asset.id)])
            asset.history_total_rental_days = sum(
                rental_lines.mapped('duration_days'))
            jobs = Job.search([('asset_id', '=', asset.id)])
            ordered_jobs = jobs.sorted(
                key=lambda job: (
                    job.completed_date
                    or job.started_date
                    or job.scheduled_date
                    or fields.Datetime.to_datetime('1970-01-01 00:00:00')),
                reverse=True)
            last_job = ordered_jobs[:1]
            asset.history_last_maintenance_id = last_job
            asset.history_last_maintenance_date = (
                last_job.completed_date
                or last_job.started_date
                or last_job.scheduled_date
                if last_job else False)
            asset.history_breakdown_count = len(jobs.filtered(
                lambda job: job.job_type in ('breakdown', 'corrective')))
            asset.history_total_parts_cost = (
                sum(jobs.mapped('total_parts_cost')) if has_parts_cost else 0.0)

    @api.depends('status', 'current_customer_id', 'current_site_id',
                 'depot_location_id', 'current_rental_order_id')
    def _compute_current_presence(self):
        for asset in self:
            status = asset.status
            if status in ('on_rent', 'installed') and asset.current_customer_id:
                asset.current_presence_type = 'customer'
            elif status == 'reserved':
                asset.current_presence_type = 'reserved'
            elif status == 'in_transit':
                asset.current_presence_type = 'transit'
            elif status in ('under_maintenance', 'maintenance_due'):
                asset.current_presence_type = 'maintenance'
            elif status == 'returned_pending_inspection':
                asset.current_presence_type = 'inspection'
            elif status in ('breakdown', 'retired'):
                asset.current_presence_type = 'out_of_service'
            elif status == 'unavailable':
                asset.current_presence_type = 'unavailable'
            else:
                asset.current_presence_type = 'available'
            asset.current_location_label = (
                asset.current_site_id.display_name
                or asset.current_site_ref
                or asset.depot_location_id.display_name
                or asset.current_customer_id.display_name
                or False)

    def _history_action(self, name, model, domain, context=None):
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': 'list,form',
            'domain': domain,
            'context': context or {},
        }

    def action_view_asset_history(self):
        self.ensure_one()
        return self._history_action(
            _('Asset History'), 'rental.asset.history',
            [('asset_id', '=', self.id)],
            {
                'default_asset_id': self.id,
                'search_default_f_business_events': 1,
            })

    def action_view_history_rental_orders(self):
        self.ensure_one()
        order_ids = self.history_rental_line_ids.mapped('rental_order_id').ids
        return self._history_action(
            _('Rental Orders'), 'gr.rental.order', [('id', 'in', order_ids)],
            {'default_asset_id': self.id})

    def action_view_history_contracts(self):
        self.ensure_one()
        contract_ids = self.history_ids.mapped('contract_id').ids
        contract_ids += self.env['gr.rental.order'].search([
            ('asset_id', '=', self.id),
            ('contract_id', '!=', False),
        ]).mapped('contract_id').ids
        return self._history_action(
            _('Contracts'), 'gr.rental.contract',
            [('id', 'in', list(set(contract_ids)))])

    def action_view_history_deliveries(self):
        self.ensure_one()
        return self._history_action(
            _('Deliveries'), 'rental.asset.history',
            [('asset_id', '=', self.id),
             ('event_type', 'in', ['delivery', 'installed'])])

    def action_view_history_returns(self):
        self.ensure_one()
        return self._history_action(
            _('Returns'), 'rental.asset.history',
            [('asset_id', '=', self.id), ('event_type', '=', 'return')])

    def action_view_history_repairs(self):
        self.ensure_one()
        return self._history_action(
            _('Repairs / Breakdowns'), 'rental.asset.history',
            [('asset_id', '=', self.id),
             ('event_type', 'in', ['breakdown_reported', 'damage_found'])])

    def action_view_history_inspections(self):
        self.ensure_one()
        return self._history_action(
            _('Inspections'), 'gr.rental.inspection',
            [('asset_id', '=', self.id)])

    def action_view_history_visits(self):
        self.ensure_one()
        return self._history_action(
            _('Visits'), 'gr.field.worksheet', [('asset_id', '=', self.id)])
