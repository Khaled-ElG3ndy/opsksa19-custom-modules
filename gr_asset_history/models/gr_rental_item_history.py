# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

from .rental_asset_history import history_text


class GrRentalItemUnitHistory(models.Model):
    _inherit = 'gr.rental.item.unit'

    history_ids = fields.One2many(
        'rental.asset.history', 'item_unit_id', string='Asset History',
        readonly=True)
    history_event_count = fields.Integer(
        string='History Events', compute='_compute_history_counts')
    history_rental_order_count = fields.Integer(
        string='Rental Orders', compute='_compute_history_counts')
    history_delivery_count = fields.Integer(
        string='Deliveries', compute='_compute_history_counts')
    history_return_count = fields.Integer(
        string='Returns', compute='_compute_history_counts')
    history_last_event_datetime = fields.Datetime(
        string='Last Movement', readonly=True, copy=False)
    current_presence_type = fields.Selection([
        ('customer', 'At Customer'),
        ('warehouse', 'In Warehouse'),
        ('maintenance', 'In Maintenance'),
        ('transit', 'In Transit'),
        ('reserved', 'Reserved'),
        ('unavailable', 'Unavailable'),
        ('available', 'Available'),
        ('out_of_service', 'Damaged / Out of Service'),
    ], string='Current Presence', compute='_compute_current_presence')
    current_partner_id = fields.Many2one(
        'res.partner', string='Current Customer', readonly=True, copy=False)
    current_rental_order_id = fields.Many2one(
        'gr.rental.order', string='Current Rental Order', readonly=True,
        copy=False)
    current_contract_id = fields.Many2one(
        'gr.rental.contract', string='Current Contract', readonly=True,
        copy=False)
    current_site_id = fields.Many2one(
        'gr.customer.site', string='Current Site', readonly=True, copy=False)
    expected_return_datetime = fields.Datetime(
        string='Expected Return', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        units = super().create(vals_list)
        History = self.env['rental.asset.history']
        for unit in units:
            History.record_event(
                unit,
                event_type='asset_created',
                name=history_text(
                    self.env,
                    _('Rentable item %(item)s created'),
                    item=unit.display_name),
                description=_("Rentable item %(item)s was registered.",
                              item=unit.display_name),
                technical_key='gr.rental.item.unit:%s:asset_created' % unit.id,
                source=unit,
            )
        return units

    def write(self, vals):
        tracked = {'name', 'serial_number', 'specification', 'status',
                   'item_type_id'}
        old_values = {}
        if tracked & set(vals) and not self.env.context.get(
                'gr_skip_history_item_write'):
            for unit in self:
                old_values[unit.id] = {
                    field_name: unit[field_name]
                    for field_name in tracked & set(vals)
                    if field_name in unit._fields
                }
        result = super().write(vals)
        if old_values:
            History = self.env['rental.asset.history']
            now_key = fields.Datetime.now()
            for unit in self:
                changes = []
                business_changes = []
                old_state = False
                new_state = False
                event_type = 'asset_updated'
                for field_name, old_value in old_values.get(unit.id, {}).items():
                    new_value = unit[field_name]
                    old_label = self._history_display_value(old_value)
                    new_label = self._history_display_value(new_value)
                    if old_label == new_label:
                        continue
                    if field_name == 'status':
                        old_state = old_label
                        new_state = new_label
                        continue
                    change_line = "%s: %s -> %s" % (
                        unit._fields[field_name].string, old_label or '-',
                        new_label or '-')
                    changes.append(change_line)
                    business_changes.append(change_line)
                if event_type == 'asset_updated' and not business_changes:
                    continue
                if changes:
                    History.record_event(
                        unit,
                        event_type=event_type,
                        name=history_text(
                            self.env,
                            _('Rentable item %(item)s data updated'),
                            item=unit.display_name),
                        description='\n'.join(changes),
                        old_state=old_state,
                        new_state=new_state,
                        technical_key='gr.rental.item.unit:%s:write:%s:%s' % (
                            unit.id, now_key, self.env.user.id),
                        source=unit,
                    )
        return result

    def _history_display_value(self, value):
        if hasattr(value, 'display_name'):
            return value.display_name
        return value or False

    def _compute_history_counts(self):
        History = self.env['rental.asset.history']
        Line = self.env['gr.rental.order.line']
        base = {unit_id: 0 for unit_id in self.ids}
        totals = dict(base)
        for unit, count in History._read_group([
                ('item_unit_id', 'in', self.ids),
                ('is_technical_event', '=', False),
        ], ['item_unit_id'], ['__count']):
            totals[unit.id] = count
        order_counts = dict(base)
        for unit, __ in Line._read_group([
                ('item_unit_id', 'in', self.ids),
        ], ['item_unit_id', 'order_id']):
            order_counts[unit.id] += 1
        deliveries = dict(base)
        returns = dict(base)
        for field_name, target, event_types in [
                ('delivery', deliveries, ['delivery', 'installed']),
                ('return', returns, ['return'])]:
            for unit, count in History._read_group([
                    ('item_unit_id', 'in', self.ids),
                    ('event_type', 'in', event_types),
            ], ['item_unit_id'], ['__count']):
                target[unit.id] = count
        for unit in self:
            unit.history_event_count = totals.get(unit.id, 0)
            unit.history_rental_order_count = order_counts.get(unit.id, 0)
            unit.history_delivery_count = deliveries.get(unit.id, 0)
            unit.history_return_count = returns.get(unit.id, 0)

    @api.depends('status', 'current_partner_id', 'current_rental_order_id.state')
    def _compute_current_presence(self):
        for unit in self:
            order_state = unit.current_rental_order_id.state
            if order_state == 'reserved':
                unit.current_presence_type = 'reserved'
            elif order_state == 'dispatched':
                unit.current_presence_type = 'transit'
            elif order_state in ('installed', 'on_rent', 'off_hire_requested') \
                    and unit.current_partner_id:
                unit.current_presence_type = 'customer'
            elif unit.status == 'maintenance':
                unit.current_presence_type = 'maintenance'
            elif unit.status == 'unavailable':
                unit.current_presence_type = 'unavailable'
            elif unit.status == 'retired':
                unit.current_presence_type = 'out_of_service'
            else:
                unit.current_presence_type = 'available'

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
            [('item_unit_id', '=', self.id)],
            {
                'default_item_unit_id': self.id,
                'search_default_f_business_events': 1,
            })

    def action_view_history_rental_orders(self):
        self.ensure_one()
        order_ids = self.env['gr.rental.order.line'].search([
            ('item_unit_id', '=', self.id),
        ]).mapped('order_id').ids
        return self._history_action(
            _('Rental Orders'), 'gr.rental.order',
            [('id', 'in', order_ids)])

    def action_view_history_deliveries(self):
        self.ensure_one()
        return self._history_action(
            _('Deliveries'), 'rental.asset.history',
            [('item_unit_id', '=', self.id),
             ('event_type', 'in', ['delivery', 'installed'])])

    def action_view_history_returns(self):
        self.ensure_one()
        return self._history_action(
            _('Returns'), 'rental.asset.history',
            [('item_unit_id', '=', self.id), ('event_type', '=', 'return')])
