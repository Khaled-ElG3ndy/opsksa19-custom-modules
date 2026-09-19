# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo import fields


@tagged('post_install', '-at_install')
class TestQuantityIncreaseOrder(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Arabic is asserted below and now comes from i18n/ar.po. Activating the
        # language does not backfill catalogues for modules installed before it,
        # so the module is retranslated explicitly.
        cls.env['res.lang']._activate_lang('ar_001')
        cls.env['ir.module.module'].search([
            ('name', '=', 'strx_cabin_allocation'), ('state', '=', 'installed'),
        ])._update_translations(['ar_001'])
        cls.partner = cls.env['res.partner'].create({
            'name': 'Quantity Increase Test Co.'})
        cls.cabin = cls.env['product.product'].create({
            'name': 'Cabin 5x3 IncreaseTest',
            'default_code': 'INC-CAB-5X3',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'serial',
            'strx_is_cabin': True,
            'strx_asset_kind': 'cabin',
            'strx_cabin_size': '5x3',
            'strx_cabin_grade': 'std',
        })
        cls.free_service = cls.env['product.product'].create({
            'name': 'Bathroom Tank Included Service',
            'default_code': 'FREE-TANK',
            'type': 'service',
            'sale_ok': True,
            'list_price': 0.0,
            'strx_is_free_additional_service': True,
        })
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'order_line': [(0, 0, {
                'product_id': cls.cabin.id,
                'product_uom_qty': 2,
                'price_unit': 1000.0,
            })],
        })
        cls.order.action_confirm()

    def test_confirmed_order_qty_increase_is_blocked(self):
        line = self.order.order_line.filtered(
            lambda l: l.product_id == self.cabin)[:1]

        with self.assertRaisesRegex(
                UserError, 'Create a quantity increase order instead'):
            line.write({'product_uom_qty': 3})

        with self.assertRaisesRegex(
                UserError, 'Create a quantity increase order instead'):
            self.env['sale.order.line'].create({
                'order_id': self.order.id,
                'product_id': self.cabin.id,
                'price_unit': 1000.0,
            })

    def test_quantity_increase_wizard_creates_new_order(self):
        wizard = self.env['strx.sale.quantity.increase.wizard'].with_context(
            default_original_order_id=self.order.id).create({})
        self.assertEqual(wizard.original_order_id, self.order)
        wizard.line_ids[0].write({'increase_qty': 2})

        action = wizard.action_create_increase_order()
        new_order = self.env['sale.order'].browse(action['res_id'])

        self.assertEqual(new_order.state, 'draft')
        self.assertEqual(new_order.strx_origin_order_id, self.order)
        self.assertEqual(new_order.partner_id, self.order.partner_id)
        self.assertEqual(len(new_order.order_line), 1)
        self.assertEqual(new_order.order_line.product_id, self.cabin)
        self.assertEqual(new_order.order_line.product_uom_qty, 2)
        self.assertIn(new_order, self.order.strx_addition_order_ids)

    def test_free_additional_service_defaults_zero_but_price_is_editable(self):
        line = self.env['sale.order.line'].create({
            'order_id': self.order.id,
            'product_id': self.free_service.id,
            'product_uom_qty': 1,
        })

        self.assertEqual(line.price_unit, 0.0)
        self.assertFalse(line.product_id.strx_is_cabin)
        self.assertFalse(line.strx_allocation_ids)
        self.assertEqual(self.order.amount_untaxed, 2000.0)

        line.write({'price_unit': 500.0})
        self.assertEqual(line.price_unit, 500.0)
        self.assertEqual(self.order.amount_untaxed, 2500.0)

    # Odoo 19 removed sale.order.option / Optional Products from sale_management,
    # so the guard this test covered no longer has a model to guard.

    def test_rental_days_sync_to_allocation_and_create_return_alert(self):
        start = fields.Date.context_today(self.env['sale.order.line'])
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.cabin.id,
                'product_uom_qty': 1,
                'strx_rental_start_date': start,
                'strx_rental_days': 5,
                'price_unit': 1000.0,
            })],
        })
        line = order.order_line.filtered(lambda l: l.product_id == self.cabin)[:1]
        self.assertEqual(line.strx_expected_return_date, start + timedelta(days=5))
        order.action_confirm()
        lot = self.env['stock.lot'].create({
            'name': 'RENTAL-DAYS-ALERT',
            'product_id': self.cabin.id,
            'company_id': self.env.company.id,
        })
        alloc = self.env['strx.cabin.allocation'].create({
            'order_line_id': line.id,
            'lot_id': lot.id,
        })
        self.assertEqual(alloc.strx_date_out, line.strx_rental_start_date)
        self.assertEqual(alloc.strx_expected_return_date,
                         line.strx_expected_return_date)

        line.write({'strx_rental_days': 6})
        self.assertEqual(line.strx_expected_return_date, start + timedelta(days=6))
        self.assertEqual(alloc.strx_expected_return_date, start + timedelta(days=6))

        alloc.write({'state': 'on_rent'})
        lot._strx_set_readiness('on_rent', reason='Return alert test')
        alert_date = alloc._strx_business_days_before_return(
            alloc.strx_expected_return_date)
        alloc._strx_schedule_return_alerts(today=start)
        self.assertFalse(self.env['mail.activity'].search([
            ('res_model', '=', 'strx.cabin.allocation'),
            ('res_id', '=', alloc.id),
            ('summary', '=', 'Prepare return shipment'),
        ]))

        alloc._strx_schedule_return_alerts(today=alert_date)

        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'strx.cabin.allocation'),
            ('res_id', '=', alloc.id),
            '|',
            ('summary', 'ilike', 'two business days'),
            ('summary', 'ilike', 'يومان عمل'),
        ])
        self.assertTrue(activities)
        self.assertEqual(activities[:1].date_deadline, alert_date)

    def test_return_alert_date_uses_two_business_days_excluding_weekend(self):
        Allocation = self.env['strx.cabin.allocation']
        cases = {
            # Python calendar: 2026-08-02 is Sunday.
            date(2026, 8, 2): date(2026, 7, 30),
            date(2026, 8, 3): date(2026, 8, 1),
            date(2026, 8, 4): date(2026, 8, 2),
            date(2026, 8, 1): date(2026, 7, 29),
        }
        for return_date, expected_alert_date in cases.items():
            self.assertEqual(
                Allocation._strx_business_days_before_return(return_date),
                expected_alert_date,
                "Wrong 2-business-day alert date for %s" % return_date,
            )

    def test_return_alerts_follow_three_phases_without_duplicates(self):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.cabin.id,
                'product_uom_qty': 1,
                'price_unit': 1000.0,
            })],
        })
        order.action_confirm()
        lot = self.env['stock.lot'].create({
            'name': 'RETURN-THREE-PHASES',
            'product_id': self.cabin.id,
            'company_id': self.env.company.id,
        })
        alloc = self.env['strx.cabin.allocation'].with_context(
            strx_skip_return_alerts=True).create({
                'order_line_id': order.order_line[0].id,
                'lot_id': lot.id,
                'strx_expected_return_date': date(2026, 8, 4),
                'state': 'on_rent',
            })
        lot._strx_set_readiness('on_rent', reason='Three-phase alert test')

        Activity = self.env['mail.activity']
        base_domain = [
            ('res_model', '=', 'strx.cabin.allocation'),
            ('res_id', '=', alloc.id),
        ]
        two_days_domain = base_domain + [
            '|',
            ('summary', 'ilike', 'two business days'),
            ('summary', 'ilike', 'يومان عمل'),
        ]
        today_domain = base_domain + [
            '|',
            ('summary', 'ilike', 'due today'),
            ('summary', 'ilike', 'موعد الإرجاع اليوم'),
        ]
        overdue_domain = base_domain + [
            '|',
            ('summary', 'ilike', 'overdue'),
            ('summary', 'ilike', 'الإرجاع متأخر'),
        ]

        alloc._strx_schedule_return_alerts(today=date(2026, 8, 2))
        two_days_count = Activity.search_count(two_days_domain)
        self.assertTrue(two_days_count)
        alloc._strx_schedule_return_alerts(today=date(2026, 8, 2))
        self.assertEqual(Activity.search_count(two_days_domain), two_days_count)

        alloc._strx_schedule_return_alerts(today=date(2026, 8, 4))
        self.assertTrue(Activity.search_count(today_domain))

        alloc._strx_schedule_return_alerts(today=date(2026, 8, 5))
        self.assertTrue(Activity.search_count(overdue_domain))

        alloc.write({'state': 'returned'})
        self.assertFalse(Activity.search([
            ('res_model', '=', 'strx.cabin.allocation'),
            ('res_id', '=', alloc.id),
            '|',
            ('summary', 'ilike', 'return'),
            ('summary', 'ilike', 'الإرجاع'),
        ]))

    def test_confirmed_cabin_product_change_wizard_notifies_logistics(self):
        new_cabin = self.env['product.product'].create({
            'name': 'Cabin 5x5 ProductChangeTest',
            'default_code': 'CHG-CAB-5X5',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'serial',
            'strx_is_cabin': True,
            'strx_asset_kind': 'cabin',
            'strx_cabin_size': '5x5',
            'strx_cabin_grade': 'std',
        })
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.cabin.id,
                'product_uom_qty': 1,
                'price_unit': 1000.0,
            })],
        })
        order.action_confirm()
        line = order.order_line.filtered(lambda l: l.product_id == self.cabin)[:1]
        lot = self.env['stock.lot'].create({
            'name': 'PRODUCT-CHANGE-OLD-SERIAL',
            'product_id': self.cabin.id,
            'company_id': self.env.company.id,
        })
        alloc = self.env['strx.cabin.allocation'].create({
            'order_line_id': line.id,
            'lot_id': lot.id,
        })
        alloc.action_allocate()

        with self.assertRaisesRegex(UserError, 'modify the product'):
            line.with_context(lang='en_US').write({'product_id': new_cabin.id})

        wizard = self.env['strx.sale.product.change.wizard'].with_context(
            default_original_order_id=order.id,
            lang='ar_001',
        ).create({'reason': 'Customer requested a larger size'})
        wizard.line_ids.filtered(lambda wl: wl.order_line_id == line)[:1].write({
            'proposed_product_id': new_cabin.id,
        })
        wizard.action_apply_product_change()

        self.assertEqual(line.product_id, new_cabin)
        self.assertEqual(alloc.product_id, new_cabin)
        self.assertFalse(alloc.lot_id)
        self.assertEqual(alloc.state, 'draft')
        self.assertEqual(lot.strx_readiness_state, 'available')
        self.assertTrue(self.env['mail.activity'].search([
            ('res_model', '=', 'sale.order'),
            ('res_id', '=', order.id),
            '|',
            ('summary', 'ilike', 'تم تغيير مواصفة الكابينة'),
            ('summary', 'ilike', 'cabin specification changed'),
        ]))
