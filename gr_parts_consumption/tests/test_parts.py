# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestPartsConsumption(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Asset = cls.env['gr.generator.asset']
        cls.Job = cls.env['gr.maintenance.job']
        cls.Line = cls.env['gr.parts.consumption.line']
        cls.company = cls.env.company

        # Warehouse for this company (created with stock install).
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        cls.stock_loc = cls.warehouse.lot_stock_id

        # A storable spare part (Odoo 18: type='consu' + is_storable=True).
        cls.part = cls.env['product.product'].create({
            'name': 'Oil Filter',
            'type': 'consu',
            'is_storable': True,
            'standard_price': 25.0,
        })
        # Put 100 units on hand.
        cls.env['stock.quant']._update_available_quantity(
            cls.part, cls.stock_loc, 100.0)

        cls.asset = cls.Asset.create({
            'name': 'Parts Gen', 'pm_interval_hours': 2000.0})

    def _job(self):
        return self.Job.create({
            'asset_id': self.asset.id, 'job_type': 'preventive'})

    def _on_hand(self):
        return self.env['stock.quant']._get_available_quantity(
            self.part, self.stock_loc)

    # ---------- consumption creates a stock move + decrements on-hand ----------
    def test_consume_decrements_stock(self):
        before = self._on_hand()
        job = self._job()
        line = self.Line.create({
            'job_id': job.id, 'product_id': self.part.id, 'quantity': 3.0})
        line.action_consume()
        self.assertEqual(line.state, 'consumed')
        self.assertTrue(line.move_id)
        self.assertEqual(line.move_id.state, 'done')
        after = self._on_hand()
        self.assertEqual(before - after, 3.0)

    # ---------- cost snapshot ----------
    def test_cost_snapshot(self):
        job = self._job()
        line = self.Line.create({
            'job_id': job.id, 'product_id': self.part.id, 'quantity': 2.0})
        line.action_consume()
        self.assertEqual(line.unit_cost, 25.0)
        self.assertEqual(line.subtotal_cost, 50.0)

    def test_cost_snapshot_is_stable(self):
        # Changing product cost AFTER consumption must not change the snapshot.
        job = self._job()
        line = self.Line.create({
            'job_id': job.id, 'product_id': self.part.id, 'quantity': 1.0})
        line.action_consume()
        self.part.standard_price = 99.0
        line.invalidate_recordset()
        self.assertEqual(line.unit_cost, 25.0)  # unchanged

    # ---------- job total + asset live_cost ----------
    def test_job_total_parts_cost(self):
        job = self._job()
        l1 = self.Line.create({
            'job_id': job.id, 'product_id': self.part.id, 'quantity': 2.0})
        l2 = self.Line.create({
            'job_id': job.id, 'product_id': self.part.id, 'quantity': 4.0})
        l1.action_consume()
        l2.action_consume()
        job.invalidate_recordset()
        self.assertEqual(job.total_parts_cost, (2 + 4) * 25.0)  # 150

    def test_asset_live_cost_reflects_parts(self):
        job = self._job()
        line = self.Line.create({
            'job_id': job.id, 'product_id': self.part.id, 'quantity': 4.0})
        line.action_consume()
        self.asset.invalidate_recordset()
        self.assertEqual(self.asset.live_cost, 100.0)  # 4 * 25
        # profit estimate = revenue - cost; revenue is 0 here -> -100
        self.assertEqual(self.asset.live_profit_estimate,
                         self.asset.live_revenue - 100.0)

    # ---------- draft parts don't count ----------
    def test_draft_line_not_counted(self):
        job = self._job()
        self.Line.create({
            'job_id': job.id, 'product_id': self.part.id, 'quantity': 5.0})
        job.invalidate_recordset()
        self.assertEqual(job.total_parts_cost, 0.0)  # not consumed yet

    # ---------- guards ----------
    def test_cannot_consume_zero_qty(self):
        job = self._job()
        line = self.Line.create({
            'job_id': job.id, 'product_id': self.part.id, 'quantity': 0.0})
        with self.assertRaises(UserError):
            line.action_consume()

    def test_cannot_cancel_consumed(self):
        job = self._job()
        line = self.Line.create({
            'job_id': job.id, 'product_id': self.part.id, 'quantity': 1.0})
        line.action_consume()
        with self.assertRaises(UserError):
            line.action_cancel()

    def test_cannot_reconsume(self):
        job = self._job()
        line = self.Line.create({
            'job_id': job.id, 'product_id': self.part.id, 'quantity': 1.0})
        line.action_consume()
        with self.assertRaises(UserError):
            line.action_consume()

    # ---------- parts category configured (AVCO) ----------
    def test_parts_category_avco(self):
        from odoo.addons.gr_parts_consumption import _configure_parts_category
        cat = self.env.ref('gr_parts_consumption.product_category_gr_parts')
        # Exercise the shared configurator directly so the test does not depend
        # on whether the install-time hook fired in this particular DB state
        # (the field is company-dependent and the hook only runs on a true
        # install transition). The costing method (AVCO) does not require
        # accounting setup, so it must be applied; automated valuation is
        # environment-dependent and is not asserted.
        _configure_parts_category(self.env)
        cat.invalidate_recordset()
        self.assertEqual(
            cat.with_company(self.company).property_cost_method, 'average',
            "Spare-parts category should use AVCO costing so part cost tracks "
            "the last purchase price.")
