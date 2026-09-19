# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestInvoiceAllocationControl(TransactionCase):

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
            'name': 'Invoice Allocation Test Co.',
        })
        cls.cabin_a = cls._create_cabin('Invoice Cabin A', 'INV-CAB-A')
        cls.cabin_b = cls._create_cabin('Invoice Cabin B', 'INV-CAB-B')
        cls.service = cls.env['product.product'].create({
            'name': 'Invoice Test Service',
            'default_code': 'INV-SERVICE',
            'type': 'service',
            'sale_ok': True,
            'invoice_policy': 'order',
            'list_price': 100.0,
            # This suite asserts which serials land on which invoice line; taxes are
            # not part of it. The default company carries a fiscal-country/default-tax
            # mismatch that would raise before the assertions are ever reached.
            'taxes_id': [(5, 0, 0)],
        })

    @classmethod
    def _create_cabin(cls, name, code):
        return cls.env['product.product'].create({
            'name': name,
            'default_code': code,
            'type': 'consu',
            'is_storable': True,
            'tracking': 'serial',
            'sale_ok': True,
            'invoice_policy': 'order',
            'list_price': 1000.0,
            'strx_is_cabin': True,
            'strx_asset_kind': 'cabin',
            'strx_cabin_size': '5x3',
            'strx_cabin_grade': 'std',
            'taxes_id': [(5, 0, 0)],
        })

    def _lot(self, product, name):
        return self.env['stock.lot'].create({
            'name': name,
            'product_id': product.id,
            'company_id': self.env.company.id,
        })

    def _order(self, lines):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': quantity,
                'price_unit': product.list_price,
            }) for product, quantity in lines],
        })
        order.action_confirm()
        return order

    def _allocation(self, line, lots, allocate=False):
        allocation = self.env['strx.cabin.allocation'].create({
            'order_line_id': line.id,
            'lot_ids': [(6, 0, lots.ids)],
        })
        if allocate:
            allocation.action_allocate()
        return allocation

    def test_invoice_blocked_until_full_allocation_is_committed(self):
        order = self._order([(self.cabin_a, 2)])
        line = order.order_line.filtered(lambda item: item.product_id == self.cabin_a)
        lot_a = self._lot(self.cabin_a, 'INV-A-002')
        lot_b = self._lot(self.cabin_a, 'INV-A-001')

        with self.assertRaisesRegex(UserError, '0/2 serials allocated'):
            order._create_invoices()

        allocation = self._allocation(line, lot_a | lot_b)
        with self.assertRaisesRegex(UserError, '0/2 serials allocated'):
            order._create_invoices()

        allocation.action_allocate()
        invoice = order._create_invoices()
        invoice_line = invoice.invoice_line_ids.filtered(
            lambda item: item.product_id == self.cabin_a)
        self.assertEqual(invoice_line.strx_allocated_lot_ids, lot_a | lot_b)
        self.assertEqual(
            invoice_line.strx_allocated_serial_numbers,
            'INV-A-001, INV-A-002')

    def test_each_invoice_line_gets_only_its_related_serials(self):
        order = self._order([
            (self.cabin_a, 1),
            (self.cabin_b, 1),
            (self.service, 1),
        ])
        line_a = order.order_line.filtered(lambda item: item.product_id == self.cabin_a)
        line_b = order.order_line.filtered(lambda item: item.product_id == self.cabin_b)
        lot_a = self._lot(self.cabin_a, 'INV-LINE-A')
        lot_b = self._lot(self.cabin_b, 'INV-LINE-B')
        self._allocation(line_a, lot_a, allocate=True)
        self._allocation(line_b, lot_b, allocate=True)

        invoice = order._create_invoices()
        invoice_line_a = invoice.invoice_line_ids.filtered(
            lambda item: item.product_id == self.cabin_a)
        invoice_line_b = invoice.invoice_line_ids.filtered(
            lambda item: item.product_id == self.cabin_b)
        service_line = invoice.invoice_line_ids.filtered(
            lambda item: item.product_id == self.service)

        self.assertEqual(invoice_line_a.strx_allocated_lot_ids, lot_a)
        self.assertEqual(invoice_line_a.strx_allocated_serial_numbers, 'INV-LINE-A')
        self.assertEqual(invoice_line_b.strx_allocated_lot_ids, lot_b)
        self.assertEqual(invoice_line_b.strx_allocated_serial_numbers, 'INV-LINE-B')
        self.assertFalse(service_line.strx_allocated_lot_ids)
        self.assertFalse(service_line.strx_allocated_serial_numbers)

    def test_invoice_wizard_checks_allocations_before_creation(self):
        order = self._order([(self.cabin_a, 1)])
        wizard_model = self.env['sale.advance.payment.inv'].with_context(
            active_ids=order.ids,
            active_id=order.id,
            active_model='sale.order')

        with self.assertRaisesRegex(UserError, 'fully allocated'):
            wizard_model.default_get(['sale_order_ids'])

        # The private wizard route is also protected for RPC/integration callers
        # that construct a transient record without opening the form first.
        wizard = wizard_model.with_context(active_ids=[]).create({
            'sale_order_ids': [(6, 0, order.ids)],
        })
        with self.assertRaisesRegex(UserError, 'fully allocated'):
            wizard._create_invoices(order)

        lot = self._lot(self.cabin_a, 'INV-WIZARD-A')
        self._allocation(order.order_line, lot, allocate=True)
        values = wizard_model.default_get(['sale_order_ids'])
        self.assertEqual(values['sale_order_ids'], [(6, 0, order.ids)])

    def test_invoice_report_lists_serials_in_customer_language(self):
        self.partner.lang = 'ar_001'
        order = self._order([(self.cabin_a, 1)])
        lot = self._lot(self.cabin_a, 'INV-REPORT-AR')
        self._allocation(order.order_line, lot, allocate=True)
        invoice = order._create_invoices()

        html, _report_type = self.env['ir.actions.report']._render_qweb_html(
            'account.account_invoices', invoice.ids)

        self.assertIn('الأرقام التسلسلية:'.encode(), html)
        self.assertIn(b'INV-REPORT-AR', html)
