# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReturnAssessment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Return Assessment Customer',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Return Assessment Cabin 5x3',
            'default_code': 'RETURN-ASSESS-5X3',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'serial',
            'strx_is_cabin': True,
            'strx_cabin_size': '5x3',
            'strx_cabin_grade': 'std',
        })

    def _returned_allocation(self, serial_names):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': len(serial_names),
            })],
        })
        order.action_confirm()
        lots = self.env['stock.lot']
        for serial_name in serial_names:
            lots |= self.env['stock.lot'].create({
                'name': serial_name,
                'product_id': self.product.id,
                'company_id': self.env.company.id,
            })
        allocation = self.env['strx.cabin.allocation'].create({
            'order_line_id': order.order_line[0].id,
            'lot_ids': [(6, 0, lots.ids)],
        })
        allocation.action_allocate()
        allocation.write({'state': 'on_rent'})
        lots._strx_set_readiness('on_rent', reason='Delivered test fixture')
        allocation.write({'state': 'returned'})
        lots._strx_set_readiness('returned', reason='Returned test fixture')
        return allocation, lots

    def _wizard(self, allocation):
        return self.env[
            'strx.cabin.return.assessment.wizard'
        ].with_context(default_allocation_id=allocation.id).create({})

    def test_mixed_outcomes_update_each_cabin_and_close_assessment(self):
        allocation, lots = self._returned_allocation([
            'ASSESS-MIXED-READY', 'ASSESS-MIXED-MAINT',
        ])
        ready = lots.filtered(lambda lot: lot.name == 'ASSESS-MIXED-READY')
        maintenance = lots - ready

        action = allocation.action_open_return_assessment()
        self.assertEqual(action['target'], 'new')
        wizard = self._wizard(allocation)
        self.assertEqual(wizard.line_ids.mapped('lot_id'), lots)
        self.assertEqual(
            set(wizard.line_ids.mapped('target_state')), {'in_inspection'})

        ready_line = wizard.line_ids.filtered(lambda line: line.lot_id == ready)
        ready_line.write({
            'target_state': 'available',
            'condition': 'fair',
            'note': 'Minor cosmetic wear only',
        })
        maintenance_line = wizard.line_ids - ready_line
        maintenance_line.write({
            'target_state': 'in_maintenance',
            'condition': 'damaged',
            'note': 'Door hinge requires repair',
        })

        result = wizard.action_confirm_assessment()

        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(allocation.state, 'available')
        self.assertEqual(ready.strx_readiness_state, 'available')
        self.assertEqual(ready.strx_condition, 'fair')
        self.assertTrue(ready.strx_inspection_passed)
        self.assertTrue(ready.strx_cleaning_passed)
        self.assertTrue(ready.strx_selectable)
        self.assertEqual(maintenance.strx_readiness_state, 'in_maintenance')
        self.assertEqual(maintenance.strx_condition, 'damaged')
        self.assertFalse(maintenance.strx_selectable)

        logs = self.env['strx.cabin.readiness.log'].search([
            ('lot_id', 'in', lots.ids),
            ('reason', 'ilike', allocation.name),
            ('old_state', '=', 'returned'),
        ])
        self.assertEqual(len(logs), 2)
        self.assertEqual(set(logs.mapped('condition')), {'fair', 'damaged'})
        self.assertTrue(any(
            'Minor cosmetic wear' in note for note in logs.mapped('note')))
        self.assertTrue(any(
            'Door hinge' in note for note in logs.mapped('note')))

    def test_cleaning_outcome_records_inspection_only(self):
        allocation, lot = self._returned_allocation(['ASSESS-CLEANING'])
        wizard = self._wizard(allocation)
        wizard.line_ids.write({
            'target_state': 'in_cleaning',
            'condition': 'good',
        })

        wizard.action_confirm_assessment()

        self.assertEqual(lot.strx_readiness_state, 'in_cleaning')
        self.assertTrue(lot.strx_inspection_passed)
        self.assertFalse(lot.strx_cleaning_passed)
        self.assertTrue(lot.strx_last_inspection_date)
        self.assertFalse(lot.strx_selectable)

    def test_damaged_condition_cannot_be_marked_available(self):
        allocation, lot = self._returned_allocation(['ASSESS-DAMAGED'])
        wizard = self._wizard(allocation)
        wizard.line_ids.write({
            'target_state': 'available',
            'condition': 'damaged',
        })

        with self.assertRaisesRegex(
                ValidationError, 'cannot be Available'):
            wizard.action_confirm_assessment()

        self.assertEqual(allocation.state, 'returned')
        self.assertEqual(lot.strx_readiness_state, 'returned')
