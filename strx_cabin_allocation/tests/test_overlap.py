# -*- coding: utf-8 -*-
"""Automated cover for the no-double-booking rule.

Acceptance 10: two overlapping allocations of the same serial are impossible.

The rule lives in strx.cabin.allocation._check_no_overlap, an @api.constrains,
so it re-runs on create AND on any write that moves a serial or a date — the
boundary and open-ended cases below are the ones a naive range check gets wrong.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAllocationOverlap(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.partner = cls.env['res.partner'].create({'name': 'Overlap Test Co.'})
        cls.cabin = cls.env['product.product'].create({
            'name': 'Cabin 5x3 OverlapTest', 'default_code': 'OVL-CAB-5X3',
            'type': 'consu', 'is_storable': True, 'tracking': 'serial',
            'strx_is_cabin': True, 'strx_asset_kind': 'cabin',
            'strx_cabin_size': '5x3', 'strx_cabin_grade': 'std'})

    # ---------------------------------------------------------------- helpers
    def _d(self, offset):
        return self.today + timedelta(days=offset)

    def _lot(self, name):
        return self.env['stock.lot'].create({
            'name': name, 'product_id': self.cabin.id,
            'company_id': self.env.company.id})

    def _order(self):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.cabin.id, 'product_uom_qty': 1})]})

    def _alloc(self, lot, out, ret, order=None):
        order = order or self._order()
        return self.env['strx.cabin.allocation'].create({
            'order_line_id': order.order_line[0].id,
            'lot_id': lot.id,
            'strx_date_out': out,
            'strx_expected_return_date': ret,
        })

    # =========================================================== ACCEPTANCE 10
    def test_10_overlapping_allocations_blocked(self):
        """A second booking of the same serial over the same window is refused."""
        lot = self._lot('OVL-5X3-001')
        self._alloc(lot, self._d(1), self._d(10))
        with self.assertRaises(ValidationError):
            self._alloc(lot, self._d(5), self._d(15))

    def test_10b_contained_and_enclosing_windows_blocked(self):
        """Overlap is not just partial: nested ranges collide too."""
        lot = self._lot('OVL-5X3-002')
        self._alloc(lot, self._d(1), self._d(30))
        # Fully inside the existing booking.
        with self.assertRaises(ValidationError):
            self._alloc(lot, self._d(5), self._d(9))
        # Fully enclosing it.
        with self.assertRaises(ValidationError):
            self._alloc(lot, self._d(0), self._d(40))

    def test_10c_adjacent_windows_allowed(self):
        """Back-to-back rentals are legitimate: one ends before the next starts.

        NOTE the scope of what this proves. Both allocations here are never-actioned
        holds — action_allocate() is not called, so the unit stays Available and the
        tier-2 commitment guard does not engage. Booking an adjacent window against a
        unit that is actually ON RENT is forward booking, which is deliberately
        blocked in this phase (see _strx_assert_lot_selectable). Do not read this test
        as evidence that forward booking works.
        """
        lot = self._lot('OVL-5X3-003')
        self._alloc(lot, self._d(1), self._d(10))
        second = self._alloc(lot, self._d(11), self._d(20))
        self.assertTrue(second.id, "Adjacent, non-overlapping periods must be allowed.")

    def test_10d_shared_boundary_day_blocked(self):
        """Same-day handover is a collision: the unit cannot be in two places."""
        lot = self._lot('OVL-5X3-004')
        self._alloc(lot, self._d(1), self._d(10))
        with self.assertRaises(ValidationError):
            self._alloc(lot, self._d(10), self._d(20))

    def test_10e_open_ended_allocation_conflicts_with_everything(self):
        """Missing dates are open-ended and must fail closed, not open."""
        lot = self._lot('OVL-5X3-005')
        self._alloc(lot, False, False)
        with self.assertRaises(ValidationError):
            self._alloc(lot, self._d(100), self._d(110))

    def test_10f_moving_dates_onto_a_clash_is_blocked(self):
        """The constraint re-runs on write, not only on create."""
        lot = self._lot('OVL-5X3-006')
        self._alloc(lot, self._d(1), self._d(10))
        later = self._alloc(lot, self._d(20), self._d(30))
        with self.assertRaises(ValidationError):
            later.write({'strx_date_out': self._d(5),
                         'strx_expected_return_date': self._d(15)})

    def test_10g_repointing_a_serial_onto_a_clash_is_blocked(self):
        """Swapping lot_id onto an already-booked serial is refused."""
        busy = self._lot('OVL-5X3-007')
        free = self._lot('OVL-5X3-008')
        self._alloc(busy, self._d(1), self._d(10))
        other = self._alloc(free, self._d(5), self._d(15))
        with self.assertRaises(ValidationError):
            other.write({'lot_id': busy.id})

    def test_10h_returned_allocation_no_longer_blocks_reuse(self):
        """Once returned, the old allocation no longer reserves the serial."""
        lot = self._lot('OVL-5X3-RETURNED-FREE')
        old = self._alloc(lot, self._d(1), self._d(10))
        old.write({'state': 'returned'})

        new = self._alloc(lot, self._d(5), self._d(15))

        self.assertTrue(new.id)

    def test_10h_cancelled_allocation_frees_the_serial(self):
        """A cancelled booking must not keep blocking the unit."""
        lot = self._lot('OVL-5X3-009')
        first = self._alloc(lot, self._d(1), self._d(10))
        with self.assertRaises(ValidationError):
            self._alloc(lot, self._d(5), self._d(15))
        first.action_cancel()
        freed = self._alloc(lot, self._d(5), self._d(15))
        self.assertTrue(freed.id, "Cancelling must release the serial.")

    def test_10i_different_serials_may_share_a_period(self):
        """The rule is per serial, not per specification."""
        lot_a = self._lot('OVL-5X3-010')
        lot_b = self._lot('OVL-5X3-011')
        self._alloc(lot_a, self._d(1), self._d(10))
        second = self._alloc(lot_b, self._d(1), self._d(10))
        self.assertTrue(second.id,
                        "Two different units may be out over the same period.")
