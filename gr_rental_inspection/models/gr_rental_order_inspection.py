# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class GrRentalOrderInspection(models.Model):
    """Wire inspections into the rental lifecycle:
      - dispatch requires a PASSED delivery inspection (readiness gate);
      - close requires a PASSED return inspection (return lock)."""
    _inherit = 'gr.rental.order'

    inspection_ids = fields.One2many(
        'gr.rental.inspection', 'rental_order_id', string='Inspections')
    inspection_count = fields.Integer(
        string='Inspection Count', compute='_compute_inspection_count')
    delivery_inspection_passed = fields.Boolean(
        string='Delivery Inspection Passed', compute='_compute_inspection_flags')
    return_inspection_passed = fields.Boolean(
        string='Return Inspection Passed', compute='_compute_inspection_flags')

    def _compute_inspection_count(self):
        Insp = self.env['gr.rental.inspection']
        for o in self:
            o.inspection_count = Insp.search_count([('rental_order_id', '=', o.id)])

    @api.depends('inspection_ids.state', 'inspection_ids.mode')
    def _compute_inspection_flags(self):
        for o in self:
            o.delivery_inspection_passed = bool(o.inspection_ids.filtered(
                lambda i: i.mode == 'delivery' and i.state == 'passed'))
            o.return_inspection_passed = bool(o.inspection_ids.filtered(
                lambda i: i.mode == 'return' and i.state == 'passed'))

    # ---- Readiness gate: block dispatch without a passed delivery inspection ----
    def action_dispatch(self):
        for o in self:
            requires_delivery = (
                o.rental_workflow_requires_delivery_inspection
                if 'rental_workflow_requires_delivery_inspection' in o._fields
                else True)
            if requires_delivery and not o.delivery_inspection_passed:
                raise UserError(_(
                    "Cannot dispatch %s: a passed DELIVERY inspection is "
                    "required first (readiness check). Create and pass a "
                    "delivery inspection for this order.") % o.name)
        return super().action_dispatch()

    # ---- Return lock: block close without a passed return inspection ----
    def action_close(self):
        for o in self:
            requires_return = (
                o.rental_workflow_requires_return_inspection
                if 'rental_workflow_requires_return_inspection' in o._fields
                else True)
            if requires_return and not o.return_inspection_passed:
                raise UserError(_(
                    "Cannot close %s: a passed RETURN inspection is required "
                    "first. The unit stays unavailable until the return "
                    "inspection is signed off.") % o.name)
        return super().action_close()

    # ---- On return, auto-create a return inspection to service the lock ----
    def action_return(self):
        res = super().action_return()
        for o in self:
            requires_return = (
                o.rental_workflow_requires_return_inspection
                if 'rental_workflow_requires_return_inspection' in o._fields
                else True)
            if not requires_return:
                continue
            existing = o.inspection_ids.filtered(lambda i: i.mode == 'return')
            if not existing:
                insp = self.env['gr.rental.inspection'].create({
                    'rental_order_id': o.id,
                    'mode': 'return',
                    'current_hours': (
                        o.end_meter_reading or
                        (o.asset_id.current_hour_meter if o.asset_id else 0.0)),
                })
                insp._populate_default_checklist()
                o.message_post(
                    body=_("Return inspection %s auto-created; unit stays "
                           "unavailable until it is passed.") % insp.name,
                    subtype_xmlid='mail.mt_note')
        return res

    def action_create_delivery_inspection(self):
        """Convenience: create a delivery inspection pre-filled with checklist."""
        self.ensure_one()
        insp = self.env['gr.rental.inspection'].create({
            'rental_order_id': self.id,
            'mode': 'delivery',
            'current_hours': (
                self.start_meter_reading or
                (self.asset_id.current_hour_meter if self.asset_id else 0.0)),
        })
        insp._populate_default_checklist()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Delivery Inspection'),
            'res_model': 'gr.rental.inspection',
            'res_id': insp.id,
            'view_mode': 'form',
        }

    def action_view_inspections(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Inspections'),
            'res_model': 'gr.rental.inspection',
            'domain': [('rental_order_id', '=', self.id)],
            'view_mode': 'list,form',
            'context': {'default_rental_order_id': self.id},
        }
