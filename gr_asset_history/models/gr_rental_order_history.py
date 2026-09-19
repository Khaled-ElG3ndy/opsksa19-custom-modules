# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

from .rental_asset_history import history_text


class GrRentalOrderHistory(models.Model):
    _inherit = 'gr.rental.order'

    def _history_targets(self):
        self.ensure_one()
        targets = []
        if self.asset_id:
            targets.append(('asset', self.asset_id))
        for line in self.item_line_ids:
            if 'is_primary_asset_line' in line._fields and line.is_primary_asset_line:
                continue
            if line.equipment_asset_id:
                targets.append(('asset', line.equipment_asset_id))
            if line.item_unit_id:
                targets.append(('item', line.item_unit_id))
        return targets

    def _asset_rental_history_targets(self):
        self.ensure_one()
        targets = []
        if self.asset_id:
            targets.append((self.asset_id, 'main', self.env['gr.rental.order.line']))
        for line in self.item_line_ids.filtered('equipment_asset_id'):
            if 'is_primary_asset_line' in line._fields and line.is_primary_asset_line:
                continue
            targets.append((line.equipment_asset_id, 'accessory', line))
        return targets

    def _sync_asset_rental_history_lines(self):
        RentalHistory = self.env['rental.asset.rental.history']
        for order in self:
            RentalHistory.sync_from_order(order)

    def _history_record_for_targets(self, event_type, title, description=False,
                                    event_datetime=False):
        History = self.env['rental.asset.history']
        for order in self:
            for kind, target in order._history_targets():
                event_title = order._history_event_title(
                    event_type, target, fallback=title)
                History.record_event(
                    target,
                    event_type=event_type,
                    name=event_title,
                    description=description or order.display_name,
                    old_state=False,
                    new_state=order.state,
                    partner=order.partner_id,
                    location=order.site_id,
                    location_label=order.site_id.display_name if order.site_id else False,
                    event_datetime=event_datetime,
                    technical_key='gr.rental.order:%s:%s:%s:%s' % (
                        order.id, event_type, kind, target.id),
                    source=order,
                )

    def _history_event_title(self, event_type, target, fallback=False):
        customer = self.partner_id.display_name or history_text(
            self.env, _('the customer'))
        site = self.site_id.display_name or history_text(
            self.env, _('the site'))
        target_name = target.display_name
        titles = {
            'rental_order_created': history_text(
                self.env,
                _('Rental order %(order)s created for %(target)s'),
                order=self.display_name, target=target_name),
            'rental_confirmed': history_text(
                self.env,
                _('Rental order %(order)s confirmed'),
                order=self.display_name),
            'asset_reserved': history_text(
                self.env,
                _('%(target)s reserved for %(customer)s'),
                target=target_name, customer=customer),
            'delivery': history_text(
                self.env,
                _('%(target)s delivered to %(site)s'),
                target=target_name, site=site),
            'installed': history_text(
                self.env,
                _('%(target)s installed at %(site)s'),
                target=target_name, site=site),
            'rental_started': history_text(
                self.env,
                _('Rental period started for %(target)s'),
                target=target_name),
            'off_hire_requested': history_text(
                self.env,
                _('Return requested for %(target)s'),
                target=target_name),
            'return': history_text(
                self.env,
                _('%(target)s returned from %(customer)s'),
                target=target_name, customer=customer),
            'inspection_started': history_text(
                self.env,
                _('Return inspection started for %(target)s'),
                target=target_name),
            'rental_closed': history_text(
                self.env,
                _('Rental order %(order)s closed'),
                order=self.display_name),
            'reservation_cancelled': history_text(
                self.env,
                _('Rental order %(order)s cancelled'),
                order=self.display_name),
        }
        return titles.get(event_type, fallback or self.display_name)

    def _history_sync_current_from_order(self, clear=False):
        for order in self:
            for kind, target in order._history_targets():
                if kind == 'asset':
                    vals = {
                        'current_rental_order_id': False if clear else order.id,
                        'current_contract_id': False if clear else order.contract_id.id,
                        'current_site_id': False if clear else order.site_id.id,
                        'expected_return_datetime': False if clear else order.planned_return_datetime,
                    }
                    if clear:
                        vals.update({
                            'current_customer_id': False,
                            'current_site_ref': False,
                            'current_contract_ref': False,
                            'current_rental_order_ref': False,
                        })
                    elif order.state in ('installed', 'on_rent', 'off_hire_requested'):
                        vals.update({
                            'current_customer_id': order.partner_id.id,
                            'current_site_ref': order.site_id.display_name if order.site_id else False,
                            'current_contract_ref': order.contract_id.name if order.contract_id else False,
                            'current_rental_order_ref': order.name,
                        })
                    target.with_context(gr_skip_history_asset_write=True).write(vals)
                else:
                    vals = {
                        'current_partner_id': False if clear else order.partner_id.id,
                        'current_rental_order_id': False if clear else order.id,
                        'current_contract_id': False if clear else order.contract_id.id,
                        'current_site_id': False if clear else order.site_id.id,
                        'expected_return_datetime': False if clear else order.planned_return_datetime,
                    }
                    target.with_context(gr_skip_history_item_write=True).write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._sync_asset_rental_history_lines()
        orders._history_record_for_targets(
            'rental_order_created',
            _("Rental order created"),
            _("Rental order was created."))
        return orders

    def write(self, vals):
        tracked_return = 'planned_return_datetime' in vals
        old_returns = {}
        if tracked_return and not self.env.context.get('gr_skip_history_order_write'):
            for order in self:
                old_returns[order.id] = order.planned_return_datetime
        res = super().write(vals)
        self._sync_asset_rental_history_lines()
        if tracked_return and old_returns:
            History = self.env['rental.asset.history']
            for order in self:
                old_dt = old_returns.get(order.id)
                new_dt = order.planned_return_datetime
                if old_dt == new_dt:
                    continue
                if order.state in ('reserved', 'dispatched', 'installed',
                                   'on_rent', 'off_hire_requested'):
                    order._history_sync_current_from_order(clear=False)
                for kind, target in order._history_targets():
                    History.record_event(
                        target,
                        event_type='rental_extended',
                        name=history_text(
                            self.env,
                            _('Expected return changed for %(target)s'),
                            target=target.display_name),
                        description=_(
                            "Expected return changed from %(old)s to %(new)s.",
                            old=old_dt or _('Not set'),
                            new=new_dt or _('Not set')),
                        old_state=old_dt and fields.Datetime.to_string(old_dt),
                        new_state=new_dt and fields.Datetime.to_string(new_dt),
                        partner=order.partner_id,
                        location=order.site_id,
                        location_label=(
                            order.site_id.display_name if order.site_id else False),
                        event_datetime=fields.Datetime.now(),
                        technical_key='gr.rental.order:%s:rental_extended:%s:%s:%s:%s' % (
                            order.id, kind, target.id, old_dt or 'none',
                            new_dt or 'none'),
                        source=order,
                    )
        return res

    def action_confirm(self):
        res = super().action_confirm()
        self._sync_asset_rental_history_lines()
        self._history_record_for_targets(
            'rental_confirmed',
            _("Rental confirmed"),
            _("Rental order was confirmed."))
        return res

    def action_reserve(self):
        res = super().action_reserve()
        self._sync_asset_rental_history_lines()
        current_orders = self.filtered(
            lambda order: order._availability_should_touch_current_status())
        current_orders._history_sync_current_from_order(clear=False)
        self._history_record_for_targets(
            'asset_reserved',
            _("Asset reserved"),
            _("Asset was reserved for this rental order."))
        return res

    def action_dispatch(self):
        res = super().action_dispatch()
        self._sync_asset_rental_history_lines()
        self._history_sync_current_from_order(clear=False)
        self._history_record_for_targets(
            'delivery',
            _("Delivered to customer"),
            _("Asset was dispatched for delivery to the customer."),
            event_datetime=fields.Datetime.now())
        return res

    def action_install(self):
        res = super().action_install()
        self._sync_asset_rental_history_lines()
        self._history_sync_current_from_order(clear=False)
        self._history_record_for_targets(
            'installed',
            _("Installed at site"),
            _("Asset was installed at the customer site."),
            event_datetime=fields.Datetime.now())
        return res

    def action_start_rental(self):
        res = super().action_start_rental()
        self._sync_asset_rental_history_lines()
        self._history_sync_current_from_order(clear=False)
        self._history_record_for_targets(
            'rental_started',
            _("Rental started"),
            _("Rental period started."))
        return res

    def action_request_off_hire(self):
        res = super().action_request_off_hire()
        self._sync_asset_rental_history_lines()
        self._history_record_for_targets(
            'off_hire_requested',
            _("Off-hire requested"),
            _("Customer requested off-hire / return."))
        return res

    def action_return(self):
        res = super().action_return()
        self._sync_asset_rental_history_lines()
        self._history_record_for_targets(
            'return',
            _("Returned from customer"),
            _("Asset was returned from the customer."),
            event_datetime=fields.Datetime.now())
        return res

    def action_start_inspection(self):
        res = super().action_start_inspection()
        self._sync_asset_rental_history_lines()
        self._history_record_for_targets(
            'inspection_started',
            _("Return inspection started"),
            _("Returned asset entered inspection."))
        return res

    def action_close(self):
        res = super().action_close()
        self._sync_asset_rental_history_lines()
        self._history_sync_current_from_order(clear=True)
        self._history_record_for_targets(
            'rental_closed',
            _("Rental closed"),
            _("Rental order was closed and the asset was released."))
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self._sync_asset_rental_history_lines()
        self._history_sync_current_from_order(clear=True)
        self._history_record_for_targets(
            'reservation_cancelled',
            _("Rental cancelled"),
            _("Rental order was cancelled and any reservation was released."))
        return res
