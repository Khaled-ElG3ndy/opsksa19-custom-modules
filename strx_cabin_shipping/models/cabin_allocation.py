# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StrxCabinAllocation(models.Model):
    _inherit = 'strx.cabin.allocation'

    strx_shipping_order_ids = fields.Many2many(
        'strx.cabin.shipping.order',
        'strx_cabin_allocation_shipping_order_rel',
        'allocation_id',
        'shipping_order_id',
        string='Shipments',
        readonly=True,
        copy=False)
    strx_shipping_count = fields.Integer(
        string='Shipment Count', compute='_compute_strx_shipping_count')

    @api.depends('strx_shipping_order_ids')
    def _compute_strx_shipping_count(self):
        for allocation in self:
            allocation.strx_shipping_count = len(
                allocation.strx_shipping_order_ids)

    def action_create_delivery_shipment(self):
        self.ensure_one()
        if self.state != 'allocated':
            raise UserError(_(
                "Delivery shipments can only be created from allocated cabins."))
        if not self.lot_ids:
            raise UserError(_("Select and allocate the required serials before creating shipment."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Delivery Shipment'),
            'res_model': 'strx.cabin.shipping.order',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_order_id': self.order_id.id,
                'default_movement_type': 'delivery',
                'default_lot_ids': [(6, 0, self.lot_ids.ids)],
                'default_route_origin': self.company_id.name or '',
                'default_route_destination': self.partner_id.display_name or '',
            },
        }

    def action_create_return_shipment(self):
        self.ensure_one()
        if self.state != 'on_rent':
            raise UserError(_(
                "Return shipments can only be created from on-rent cabins."))
        if not self.lot_ids:
            raise UserError(_("This rented cabin allocation has no serials to return."))
        invalid = self.lot_ids.filtered(
            lambda lot: lot.strx_readiness_state not in ('on_rent', 'return_due'))
        if invalid:
            raise UserError(_(
                "Serial %(serial)s is not ready for a return shipment.",
                serial=invalid[0].name))
        shipment = self._strx_create_instant_return_shipment()
        message = _('Cabin %(serial)s was returned on shipment %(shipment)s.') % {
            'serial': ", ".join(self.lot_ids.mapped('name')),
            'shipment': shipment.name,
        }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Return completed'),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            },
        }

    def action_view_shipping_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Shipments'),
            'res_model': 'strx.cabin.shipping.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.strx_shipping_order_ids.ids)],
            'context': {'create': False},
        }

    def _strx_create_instant_return_shipment(self):
        self.ensure_one()
        Shipping = self.env['strx.cabin.shipping.order']
        previous = Shipping.search([
            ('order_id', '=', self.order_id.id),
            ('lot_ids', 'in', self.lot_ids.ids),
            ('broker_id', '!=', False),
            ('state', '!=', 'cancel'),
        ], order='id desc', limit=1)
        broker = previous.broker_id or self.env['strx.cabin.broker'].search([
            ('is_internal', '=', True),
            ('active', '=', True),
        ], limit=1)
        if not broker:
            broker = self.env['strx.cabin.broker'].create({
                'name': self.company_id.name or _('Internal Return'),
                'is_internal': True,
                'contact_name': self.env.user.name,
                'contact_phone': self.env.user.partner_id.phone or '',
            })
        now = fields.Datetime.now()
        shipment_vals = {
            'broker_id': broker.id,
            'order_id': self.order_id.id,
            'movement_type': 'return',
            'lot_ids': [(6, 0, self.lot_ids.ids)],
            'route_origin': self.partner_id.display_name or '',
            'route_destination': self.company_id.name or '',
            'scheduled_date': now,
            'loaded_date': now,
            'shipped_date': now,
            'delivered_date': now,
            'agreed_cost': 0.0,
            'driver_name': previous.driver_name or self.env.user.name,
            'driver_id_number': previous.driver_id_number or _('Auto Return'),
            'driver_phone': previous.driver_phone or self.env.user.partner_id.phone or '',
            'vehicle_model': previous.vehicle_model or _('Auto Return'),
            'vehicle_plate': previous.vehicle_plate or _('Auto Return'),
            'route_note': _('Instant return created from allocation %(allocation)s.') % {'allocation': self.name},
        }
        shipment = Shipping.create(shipment_vals)
        shipment.write({'state': 'shipped'})
        shipment._strx_sync_delivery('ship')
        shipment.write({'state': 'delivered'})
        shipment._strx_sync_delivery('deliver')
        return shipment

    def action_view_return_shipments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Return Shipments'),
            'res_model': 'strx.cabin.shipping.order',
            'view_mode': 'list,form',
            'domain': [
                ('order_id', '=', self.order_id.id),
                ('movement_type', '=', 'return'),
                ('lot_ids', 'in', self.lot_ids.ids),
            ],
            'context': {
                'default_order_id': self.order_id.id,
                'default_movement_type': 'return',
                'default_lot_ids': [(6, 0, self.lot_ids.ids)] if self.lot_ids else False,
                'default_route_origin': self.partner_id.display_name or '',
                'default_route_destination': self.company_id.name or '',
            },
        }
