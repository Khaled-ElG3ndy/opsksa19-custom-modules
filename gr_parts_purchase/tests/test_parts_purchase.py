# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestPartsPurchase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Req = cls.env['gr.parts.request']
        cls.Job = cls.env['gr.maintenance.job']
        cls.Asset = cls.env['gr.generator.asset']
        cls.Line = cls.env['gr.parts.consumption.line']
        cls.vendor = cls.env['res.partner'].create({'name': 'Parts Vendor'})
        cls.company = cls.env.company

        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        cls.stock_loc = cls.warehouse.lot_stock_id

        cls.part = cls.env['product.product'].create({
            'name': 'Fuel Filter',
            'type': 'consu',
            'is_storable': True,
            'purchase_ok': True,
            'standard_price': 40.0,
        })
        cls.other_part = cls.env['product.product'].create({
            'name': 'Oil Filter',
            'type': 'consu',
            'is_storable': True,
            'purchase_ok': True,
            'standard_price': 30.0,
        })
        cls.asset = cls.Asset.create({
            'name': 'PtP Gen',
            'pm_interval_hours': 2000.0,
        })

    def setUp(self):
        super().setUp()
        self.job = self.Job.create({
            'asset_id': self.asset.id,
            'job_type': 'preventive',
        })
        self._set_stock(0.0)

    def _stock_qty(self):
        return self.env['stock.quant']._get_available_quantity(
            self.part, self.stock_loc)

    def _set_stock(self, qty):
        delta = qty - self._stock_qty()
        if delta:
            self.env['stock.quant']._update_available_quantity(
                self.part, self.stock_loc, delta)

    def _request(self, qty=2.0, **kw):
        vals = {
            'job_id': self.job.id,
            'product_id': self.part.id,
            'quantity': qty,
            'vendor_id': self.vendor.id,
            'warehouse_id': self.warehouse.id,
        }
        vals.update(kw)
        return self.Req.create(vals)

    def test_sequence_and_asset_link(self):
        req = self._request()
        self.assertTrue(req.name.startswith('GR/PREQ/'))
        self.assertEqual(req.asset_id, self.asset)
        self.assertEqual(req.source_location_id, self.stock_loc)

    def test_required_one_available_two_issues_without_po(self):
        self._set_stock(2.0)
        req = self._request(qty=1.0)
        req.action_issue_available()
        req.invalidate_recordset()
        self.assertEqual(req.qty_issued, 1.0)
        self.assertEqual(req.qty_remaining_to_issue, 0.0)
        self.assertEqual(req.qty_shortage_to_buy, 0.0)
        self.assertFalse(req.purchase_order_id)
        self.assertEqual(self._stock_qty(), 1.0)

    def test_required_three_available_two_po_for_shortage_only(self):
        self._set_stock(2.0)
        req = self._request(qty=3.0)
        req.action_issue_available()
        req.invalidate_recordset()
        self.assertEqual(req.qty_issued, 2.0)
        self.assertEqual(req.qty_remaining_to_issue, 1.0)
        self.assertEqual(req.qty_shortage_to_buy, 1.0)
        self.assertEqual(req.state, 'issued')

        req.action_generate_po()
        self.assertEqual(req.state, 'purchased')
        self.assertEqual(req.purchase_line_id.product_id, self.part)
        self.assertEqual(req.purchase_line_id.product_qty, 1.0)

    def test_user_can_increase_po_qty_for_restock_without_reopening_shortage(self):
        self._set_stock(2.0)
        req = self._request(qty=3.0)
        req.action_issue_available()
        req.action_generate_po()
        req.purchase_line_id.product_qty = 10.0
        req.invalidate_recordset()
        self.assertEqual(req.qty_shortage_to_buy, 0.0)
        with self.assertRaises(UserError):
            req.action_generate_po()

    def _receive_purchase_order(self, po):
        po.button_confirm()
        for picking in po.picking_ids:
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.button_validate()

    def test_shortage_purchase_restock_receive_and_issue_remaining_only(self):
        self._set_stock(2.0)
        req = self._request(qty=3.0)
        req.action_issue_available()
        self.assertEqual(self._stock_qty(), 0.0)
        self.assertEqual(self.job.total_parts_cost, 80.0)

        req.action_generate_po()
        req.purchase_line_id.write({
            'product_qty': 10.0,
            'price_unit': 40.0,
        })
        req.invalidate_recordset()
        self.assertEqual(req.purchase_qty_ordered, 10.0)
        self.assertEqual(req.qty_shortage_to_buy, 0.0)
        with self.assertRaises(UserError):
            req.action_mark_received()

        self._receive_purchase_order(req.purchase_order_id)
        req.invalidate_recordset(['purchase_qty_received', 'available_qty'])
        self.assertEqual(req.purchase_qty_received, 10.0)
        self.assertEqual(self._stock_qty(), 10.0)

        req.action_mark_received()
        req.action_issue_available()
        req.invalidate_recordset()
        self.assertEqual(req.qty_issued, 3.0)
        self.assertEqual(req.qty_remaining_to_issue, 0.0)
        self.assertEqual(req.qty_shortage_to_buy, 0.0)
        self.assertEqual(self._stock_qty(), 9.0)
        self.assertEqual(
            sum(req.consumption_line_ids.filtered(
                lambda line: line.state == 'consumed').mapped('quantity')),
            3.0)
        self.assertEqual(self.job.total_parts_cost, 120.0)
        req.action_register_installation()
        self.assertTrue(req.reconciled)

    def test_available_zero_po_for_full_required_qty(self):
        self._set_stock(0.0)
        req = self._request(qty=3.0)
        self.assertEqual(req.qty_shortage_to_buy, 3.0)
        req.action_generate_po()
        self.assertEqual(req.purchase_line_id.product_qty, 3.0)

    def test_generate_po_requires_real_shortage_and_vendor(self):
        self._set_stock(5.0)
        req = self._request(qty=3.0)
        with self.assertRaises(UserError):
            req.action_generate_po()
        req.vendor_id = False
        self._set_stock(0.0)
        req.invalidate_recordset()
        with self.assertRaises(UserError):
            req.action_generate_po()

    def test_issue_creates_real_picking_and_stock_move(self):
        self._set_stock(4.0)
        req = self._request(qty=2.0)
        req.action_issue_available()
        line = req.consumption_line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.state, 'consumed')
        self.assertTrue(line.picking_id)
        self.assertTrue(line.move_id)
        self.assertEqual(line.move_id.state, 'done')
        self.assertEqual(line.source_location_id, self.stock_loc)

    def test_cannot_issue_more_than_available_from_consumption_line(self):
        self._set_stock(1.0)
        req = self._request(qty=3.0)
        line = self.Line.create({
            'request_id': req.id,
            'quantity': 2.0,
        })
        with self.assertRaises(UserError):
            line.action_consume()

    def test_register_installation_reconciles_after_issue(self):
        self._set_stock(2.0)
        req = self._request(qty=2.0)
        req.action_issue_available()
        req.action_register_installation()
        req.invalidate_recordset()
        self.assertEqual(req.qty_installed, 2.0)
        self.assertEqual(req.qty_outstanding, 0.0)
        self.assertTrue(req.reconciled)
        self.assertEqual(req.state, 'installed')

    def test_job_cannot_complete_with_unissued_or_uninstalled_request(self):
        self._set_stock(1.0)
        req = self._request(qty=1.0)
        self.job.action_start()
        with self.assertRaises(UserError):
            self.job.action_complete()
        req.action_issue_available()
        with self.assertRaises(UserError):
            self.job.action_complete()
        req.action_register_installation()
        self.job.action_complete()
        self.assertEqual(self.job.state, 'done')

    def test_source_request_onchange_prefills_consumption_line(self):
        self._set_stock(4.0)
        req = self._request(qty=4.0)
        line = self.Line.new({'request_id': req.id})
        line._onchange_request_id()
        self.assertEqual(line.job_id, req.job_id)
        self.assertEqual(line.asset_id, req.asset_id)
        self.assertEqual(line.product_id, req.product_id)
        self.assertEqual(line.warehouse_id, req.warehouse_id)
        self.assertEqual(line.source_location_id, req.source_location_id)
        self.assertEqual(line.request_remaining_qty, 4.0)
        self.assertEqual(line.quantity, 4.0)

    def test_source_request_create_prefills_consumption_line(self):
        self._set_stock(3.0)
        req = self._request(qty=3.0)
        line = self.Line.create({'request_id': req.id})
        self.assertEqual(line.job_id, req.job_id)
        self.assertEqual(line.asset_id, req.asset_id)
        self.assertEqual(line.product_id, req.product_id)
        self.assertEqual(line.warehouse_id, req.warehouse_id)
        self.assertEqual(line.source_location_id, req.source_location_id)
        self.assertEqual(line.request_remaining_qty, 3.0)
        self.assertEqual(line.quantity, 3.0)

    def test_source_request_rejects_unrelated_part(self):
        self._set_stock(2.0)
        req = self._request(qty=2.0)
        with self.assertRaises(ValidationError):
            self.Line.create({
                'request_id': req.id,
                'job_id': req.job_id.id,
                'product_id': self.other_part.id,
                'quantity': 1.0,
            })

    def test_source_request_prevents_over_issue(self):
        self._set_stock(10.0)
        req = self._request(qty=5.0)
        line = self.Line.create({'request_id': req.id, 'quantity': 6.0})
        with self.assertRaises(UserError):
            line.action_consume()

    def test_cancel_draft(self):
        req = self._request()
        req.action_cancel()
        self.assertEqual(req.state, 'cancelled')

    def test_job_lists_requests(self):
        req = self._request()
        self.job.invalidate_recordset()
        self.assertIn(req, self.job.parts_request_ids)
        self.assertEqual(self.job.parts_request_count, 1)
