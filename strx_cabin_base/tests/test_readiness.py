# -*- coding: utf-8 -*-
"""Automated cover for the readiness state machine.

Acceptance 9: a returned cabin cannot be re-rented until inspection AND
              cleaning both pass.

The gate lives in stock.lot.write(), so it holds for every path — the state
machine helper, a direct write, and a bulk write over a recordset alike. Each of
those is exercised below; a gate that only guards the helper would be trivially
bypassable from an import or the Inventory screen.
"""
import base64

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReadinessReturnGate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cabin = cls.env['product.product'].create({
            'name': 'Cabin 5x3 GateTest', 'default_code': 'GATE-CAB-5X3',
            'type': 'consu', 'is_storable': True, 'tracking': 'serial',
            'strx_is_cabin': True, 'strx_asset_kind': 'cabin',
            'strx_cabin_size': '5x3', 'strx_cabin_grade': 'std'})

    # ---------------------------------------------------------------- helpers
    def _returned_lot(self, name, state='returned'):
        """A unit that has come back from a rental and is awaiting clearance."""
        lot = self.env['stock.lot'].create({
            'name': name, 'product_id': self.cabin.id,
            'company_id': self.env.company.id})
        lot._strx_set_readiness('on_rent', reason='Out on rent')
        lot._strx_set_readiness(state, reason='Came back')
        return lot

    # ============================================================ ACCEPTANCE 9
    def test_09_returned_needs_both_inspection_and_cleaning(self):
        """Neither check, or only one, must not reopen the unit for rental."""
        lot = self._returned_lot('GATE-NEITHER')
        self.assertFalse(lot.strx_selectable)

        # Neither passed.
        with self.assertRaises(ValidationError):
            lot._strx_set_readiness('available', reason='Too early')

        # Inspection only.
        lot.strx_inspection_passed = True
        lot.strx_cleaning_passed = False
        with self.assertRaises(ValidationError):
            lot._strx_set_readiness('available', reason='Inspection only')

        # Cleaning only.
        lot.strx_inspection_passed = False
        lot.strx_cleaning_passed = True
        with self.assertRaises(ValidationError):
            lot._strx_set_readiness('available', reason='Cleaning only')

        # Still stuck, and still not offerable.
        self.assertEqual(lot.strx_readiness_state, 'returned')
        self.assertFalse(lot.strx_selectable)

        # Both passed → the unit reopens.
        lot.strx_inspection_passed = True
        lot.strx_cleaning_passed = True
        lot._strx_set_readiness('available', reason='Cleared')
        self.assertEqual(lot.strx_readiness_state, 'available')
        self.assertTrue(lot.strx_selectable,
                        "A cleared unit must be offerable again.")

    def test_09b_gate_holds_on_direct_write(self):
        """The gate is in write(), so a raw write cannot slip past it."""
        lot = self._returned_lot('GATE-DIRECT')
        with self.assertRaises(ValidationError):
            lot.write({'strx_readiness_state': 'available'})

        # Nor by flipping the flags in the SAME write as the state.
        with self.assertRaises(ValidationError):
            lot.write({'strx_readiness_state': 'available',
                       'strx_inspection_passed': True})
        self.assertEqual(lot.strx_readiness_state, 'returned')

    def test_09c_gate_applies_across_post_return_states(self):
        """in_inspection and in_cleaning are gated exactly like returned."""
        for state in ('returned', 'in_inspection', 'in_cleaning'):
            lot = self._returned_lot('GATE-%s' % state.upper(), state=state)
            with self.assertRaises(ValidationError):
                lot._strx_set_readiness('available', reason='Not cleared')
            self.assertEqual(lot.strx_readiness_state, state)

    def test_09d_gate_holds_on_bulk_write(self):
        """A multi-record write must not let one ungated unit through."""
        cleared = self._returned_lot('GATE-BULK-OK')
        cleared.write({'strx_inspection_passed': True, 'strx_cleaning_passed': True})
        blocked = self._returned_lot('GATE-BULK-NO')

        with self.assertRaises(ValidationError):
            (cleared | blocked).write({'strx_readiness_state': 'available'})

        # The guard runs before super().write(), so neither unit moved.
        self.assertEqual(blocked.strx_readiness_state, 'returned')
        self.assertEqual(cleared.strx_readiness_state, 'returned')

    def test_09e_non_return_states_are_not_gated(self):
        """The gate must not trap units that never went out on rent."""
        lot = self.env['stock.lot'].create({
            'name': 'GATE-MAINT', 'product_id': self.cabin.id,
            'company_id': self.env.company.id})
        lot._strx_set_readiness('in_maintenance', reason='Scheduled service')
        lot._strx_set_readiness('available', reason='Service done')
        self.assertEqual(lot.strx_readiness_state, 'available')

    def test_16_cabin_barcode_defaults_to_serial(self):
        """Every cabin card must have a barcode even if the user leaves it empty."""
        lot = self.env['stock.lot'].create({
            'name': 'CARD-AUTO-BARCODE',
            'product_id': self.cabin.id,
            'company_id': self.env.company.id,
        })
        self.assertEqual(lot.strx_barcode, 'CARD-AUTO-BARCODE')

    def test_16b_cabin_barcode_must_be_unique(self):
        """Two cabin identity cards may not carry the same scannable barcode."""
        self.env['stock.lot'].create({
            'name': 'CARD-UNIQUE-A',
            'product_id': self.cabin.id,
            'company_id': self.env.company.id,
            'strx_barcode': 'CARD-UNIQUE',
        })
        with self.assertRaises(ValidationError):
            self.env['stock.lot'].create({
                'name': 'CARD-UNIQUE-B',
                'product_id': self.cabin.id,
                'company_id': self.env.company.id,
                'strx_barcode': 'CARD-UNIQUE',
            })

    def test_16c_cabin_barcode_must_be_printable_code128(self):
        """Cabin barcodes are physical scan codes, so keep them Code128-B safe."""
        with self.assertRaises(ValidationError):
            self.env['stock.lot'].create({
                'name': 'CARD-AR-BARCODE',
                'product_id': self.cabin.id,
                'company_id': self.env.company.id,
                'strx_barcode': 'كابينة-001',
            })

    def test_16d_cabin_card_smart_button_opens_preview(self):
        """The smart button opens a preview wizard instead of downloading at once."""
        lot = self.env['stock.lot'].create({
            'name': 'CARD-REPORT',
            'product_id': self.cabin.id,
            'company_id': self.env.company.id,
        })
        action = lot.action_strx_print_cabin_card()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'strx.cabin.id.card.wizard')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['context']['default_lot_id'], lot.id)

    def test_16e_cabin_card_download_action(self):
        """The preview wizard download button returns the PDF report action."""
        lot = self.env['stock.lot'].create({
            'name': 'CARD-DOWNLOAD',
            'product_id': self.cabin.id,
            'company_id': self.env.company.id,
        })
        action = lot.action_strx_download_cabin_card()
        self.assertEqual(action['type'], 'ir.actions.report')
        self.assertEqual(action['report_type'], 'qweb-pdf')
        report = self.env.ref('strx_cabin_base.action_report_strx_cabin_id_card')
        self.assertEqual(report.report_name, 'strx_cabin_base.report_cabin_id_card')
        self.assertEqual(report.paperformat_id.orientation, 'Portrait')
        self.assertEqual(report.paperformat_id.page_width, 148)
        self.assertEqual(report.paperformat_id.page_height, 210)

    def test_16f_cabin_card_preview_is_localized_and_directional(self):
        lot = self.env['stock.lot'].create({
            'name': 'CARD-RTL',
            'product_id': self.cabin.id,
            'company_id': self.env.company.id,
        })
        html = lot.with_context(lang='ar_001').strx_get_cabin_card_preview_html()
        self.assertIn('dir="rtl"', html)
        self.assertIn('بطاقة تعريف الكابينة', html)
        self.assertIn('الرقم التسلسلي', html)
        self.assertIn('رمز QR', html)
        self.assertIn('امسح لفتح صفحة الكابينة', html)
        self.assertIn('المواصفة', html)
        self.assertIn('strx-cabin-card-v2', html)
        self.assertIn('width:650px;height:956px', html)
        self.assertEqual(html.count('data:image/svg+xml;base64,'), 10)
        self.assertEqual(html.count('data:image/png;base64,'), 1)
        self.assertIn('/odoo/lots/%s' % lot.id, html)
        self.assertNotIn('>Serial<', html)
        self.assertNotIn('>Barcode<', html)
        self.assertNotIn('>Specification<', html)

    def test_16g_cabin_qr_links_to_exact_record(self):
        lot = self.env['stock.lot'].create({
            'name': 'CARD-QR-LINK',
            'product_id': self.cabin.id,
            'company_id': self.env.company.id,
        })
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        self.assertEqual(
            lot.strx_get_cabin_record_url(),
            '%s/odoo/lots/%s' % (base_url.rstrip('/'), lot.id),
        )
        qr_data = base64.b64decode(lot.strx_get_cabin_qr_png_b64())
        self.assertTrue(qr_data.startswith(b'\x89PNG\r\n\x1a\n'))
