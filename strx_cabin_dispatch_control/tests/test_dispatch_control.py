# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError

BYPASS = {'strx_bypass_dispatch_control': True}


@tagged('post_install', '-at_install')
class TestDispatchControl(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.stock_loc = cls.warehouse.lot_stock_id
        cls.customer_loc = cls.env.ref('stock.stock_location_customers')
        cls.internal_b = cls.env['stock.location'].create({
            'name': 'Yard-B', 'usage': 'internal',
            'location_id': cls.warehouse.view_location_id.id})
        cls.partner = cls.env['res.partner'].create({'name': 'Test Cabin Customer'})

        cls.cab53 = cls._make_cabin('CAB-5X3-STD', '5x3')
        cls.cab55 = cls._make_cabin('CAB-5X5-STD', '5x5')
        cls.generic = cls.env['product.product'].create({
            'name': 'Loading Ramp', 'default_code': 'GEN-RAMP',
            'type': 'consu', 'is_storable': True})

    # ---------------------------------------------------------------- helpers
    @classmethod
    def _make_cabin(cls, code, size):
        return cls.env['product.product'].create({
            'name': 'Cabin %s' % size, 'default_code': code,
            'type': 'consu', 'is_storable': True, 'tracking': 'serial',
            'strx_is_cabin': True, 'strx_asset_kind': 'cabin',
            'strx_cabin_size': size, 'strx_cabin_grade': 'std'})

    def _serial_in_stock(self, product, name, location=None):
        lot = self.env['stock.lot'].create({
            'name': name, 'product_id': product.id, 'company_id': self.env.company.id})
        self.env['stock.quant']._update_available_quantity(
            product, location or self.stock_loc, 1.0, lot_id=lot)
        return lot

    def _rental_with_delivery(self, product, qty=1):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': qty})]})
        so.action_confirm()
        picking = so.picking_ids.filtered(
            lambda p: p.picking_type_id.code == 'outgoing')[:1]
        return so, picking

    def _allocate(self, so, lot):
        alloc = self.env['strx.cabin.allocation'].create({
            'order_line_id': so.order_line[0].id, 'lot_id': lot.id})
        alloc.action_allocate()
        return alloc

    def _finish_qty(self, picking):
        for ml in picking.move_line_ids:
            if not ml.quantity:
                ml.quantity = 1
        picking.move_ids.picked = True

    # =================================================================== BLOCKS
    def test_01_block_wrong_spec_on_validate(self):
        """5x5 serial on a 5x3 order → blocked at button_validate."""
        lot53 = self._serial_in_stock(self.cab53, 'V1-5X3-A')
        lot55 = self._serial_in_stock(self.cab55, 'V1-5X5-X')
        so, picking = self._rental_with_delivery(self.cab53)
        self._allocate(so, lot53)
        picking.action_assign()
        # Plant a wrong-spec line via the audited bypass (simulates a line that reached
        # the picking through a path that skipped create); validate must still block.
        move = self.env['stock.move'].sudo().with_context(**BYPASS).create({
            'product_id': self.cab55.id, 'product_uom_qty': 1,
            'product_uom': self.cab55.uom_id.id, 'picking_id': picking.id,
            'location_id': self.stock_loc.id, 'location_dest_id': self.customer_loc.id})
        self.env['stock.move.line'].sudo().with_context(**BYPASS).create({
            'move_id': move.id, 'picking_id': picking.id, 'product_id': self.cab55.id,
            'lot_id': lot55.id, 'quantity': 1,
            'location_id': self.stock_loc.id, 'location_dest_id': self.customer_loc.id})
        self._finish_qty(picking)
        with self.assertRaises(UserError):
            picking.button_validate()

    def test_02_block_wrong_serial_on_validate(self):
        """Correct spec, non-allocated serial → blocked at button_validate."""
        lot_ok = self._serial_in_stock(self.cab53, 'V2-5X3-OK')
        lot_bad = self._serial_in_stock(self.cab53, 'V2-5X3-BAD')
        so, picking = self._rental_with_delivery(self.cab53)
        self._allocate(so, lot_ok)
        picking.action_assign()
        # Swap in the wrong (correct-spec) serial — allowed at write (softened) ...
        picking.move_line_ids[:1].write({'lot_id': lot_bad.id})
        self._finish_qty(picking)
        with self.assertRaises(UserError):        # ... but blocked at validate
            picking.button_validate()

    def test_03_block_no_allocation_on_validate(self):
        """Controlled cabin dispatch with no allocation at all → blocked."""
        self._serial_in_stock(self.cab53, 'V3-5X3-A')
        so, picking = self._rental_with_delivery(self.cab53)
        picking.action_assign()                    # no allocation created
        self._finish_qty(picking)
        with self.assertRaises(UserError):
            picking.button_validate()

    def test_04_block_spec_injection_on_create(self):
        """Injecting a 5x5 move line onto a 5x3 delivery → blocked at create."""
        lot53 = self._serial_in_stock(self.cab53, 'V4-5X3-A')
        lot55 = self._serial_in_stock(self.cab55, 'V4-5X5-X')
        so, picking = self._rental_with_delivery(self.cab53)
        self._allocate(so, lot53)                  # approved set now holds 5x3
        move = self.env['stock.move'].create({
            'product_id': self.cab55.id, 'product_uom_qty': 1,
            'product_uom': self.cab55.uom_id.id, 'picking_id': picking.id,
            'location_id': self.stock_loc.id, 'location_dest_id': self.customer_loc.id})
        with self.assertRaises(UserError):
            self.env['stock.move.line'].create({
                'move_id': move.id, 'picking_id': picking.id, 'product_id': self.cab55.id,
                'lot_id': lot55.id, 'quantity': 1,
                'location_id': self.stock_loc.id, 'location_dest_id': self.customer_loc.id})

    # =================================================================== PASSES
    def test_05_pass_correct_serial_validates(self):
        """The exact allocated serial dispatches normally."""
        lot = self._serial_in_stock(self.cab53, 'P5-5X3-A')
        so, picking = self._rental_with_delivery(self.cab53)
        self._allocate(so, lot)
        picking.action_assign()
        self.assertEqual(picking.move_line_ids.lot_id, lot)
        self._finish_qty(picking)
        picking.button_validate()
        self.assertEqual(picking.state, 'done')

    def test_06_pass_non_cabin_untouched(self):
        """An ordinary (non-cabin) delivery passes through untouched."""
        self.env['stock.quant']._update_available_quantity(
            self.generic, self.stock_loc, 5.0)
        so, picking = self._rental_with_delivery(self.generic)
        picking.action_assign()
        self._finish_qty(picking)
        picking.button_validate()
        self.assertEqual(picking.state, 'done')

    def test_07_pass_internal_cabin_move_untouched(self):
        """Cabin moved yard→yard (internal) is not a dispatch → untouched."""
        lot = self._serial_in_stock(self.cab53, 'P7-5X3-A')
        pt = self.warehouse.int_type_id            # exists but may be inactive
        picking = self.env['stock.picking'].create({
            'picking_type_id': pt.id,
            'location_id': self.stock_loc.id, 'location_dest_id': self.internal_b.id,
            'move_ids': [(0, 0, {
                'product_id': self.cab53.id, 'product_uom_qty': 1,
                'product_uom': self.cab53.uom_id.id,
                'location_id': self.stock_loc.id, 'location_dest_id': self.internal_b.id})]})
        picking.action_confirm()
        picking.action_assign()
        self._finish_qty(picking)
        picking.button_validate()                  # no allocation, must still pass
        self.assertEqual(picking.state, 'done')

    def test_08_pass_incoming_return_untouched(self):
        """A cabin returning from a customer (incoming) is not a dispatch → untouched."""
        pt = self.warehouse.in_type_id
        picking = self.env['stock.picking'].create({
            'picking_type_id': pt.id,
            'location_id': self.customer_loc.id, 'location_dest_id': self.stock_loc.id,
            'move_ids': [(0, 0, {
                'product_id': self.cab53.id, 'product_uom_qty': 1,
                'product_uom': self.cab53.uom_id.id,
                'location_id': self.customer_loc.id, 'location_dest_id': self.stock_loc.id})]})
        picking.action_confirm()
        picking.action_assign()
        for ml in picking.move_line_ids:
            ml.lot_name = 'RET-5X3-1'
            ml.quantity = 1
        picking.move_ids.picked = True
        picking.button_validate()                  # no allocation, must still pass
        self.assertEqual(picking.state, 'done')

    def test_09_pass_reservation_not_blocked_after_softening(self):
        """With an allocation present, reserving / writing a different correct-spec
        serial no longer raises (the softening) — it is caught only at validate."""
        lot_alloc = self._serial_in_stock(self.cab53, 'P9-5X3-ALLOC')
        lot_other = self._serial_in_stock(self.cab53, 'P9-5X3-OTHER')
        so, picking = self._rental_with_delivery(self.cab53)
        self._allocate(so, lot_alloc)
        picking.action_assign()                    # must not raise even if it grabs OTHER
        # Explicitly write the non-allocated correct-spec serial: pre-softening this
        # raised; now it must be allowed.
        picking.move_line_ids[:1].write({'lot_id': lot_other.id})
        self.assertEqual(picking.move_line_ids[:1].lot_id, lot_other)

    def test_10_block_message_follows_user_language(self):
        """The block dialog is English or Arabic according to the user language."""
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module'].search([
            ('name', '=', 'strx_cabin_dispatch_control'),
            ('state', '=', 'installed'),
        ])._update_translations(['ar_001'])

        lot53 = self._serial_in_stock(self.cab53, 'V10-5X3-A')
        lot55 = self._serial_in_stock(self.cab55, 'V10-5X5-X')
        so, picking = self._rental_with_delivery(self.cab53)
        self._allocate(so, lot53)
        picking.action_assign()
        move = self.env['stock.move'].sudo().with_context(**BYPASS).create({
            'product_id': self.cab55.id, 'product_uom_qty': 1,
            'product_uom': self.cab55.uom_id.id, 'picking_id': picking.id,
            'location_id': self.stock_loc.id, 'location_dest_id': self.customer_loc.id})
        self.env['stock.move.line'].sudo().with_context(**BYPASS).create({
            'move_id': move.id, 'picking_id': picking.id, 'product_id': self.cab55.id,
            'lot_id': lot55.id, 'quantity': 1,
            'location_id': self.stock_loc.id, 'location_dest_id': self.customer_loc.id})
        self._finish_qty(picking)

        with self.assertRaises(UserError) as cm_en:
            picking.with_context(lang='en_US').button_validate()
        msg_en = cm_en.exception.args[0]
        self.assertIn('Dispatch blocked — wrong specification.', msg_en)
        self.assertIn('Required:', msg_en)
        self.assertNotIn('تم منع الإرسال', msg_en)

        with self.assertRaises(UserError) as cm:
            picking.with_context(lang='ar_001').button_validate()
        msg = cm.exception.args[0]
        self.assertIn('تم منع الإرسال — المواصفة غير صحيحة.', msg)
        self.assertIn('مطلوب:', msg)
        self.assertNotIn('Dispatch blocked', msg)
