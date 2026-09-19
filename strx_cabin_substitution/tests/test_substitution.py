# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError

BYPASS = {'strx_bypass_dispatch_control': True}


@tagged('post_install', '-at_install')
class TestSubstitution(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.stock_loc = cls.warehouse.lot_stock_id
        cls.customer_loc = cls.env.ref('stock.stock_location_customers')
        cls.partner = cls.env['res.partner'].create({'name': 'Subst Customer'})
        cls.cab53 = cls._make_cabin('CAB-5X3-STD-T', '5x3', 15000)
        cls.cab55 = cls._make_cabin('CAB-5X5-STD-T', '5x5', 22000)
        # A genuine non-superuser, for the forgery test.
        cls.yard_user = cls.env['res.users'].create({
            'name': 'Yard Operator', 'login': 'strx_yard_op',
            'group_ids': [(6, 0, [cls.env.ref('stock.group_stock_user').id])]})

    @classmethod
    def _make_cabin(cls, code, size, price):
        return cls.env['product.product'].create({
            'name': 'Cabin %s' % code, 'default_code': code, 'type': 'consu',
            'is_storable': True, 'tracking': 'serial', 'strx_is_cabin': True,
            'strx_asset_kind': 'cabin', 'strx_cabin_size': size,
            'strx_cabin_grade': 'std', 'list_price': price})

    def _serial(self, product, name, state=None, condition=None):
        lot = self.env['stock.lot'].create({
            'name': name, 'product_id': product.id, 'company_id': self.env.company.id})
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_loc, 1.0, lot_id=lot)
        if state:
            lot._strx_set_readiness(state, reason='Substitution test fixture')
        if condition:
            lot.write({'strx_condition': condition})
        return lot

    def _rental(self, product):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1})]})
        so.action_confirm()
        picking = so.picking_ids.filtered(lambda p: p.picking_type_id.code == 'outgoing')[:1]
        picking.action_assign()
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

    # ============================================================ 1. same spec
    def test_01_same_spec_reallocates_without_approval(self):
        lot_a = self._serial(self.cab53, 'S1-5X3-A')
        lot_b = self._serial(self.cab53, 'S1-5X3-B')
        so, picking = self._rental(self.cab53)
        alloc = self._allocate(so, lot_a)
        sub = self.env['strx.cabin.substitution'].create({
            'allocation_id': alloc.id,
            'proposed_product_id': self.cab53.id, 'proposed_lot_id': lot_b.id})
        self.assertFalse(sub.is_spec_change)
        sub.action_submit()                       # no approval gate for same spec
        self.assertEqual(sub.state, 'approved')
        self.assertEqual(alloc.lot_id, lot_b)     # reallocated
        self.assertEqual(lot_a.strx_readiness_state, 'available')
        self.assertEqual(lot_b.strx_readiness_state, 'allocated')

    # ============================================================ 2. spec change
    def test_02_spec_change_blocks_until_approved_then_dispatches(self):
        lot_53 = self._serial(self.cab53, 'S2-5X3-A')
        lot_55 = self._serial(self.cab55, 'S2-5X5-A')
        so, picking = self._rental(self.cab53)
        alloc = self._allocate(so, lot_53)
        sub = self.env['strx.cabin.substitution'].create({
            'allocation_id': alloc.id,
            'proposed_product_id': self.cab55.id, 'proposed_lot_id': lot_55.id,
            'reason': 'Customer site upgraded', 'site_fit_confirmed': True,
            'price_impact': 0.0})
        self.assertTrue(sub.is_spec_change)
        sub.action_submit()
        self.assertEqual(sub.state, 'submitted')          # needs approval
        self.assertEqual(alloc.product_id, self.cab53)    # not yet changed

        sub.action_approve()
        self.assertEqual(sub.state, 'approved')
        self.assertEqual(alloc.product_id, self.cab55)    # allocation re-pointed
        self.assertEqual(alloc.lot_id, lot_55)
        # The delivery now carries the 5x5 and validates through the hard-stop.
        self.assertEqual(picking.move_line_ids.filtered(lambda l: l.quantity or l.lot_id).lot_id, lot_55)
        self._finish_qty(picking)
        picking.button_validate()
        self.assertEqual(picking.state, 'done')

    # ============================================================ 3. free upgrade
    def test_03_free_upgrade_requires_commercial_value(self):
        lot_53 = self._serial(self.cab53, 'S3-5X3-A')
        lot_55 = self._serial(self.cab55, 'S3-5X5-A')
        so, picking = self._rental(self.cab53)
        alloc = self._allocate(so, lot_53)
        sub = self.env['strx.cabin.substitution'].create({
            'allocation_id': alloc.id,
            'proposed_product_id': self.cab55.id, 'proposed_lot_id': lot_55.id,
            'reason': 'Goodwill upgrade', 'site_fit_confirmed': True,
            'price_impact': 0.0})
        self.assertTrue(sub.is_free_upgrade)              # 5x5 > 5x3, no charge
        sub.commercial_value = 0.0                        # blank the recorded value
        with self.assertRaises(UserError):
            sub.action_submit()                           # must not allow zero-record
        # Recording the giveaway value lets it proceed.
        sub.commercial_value = self.cab55.list_price - self.cab53.list_price
        sub.action_submit()
        self.assertEqual(sub.state, 'submitted')

    # ============================================================ 4. bypass forgery
    def test_04_bypass_key_not_user_forgeable(self):
        """A normal user cannot pass the hard-stop by forging the bypass context.
        The same operation succeeds only from the server-side sudo path."""
        lot_53 = self._serial(self.cab53, 'S4-5X3-A')
        lot_55 = self._serial(self.cab55, 'S4-5X5-X')
        so, picking = self._rental(self.cab53)
        self._allocate(so, lot_53)                        # approved spec = 5x3
        move = self.env['stock.move'].create({
            'product_id': self.cab55.id, 'product_uom_qty': 1,
            'product_uom': self.cab55.uom_id.id, 'picking_id': picking.id,
            'location_id': self.stock_loc.id, 'location_dest_id': self.customer_loc.id})

        # (a) User forges the bypass context -> STILL blocked (env.su is False).
        with self.assertRaises(UserError):
            self.env['stock.move.line'].with_user(self.yard_user).with_context(**BYPASS).create({
                'move_id': move.id, 'picking_id': picking.id, 'product_id': self.cab55.id,
                'lot_id': lot_55.id, 'quantity': 1,
                'location_id': self.stock_loc.id, 'location_dest_id': self.customer_loc.id})

        # (b) The identical write from the server-side sudo path DOES pass — proving the
        #     gate is su-mode, not "always block".
        ok_line = self.env['stock.move.line'].sudo().with_context(**BYPASS).create({
            'move_id': move.id, 'picking_id': picking.id, 'product_id': self.cab55.id,
            'lot_id': lot_55.id, 'quantity': 1,
            'location_id': self.stock_loc.id, 'location_dest_id': self.customer_loc.id})
        self.assertTrue(ok_line.exists())

    def test_05_damaged_proposed_serial_is_rejected_server_side(self):
        lot_ok = self._serial(self.cab53, 'S5-5X3-OK')
        lot_damaged = self._serial(self.cab53, 'S5-5X3-DMG', condition='damaged')
        so, picking = self._rental(self.cab53)
        alloc = self._allocate(so, lot_ok)

        sub = self.env['strx.cabin.substitution'].create({
            'allocation_id': alloc.id,
            'proposed_product_id': self.cab53.id,
            'proposed_lot_id': lot_damaged.id,
        })
        with self.assertRaises(UserError):
            sub.action_submit()
        self.assertEqual(alloc.lot_id, lot_ok)
        self.assertEqual(lot_damaged.strx_condition, 'damaged')
