# -*- coding: utf-8 -*-
import base64

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError, ValidationError


@tagged('post_install', '-at_install')
class TestShipping(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Arabic now comes from i18n/ar.po. Activating the language is not
        # enough on its own: catalogues are not backfilled for modules that
        # were installed before it, so the module is retranslated explicitly.
        cls.env['res.lang']._activate_lang('ar_001')
        cls.env['ir.module.module'].search([
            ('name', '=', 'strx_cabin_shipping'), ('state', '=', 'installed'),
        ])._update_translations(['ar_001'])
        cls.partner = cls.env['res.partner'].create({'name': 'Ship Customer'})
        cls.product = cls.env['product.product'].create({
            'name': 'Cabin 5x3', 'default_code': 'SHIP-5X3', 'type': 'consu',
            'is_storable': True, 'tracking': 'serial', 'strx_is_cabin': True,
            'strx_cabin_size': '5x3', 'strx_cabin_grade': 'std'})
        cls.lot = cls.env['stock.lot'].create({
            'name': 'SHIP-5X3-1', 'product_id': cls.product.id,
            'company_id': cls.env.company.id})
        cls.we_transport = cls.env['strx.cabin.broker'].create({
            'name': 'We Transport', 'is_internal': True,
            'company_registration': '4030xxxxxx',
            'contact_name': 'Ops Desk',
            'contact_phone': '+966500000000',
            'default_rate': 800.0})
        cls.so = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'order_line': [(0, 0, {'product_id': cls.product.id, 'product_uom_qty': 1})]})

    def _serial(self, name):
        return self.env['stock.lot'].create({
            'name': name, 'product_id': self.product.id,
            'company_id': self.env.company.id})

    def _rental(self):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
            })],
        })
        so.action_confirm()
        return so

    def _allocate(self, so, lot):
        alloc = self.env['strx.cabin.allocation'].create({
            'order_line_id': so.order_line[0].id,
            'lot_id': lot.id,
        })
        alloc.action_allocate()
        return alloc

    def _receipt_attachment_command(self, name='delivery-receipt.pdf'):
        attachment = self.env['ir.attachment'].create({
            'name': name,
            'mimetype': 'application/pdf',
            'datas': base64.b64encode(b'Test delivery receipt'),
        })
        return [(6, 0, attachment.ids)]

    def _waybill_details(self, receipt_exception=True, receipt_attachment=True):
        details = {
            'driver_name': 'Ahmed',
            'driver_id_number': 'ID-123456',
            'driver_phone': '+966511111111',
            'vehicle_model': 'Flatbed Truck',
            'vehicle_plate': 'JED-1234',
            'route_origin': 'Jeddah Yard',
            'route_destination': 'Customer Site',
            'scheduled_date': '2026-07-29 10:00:00',
            'agreed_cost': 800.0,
        }
        if receipt_attachment:
            details['customer_receipt_attachment_ids'] = (
                self._receipt_attachment_command()
            )
        if receipt_exception:
            details.update({
                'customer_receipt_exception': True,
                'customer_receipt_exception_reason': 'Customer representative unavailable for signature.',
            })
        return details

    def _delivered_waybill(self, serial_name, cost=800.0):
        so = self._rental()
        lot = self._serial(serial_name)
        self._allocate(so, lot)
        details = dict(self._waybill_details(), agreed_cost=cost)
        wb = self.env['strx.cabin.shipping.order'].create({
            'broker_id': self.we_transport.id,
            'order_id': so.id,
            **details,
        })
        wb.action_issue()
        wb.action_load()
        wb.action_ship()
        wb.action_deliver()
        return wb

    def test_01_status_flow_and_sequence(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-FLOW')
        alloc = self._allocate(so, lot)
        wb = self.env['strx.cabin.shipping.order'].create({
            'broker_id': self.we_transport.id, 'order_id': so.id,
            'lot_ids': [(6, 0, lot.ids)],
            **self._waybill_details()})
        self.assertTrue(wb.name.startswith('WB/'))
        self.assertTrue(wb.is_internal)                 # flagged inter-company
        self.assertEqual(wb.lot_ids, lot)               # exact serial linked
        wb.action_issue();   self.assertEqual(wb.state, 'issued')
        wb.action_load()
        self.assertEqual(wb.state, 'loaded')
        self.assertTrue(wb.loaded_date)
        wb.action_ship()
        self.assertEqual(wb.state, 'shipped')
        self.assertEqual(alloc.state, 'dispatched')
        self.assertEqual(lot.strx_readiness_state, 'dispatched')
        wb.action_deliver()
        self.assertEqual(wb.state, 'delivered')
        self.assertTrue(wb.delivered_date)
        self.assertEqual(alloc.state, 'on_rent')
        self.assertEqual(lot.strx_readiness_state, 'on_rent')

    def test_01b_multi_serial_allocation_moves_as_one_group(self):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 2,
            })],
        })
        so.action_confirm()
        lots = self._serial('SHIP-MULTI-A') | self._serial('SHIP-MULTI-B')
        allocation = self.env['strx.cabin.allocation'].create({
            'order_line_id': so.order_line[0].id,
            'lot_ids': [(6, 0, lots.ids)],
        })
        allocation.action_allocate()

        waybill = self.env['strx.cabin.shipping.order'].create({
            'broker_id': self.we_transport.id,
            'order_id': so.id,
            **self._waybill_details(),
        })
        self.assertEqual(waybill.lot_ids, lots)
        waybill.action_issue()
        waybill.action_load()
        waybill.action_ship()
        self.assertEqual(
            set(lots.mapped('strx_readiness_state')), {'dispatched'})
        waybill.action_deliver()
        self.assertEqual(allocation.state, 'on_rent')
        self.assertEqual(set(lots.mapped('strx_readiness_state')), {'on_rent'})
        for lot in lots:
            lot.action_strx_open_cabin_history()
            events = self.env['strx.cabin.history.event'].search([
                ('lot_id', '=', lot.id),
                ('create_uid', '=', self.env.uid),
            ])
            self.assertIn('allocation', events.mapped('event_type'))
            self.assertIn('readiness', events.mapped('event_type'))

    def test_02_cost_rolls_up_to_rental_and_excludes_cancelled(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-COST')
        self._allocate(so, lot)
        SO = self.env['strx.cabin.shipping.order']
        SO.create({'broker_id': self.we_transport.id, 'order_id': so.id,
                   'agreed_cost': 800.0})
        cancelled = SO.create({'broker_id': self.we_transport.id, 'order_id': so.id,
                               'agreed_cost': 500.0})
        self.assertEqual(so.strx_shipping_count, 2)
        self.assertEqual(so.strx_shipping_cost, 1300.0)
        cancelled.action_cancel()
        self.assertEqual(so.strx_shipping_cost, 800.0)   # cancelled excluded

    def test_03_shipping_action_name_follows_user_language(self):
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module'].search([
            ('name', '=', 'strx_cabin_shipping'),
            ('state', '=', 'installed'),
        ])._update_translations(['ar_001'])

        self.assertEqual(
            self.so.with_context(
                lang='en_US').action_view_strx_shipping_orders()['name'],
            'Shipments')
        self.assertEqual(
            self.so.with_context(
                lang='ar_001').action_view_strx_shipping_orders()['name'],
            'الشحنات')

    def test_03b_allocation_smart_button_shows_only_its_shipments(self):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [
                (0, 0, {
                    'product_id': self.product.id,
                    'product_uom_qty': 1,
                }),
                (0, 0, {
                    'product_id': self.product.id,
                    'product_uom_qty': 1,
                }),
            ],
        })
        so.action_confirm()
        lot_a = self._serial('SHIP-SMART-A')
        lot_b = self._serial('SHIP-SMART-B')
        allocation_a = self._allocate(so, lot_a)
        allocation_b = self.env['strx.cabin.allocation'].create({
            'order_line_id': so.order_line[1].id,
            'lot_ids': [(6, 0, lot_b.ids)],
        })
        allocation_b.action_allocate()

        shipment = self.env['strx.cabin.shipping.order'].create({
            'broker_id': self.we_transport.id,
            'order_id': so.id,
            'lot_ids': [(6, 0, lot_a.ids)],
            **self._waybill_details(),
        })

        self.assertEqual(shipment.allocation_ids, allocation_a)
        self.assertEqual(allocation_a.strx_shipping_order_ids, shipment)
        self.assertEqual(allocation_a.strx_shipping_count, 1)
        self.assertFalse(allocation_b.strx_shipping_order_ids)
        self.assertEqual(allocation_b.strx_shipping_count, 0)

        action = allocation_a.action_view_shipping_orders()
        self.assertEqual(action['res_model'], 'strx.cabin.shipping.order')
        self.assertEqual(action['domain'], [('id', 'in', shipment.ids)])
        self.assertFalse(action['context']['create'])
        self.assertEqual(
            allocation_a.with_context(
                lang='ar_001').action_view_shipping_orders()['name'],
            'الشحنات')

    def test_04_return_waybill_receives_cabin_back(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-RETURN')
        alloc = self._allocate(so, lot)
        alloc.write({'state': 'on_rent'})
        lot._strx_set_readiness('on_rent', reason='Delivered fixture')

        wb = self.env['strx.cabin.shipping.order'].create({
            'broker_id': self.we_transport.id,
            'order_id': so.id,
            'movement_type': 'return',
            'lot_ids': [(6, 0, lot.ids)],
            **self._waybill_details(),
        })
        wb.action_issue()
        wb.action_load()
        wb.action_ship()
        self.assertEqual(lot.strx_readiness_state, 'return_due')
        wb.action_deliver()
        self.assertEqual(alloc.state, 'returned')
        self.assertTrue(alloc.strx_actual_return_date)
        self.assertEqual(lot.strx_readiness_state, 'returned')
        self.assertFalse(lot.strx_selectable)

        open_action = alloc.action_open_return_assessment()
        self.assertEqual(
            open_action['res_model'], 'strx.cabin.return.assessment.wizard')
        wizard = self.env[
            'strx.cabin.return.assessment.wizard'
        ].with_context(default_allocation_id=alloc.id).create({})
        self.assertEqual(wizard.line_ids.target_state, 'in_inspection')
        wizard.line_ids.target_state = 'available'
        action = wizard.action_confirm_assessment()

        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(alloc.state, 'available')
        self.assertEqual(lot.strx_readiness_state, 'available')
        self.assertTrue(lot.strx_selectable)
        readiness_event = self.env['strx.cabin.readiness.log'].search([
            ('lot_id', '=', lot.id),
        ], order='id desc', limit=1)
        self.assertEqual(readiness_event.old_state, 'returned')
        self.assertEqual(readiness_event.new_state, 'available')
        self.assertIn(alloc.name, readiness_event.reason)

    def test_05_waybill_rejects_serial_not_allocated_to_order(self):
        so_a = self._rental()
        so_b = self._rental()
        lot_a = self._serial('SHIP-5X3-ORDER-A')
        lot_b = self._serial('SHIP-5X3-ORDER-B')
        self._allocate(so_a, lot_a)
        self._allocate(so_b, lot_b)
        with self.assertRaises(UserError):
            self.env['strx.cabin.shipping.order'].create({
                'broker_id': self.we_transport.id,
                'order_id': so_a.id,
                'lot_ids': [(6, 0, lot_b.ids)],
            })

    def test_06_order_without_allocation_cannot_be_selected_or_shipped(self):
        so = self._rental()
        draft_wb = self.env['strx.cabin.shipping.order'].new({
            'broker_id': self.we_transport.id,
            'movement_type': 'delivery',
        })
        draft_wb._compute_allowed_orders_and_lots()
        self.assertNotIn(so, draft_wb.allowed_order_ids)
        with self.assertRaises(UserError):
            self.env['strx.cabin.shipping.order'].create({
                'broker_id': self.we_transport.id,
                'order_id': so.id,
            })

    def test_07_draft_allocation_cannot_be_selected_or_shipped(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-DRAFT-ALLOC')
        self.env['strx.cabin.allocation'].create({
            'order_line_id': so.order_line[0].id,
            'lot_id': lot.id,
        })
        draft_wb = self.env['strx.cabin.shipping.order'].new({
            'broker_id': self.we_transport.id,
            'movement_type': 'delivery',
        })
        draft_wb._compute_allowed_orders_and_lots()
        self.assertNotIn(so, draft_wb.allowed_order_ids)
        with self.assertRaises(UserError):
            self.env['strx.cabin.shipping.order'].create({
                'broker_id': self.we_transport.id,
                'order_id': so.id,
            })

    def test_08_allocated_order_autofills_serial_and_empty_issue_is_blocked(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-AUTOFILL')
        self._allocate(so, lot)
        wb = self.env['strx.cabin.shipping.order'].create({
            'broker_id': self.we_transport.id,
            'order_id': so.id,
            **self._waybill_details(),
        })
        self.assertEqual(wb.lot_ids, lot)
        wb.write({'lot_ids': [(5, 0, 0)]})
        self.assertFalse(wb.lot_ids)
        with self.assertRaises(UserError):
            wb.action_issue()

    def test_08b_allocated_allocation_opens_delivery_shipment_action(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-SEND-ACTION')
        alloc = self._allocate(so, lot)

        action = alloc.action_create_delivery_shipment()

        self.assertEqual(action['res_model'], 'strx.cabin.shipping.order')
        self.assertEqual(action['context']['default_order_id'], so.id)
        self.assertEqual(action['context']['default_movement_type'], 'delivery')
        self.assertEqual(action['context']['default_lot_ids'], [(6, 0, lot.ids)])

        alloc.write({'state': 'on_rent'})
        with self.assertRaisesRegex(UserError, 'allocated cabins'):
            alloc.action_create_delivery_shipment()

    def test_08c_on_rent_allocation_opens_return_shipment_action(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-RETURN-ACTION')
        alloc = self._allocate(so, lot)

        with self.assertRaisesRegex(UserError, 'on-rent cabins'):
            alloc.action_create_return_shipment()

        alloc.write({
            'state': 'on_rent',
            'strx_expected_return_date': fields.Date.context_today(alloc),
        })
        lot._strx_set_readiness('on_rent', reason='On-rent fixture')

        action = alloc.action_create_return_shipment()

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['next']['type'], 'ir.actions.client')
        self.assertEqual(action['params']['next']['tag'], 'reload')
        self.assertEqual(alloc.state, 'returned')
        self.assertTrue(alloc.strx_actual_return_date)
        self.assertEqual(lot.strx_readiness_state, 'returned')
        shipment = self.env['strx.cabin.shipping.order'].search([
            ('order_id', '=', so.id),
            ('movement_type', '=', 'return'),
            ('lot_ids', 'in', lot.id),
        ], limit=1)
        self.assertTrue(shipment)
        self.assertEqual(shipment.state, 'delivered')
        self.assertEqual(shipment.lot_ids, lot)
        self.assertEqual(shipment.agreed_cost, 0.0)
        self.assertEqual(
            alloc.with_context(lang='ar_001').strx_return_timing_label,
            False)

    def test_09_return_only_allows_on_rent_or_return_due_units(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-RETURN-READY')
        alloc = self._allocate(so, lot)
        with self.assertRaises(UserError):
            self.env['strx.cabin.shipping.order'].create({
                'broker_id': self.we_transport.id,
                'order_id': so.id,
                'movement_type': 'return',
            })

        alloc.write({'state': 'on_rent'})
        lot._strx_set_readiness('on_rent', reason='Return-ready fixture')
        wb = self.env['strx.cabin.shipping.order'].create({
            'broker_id': self.we_transport.id,
            'order_id': so.id,
            'movement_type': 'return',
            **self._waybill_details(),
        })
        self.assertEqual(wb.lot_ids, lot)
        wb.action_issue()
        wb.action_load()
        wb.action_ship()
        self.assertEqual(lot.strx_readiness_state, 'return_due')
        wb.action_deliver()
        self.assertEqual(alloc.state, 'returned')
        self.assertEqual(lot.strx_readiness_state, 'returned')

    def test_11_waybill_cannot_be_issued_without_complete_logistics_details(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-MISSING-DETAILS')
        self._allocate(so, lot)
        wb = self.env['strx.cabin.shipping.order'].create({
            'broker_id': self.we_transport.id,
            'order_id': so.id,
        })

        with self.assertRaisesRegex(UserError, 'Shipment details are incomplete'):
            wb.action_issue()

        wb.write(self._waybill_details())
        wb.action_issue()
        self.assertEqual(wb.state, 'issued')

    def test_12_broker_master_data_is_required_before_issue(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-BROKER-MISSING')
        self._allocate(so, lot)
        broker = self.env['strx.cabin.broker'].create({'name': 'No Contact Carrier'})
        wb = self.env['strx.cabin.shipping.order'].create({
            'broker_id': broker.id,
            'order_id': so.id,
            **self._waybill_details(),
        })

        with self.assertRaisesRegex(UserError, 'Broker details'):
            wb.action_issue()

    def test_13_waybill_missing_details_message_follows_arabic_language(self):
        self.env['res.lang']._activate_lang('ar_001')
        so = self._rental()
        lot = self._serial('SHIP-5X3-AR-MESSAGE')
        self._allocate(so, lot)
        wb = self.env['strx.cabin.shipping.order'].with_context(lang='ar_001').create({
            'broker_id': self.we_transport.id,
            'order_id': so.id,
        })

        with self.assertRaises(UserError) as err:
            wb.with_context(lang='ar_001').action_issue()
        message = str(err.exception)
        self.assertIn('بيانات الشحنة غير مكتملة', message)
        self.assertIn('السائق والمركبة', message)
        self.assertIn('اسم السائق', message)
        self.assertIn('المسار والتكلفة', message)
        self.assertNotIn('Driver Phone', message)

    def test_14_site_transfer_moves_on_rent_cabin_without_returning_to_yard(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-SITE-XFER')
        alloc = self._allocate(so, lot)
        alloc.write({'state': 'on_rent'})
        lot._strx_set_readiness('on_rent', reason='On-rent fixture')

        draft_wb = self.env['strx.cabin.shipping.order'].new({
            'broker_id': self.we_transport.id,
            'movement_type': 'site_transfer',
        })
        draft_wb._compute_allowed_orders_and_lots()
        self.assertIn(so.id, draft_wb.allowed_order_ids._origin.ids)

        details = self._waybill_details()
        details.update({
            'route_origin': 'Customer Site A',
            'route_destination': 'Customer Site B',
        })
        wb = self.env['strx.cabin.shipping.order'].create({
            'broker_id': self.we_transport.id,
            'order_id': so.id,
            'movement_type': 'site_transfer',
            **details,
        })
        self.assertEqual(wb.lot_ids, lot)
        wb.action_issue()
        wb.action_load()
        wb.action_ship()
        self.assertEqual(alloc.state, 'on_rent')
        self.assertEqual(lot.strx_readiness_state, 'on_rent')
        wb.action_deliver()
        self.assertEqual(wb.state, 'delivered')
        self.assertEqual(alloc.state, 'on_rent')
        self.assertEqual(lot.strx_readiness_state, 'on_rent')

    def test_15_site_transfer_rejects_allocated_not_on_rent_cabin(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-SITE-XFER-BLOCKED')
        self._allocate(so, lot)

        draft_wb = self.env['strx.cabin.shipping.order'].new({
            'broker_id': self.we_transport.id,
            'movement_type': 'site_transfer',
        })
        draft_wb._compute_allowed_orders_and_lots()
        self.assertNotIn(so.id, draft_wb.allowed_order_ids._origin.ids)

        with self.assertRaises(UserError):
            self.env['strx.cabin.shipping.order'].create({
                'broker_id': self.we_transport.id,
                'order_id': so.id,
                'movement_type': 'site_transfer',
                **self._waybill_details(),
            })

    def test_10_damaged_allocated_unit_is_hidden_and_cannot_ship(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-DAMAGED')
        self._allocate(so, lot)
        lot.write({'strx_condition': 'damaged'})

        draft_wb = self.env['strx.cabin.shipping.order'].new({
            'broker_id': self.we_transport.id,
            'movement_type': 'delivery',
        })
        draft_wb._compute_allowed_orders_and_lots()
        self.assertNotIn(so, draft_wb.allowed_order_ids)

        with self.assertRaises(UserError):
            self.env['strx.cabin.shipping.order'].create({
                'broker_id': self.we_transport.id,
                'order_id': so.id,
            })
        with self.assertRaises(UserError):
            self.env['strx.cabin.shipping.order'].create({
                'broker_id': self.we_transport.id,
                'order_id': so.id,
                'lot_ids': [(6, 0, lot.ids)],
            })

    def test_16_broker_payment_order_issues_for_delivered_waybill(self):
        wb = self._delivered_waybill('SHIP-5X3-PAY-ONE')
        action = wb.action_create_broker_payment()
        payment = self.env['strx.cabin.broker.payment'].browse(action['res_id'])
        self.assertTrue(payment.name.startswith('BPO/'))
        self.assertEqual(payment.payment_batch, 'single')
        self.assertEqual(payment.broker_id, self.we_transport)
        self.assertEqual(payment.shipping_order_ids, wb)
        self.assertEqual(payment.amount_total, wb.agreed_cost)
        payment.action_issue()
        self.assertEqual(payment.state, 'issued')
        self.assertEqual(wb.broker_payment_state, 'issued')
        payment.action_approve()
        payment.action_mark_paid()
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(wb.broker_payment_state, 'paid')

    def test_17_broker_payment_rejects_undelivered_or_duplicate_waybill(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-PAY-NOT-DELIVERED')
        self._allocate(so, lot)
        wb = self.env['strx.cabin.shipping.order'].create({
            'broker_id': self.we_transport.id,
            'order_id': so.id,
            **self._waybill_details(),
        })
        with self.assertRaises(UserError):
            wb.action_create_broker_payment()

        delivered = self._delivered_waybill('SHIP-5X3-PAY-DUP')
        first = self.env['strx.cabin.broker.payment'].create({
            'broker_id': self.we_transport.id,
            'shipping_order_ids': [(6, 0, delivered.ids)],
        })
        self.assertEqual(first.amount_total, delivered.agreed_cost)
        with self.assertRaises(ValidationError):
            self.env['strx.cabin.broker.payment'].create({
                'broker_id': self.we_transport.id,
                'shipping_order_ids': [(6, 0, delivered.ids)],
            })

    def test_18_broker_batch_payment_fills_only_unpaid_delivered_waybills(self):
        paid = self._delivered_waybill('SHIP-5X3-PAY-BATCH-PAID')
        unpaid = self._delivered_waybill('SHIP-5X3-PAY-BATCH-UNPAID')
        self.env['strx.cabin.broker.payment'].create({
            'broker_id': self.we_transport.id,
            'shipping_order_ids': [(6, 0, paid.ids)],
        })
        batch = self.env['strx.cabin.broker.payment'].create({
            'broker_id': self.we_transport.id,
            'payment_batch': 'broker_batch',
        })
        batch.action_fill_payable_waybills()
        self.assertIn(unpaid, batch.shipping_order_ids)
        self.assertNotIn(paid, batch.shipping_order_ids)

    def test_19_delivery_requires_customer_receipt_or_exception(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-RECEIPT-BLOCK')
        self._allocate(so, lot)
        wb = self.env['strx.cabin.shipping.order'].create({
            'broker_id': self.we_transport.id,
            'order_id': so.id,
            **self._waybill_details(
                receipt_exception=False,
                receipt_attachment=False,
            ),
        })

        wb.action_issue()
        wb.action_load()
        wb.action_ship()
        with self.assertRaisesRegex(UserError, 'customer receipt proof'):
            wb.action_deliver()

        # A signature alone is insufficient: a receipt attachment is mandatory.
        wb.customer_receipt_signature = (
            b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lE'
            b'QVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
        )
        with self.assertRaisesRegex(UserError, 'receipt attachment'):
            wb.action_deliver()
        with self.assertRaisesRegex(UserError, 'receipt attachment'):
            wb.write({'state': 'delivered'})

        wb.write({
            'customer_receipt_attachment_ids': self._receipt_attachment_command(),
        })
        wb.action_deliver()
        self.assertEqual(wb.state, 'delivered')

    def test_20_sales_order_receipt_exception_allows_delivery(self):
        so = self._rental()
        lot = self._serial('SHIP-5X3-RECEIPT-SO')
        self._allocate(so, lot)
        so.write({
            'strx_customer_receipt_exception': True,
            'strx_customer_receipt_exception_reason': 'Signed receipt kept on customer file.',
            'strx_customer_receipt_attachment_ids': (
                self._receipt_attachment_command('sales-order-receipt.pdf')
            ),
        })
        wb = self.env['strx.cabin.shipping.order'].create({
            'broker_id': self.we_transport.id,
            'order_id': so.id,
            **self._waybill_details(
                receipt_exception=False,
                receipt_attachment=False,
            ),
        })

        wb.action_issue()
        wb.action_load()
        wb.action_ship()
        wb.action_deliver()
        self.assertEqual(wb.state, 'delivered')
