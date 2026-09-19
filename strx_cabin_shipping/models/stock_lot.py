# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    strx_cabin_history_count = fields.Integer(
        string='Cabin History',
        compute='_compute_strx_cabin_history_count')

    def _compute_strx_cabin_history_count(self):
        Readiness = self.env['strx.cabin.readiness.log']
        Allocation = self.env['strx.cabin.allocation']
        Shipping = self.env['strx.cabin.shipping.order']
        for lot in self:
            if not lot.strx_is_cabin:
                lot.strx_cabin_history_count = 0
                continue
            lot.strx_cabin_history_count = (
                Readiness.search_count([('lot_id', '=', lot.id)])
                + Allocation.search_count([('lot_ids', 'in', lot.id)])
                + Shipping.search_count([('lot_ids', 'in', lot.id)])
            )

    def _strx_selection_label(self, field, value):
        if not value:
            return '-'
        labels = dict(field._description_selection(self.env))
        return labels.get(value, value)

    def _strx_history_create_readiness_events(self, Event):
        self.ensure_one()
        values = []
        for log in self.env['strx.cabin.readiness.log'].search([
            ('lot_id', '=', self.id),
        ]):
            old_state = self._strx_selection_label(log._fields['old_state'], log.old_state)
            new_state = self._strx_selection_label(log._fields['new_state'], log.new_state)
            title = _('Readiness changed')
            details = _('From: %(old)s\nTo: %(new)s\nReason: %(reason)s\nBy: %(user)s') % {
                'old': old_state,
                'new': new_state,
                'reason': log.reason or '-',
                'user': log.user_id.display_name or '-',
            }
            values.append({
                'lot_id': self.id,
                'event_date': log.event_date,
                'event_type': 'readiness',
                'title': title,
                'reference': log.display_name or '-',
                'details': details,
            })
        if values:
            Event.create(values)

    def _strx_history_create_allocation_events(self, Event):
        self.ensure_one()
        values = []
        state_field = self.env['strx.cabin.allocation']._fields['state']
        for alloc in self.env['strx.cabin.allocation'].search([
            ('lot_ids', 'in', self.id),
        ], order='create_date desc, id desc'):
            state = self._strx_selection_label(state_field, alloc.state)
            title = _('Allocation %(ref)s') % {'ref': alloc.name}
            details = _('Rental Order: %(order)s\nCustomer: %(customer)s\nStatus: %(state)s\nDispatch: %(out)s\nExpected Return: %(ret)s\nActual Return: %(actual)s') % {
                'order': alloc.order_id.display_name or '-',
                'customer': alloc.partner_id.display_name or '-',
                'state': state,
                'out': alloc.strx_date_out or '-',
                'ret': alloc.strx_expected_return_date or '-',
                'actual': alloc.strx_actual_return_date or '-',
            }
            values.append({
                'lot_id': self.id,
                'event_date': alloc.write_date or alloc.create_date,
                'event_type': 'allocation',
                'title': title,
                'reference': alloc.name,
                'partner_id': alloc.partner_id.id,
                'details': details,
            })
        if values:
            Event.create(values)

    def _strx_history_create_shipment_events(self, Event):
        self.ensure_one()
        values = []
        Shipping = self.env['strx.cabin.shipping.order']
        state_field = Shipping._fields['state']
        movement_field = Shipping._fields['movement_type']
        for shipment in Shipping.search([
            ('lot_ids', 'in', self.id),
        ], order='create_date desc, id desc'):
            movement = self._strx_selection_label(movement_field, shipment.movement_type)
            state = self._strx_selection_label(state_field, shipment.state)
            title = _('Shipment %(ref)s — %(movement)s') % {
                'ref': shipment.name,
                'movement': movement,
            }
            details = _('Rental Order: %(order)s\nCustomer: %(customer)s\nBroker: %(broker)s\nStatus: %(state)s\nRoute: %(origin)s → %(destination)s\nPlanned: %(planned)s\nShipped: %(shipped)s\nDelivered: %(delivered)s\nCost: %(cost)s') % {
                'order': shipment.order_id.display_name or '-',
                'customer': shipment.partner_id.display_name or '-',
                'broker': shipment.broker_id.display_name or '-',
                'state': state,
                'origin': shipment.route_origin or '-',
                'destination': shipment.route_destination or '-',
                'planned': shipment.scheduled_date or '-',
                'shipped': shipment.shipped_date or '-',
                'delivered': shipment.delivered_date or '-',
                'cost': "%s %s" % (shipment.agreed_cost or 0.0, shipment.currency_id.symbol or ''),
            }
            values.append({
                'lot_id': self.id,
                'event_date': shipment.delivered_date or shipment.shipped_date
                              or shipment.scheduled_date or shipment.write_date
                              or shipment.create_date,
                'event_type': 'shipment',
                'title': title,
                'reference': shipment.name,
                'partner_id': shipment.partner_id.id,
                'details': details,
            })
        if values:
            Event.create(values)

    def action_strx_open_cabin_history(self):
        self.ensure_one()
        Event = self.env['strx.cabin.history.event']
        old_events = Event.search([
            ('create_uid', '=', self.env.uid),
            ('lot_id', '=', self.id),
        ])
        old_events.unlink()
        self._strx_history_create_readiness_events(Event)
        self._strx_history_create_allocation_events(Event)
        self._strx_history_create_shipment_events(Event)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cabin History'),
            'res_model': 'strx.cabin.history.event',
            'view_mode': 'list,form',
            'domain': [('lot_id', '=', self.id), ('create_uid', '=', self.env.uid)],
            'context': {'create': False, 'edit': False, 'delete': False},
            'target': 'current',
        }
