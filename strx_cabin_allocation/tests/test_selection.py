# -*- coding: utf-8 -*-
"""Automated cover for the client's selection-list acceptance tests.

Acceptance 5 : a damaged cabin does not appear in selection at all.
Acceptance 6 : an on-rent / in-maintenance cabin appears, colour-coded and
               Arabic-labelled, but is NOT selectable.
Acceptance 10: two overlapping allocations of the same serial are impossible.

The picker tests deliberately evaluate the REAL domain declared on
strx.cabin.allocation.lot_id rather than re-stating it here — a test that
re-implements the domain would keep passing after the domain was broken.
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install')
class TestCabinSelection(TransactionCase):

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
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.stock_loc = cls.warehouse.lot_stock_id
        cls.partner = cls.env['res.partner'].create({'name': 'Selection Test Co.'})
        cls.cab53 = cls.env['product.product'].create({
            'name': 'Cabin 5x3 SelTest', 'default_code': 'SEL-CAB-5X3',
            'type': 'consu', 'is_storable': True, 'tracking': 'serial',
            'strx_is_cabin': True, 'strx_asset_kind': 'cabin',
            'strx_cabin_size': '5x3', 'strx_cabin_grade': 'std'})

    # ---------------------------------------------------------------- helpers
    def _serial(self, product, name, state=None, condition=None):
        """A serialised unit sitting in the yard, optionally forced to a state."""
        lot = self.env['stock.lot'].create({
            'name': name, 'product_id': product.id,
            'company_id': self.env.company.id})
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_loc, 1.0, lot_id=lot)
        if state:
            lot._strx_set_readiness(state, reason='Selection test fixture')
        if condition:
            lot.write({'strx_condition': condition})
        return lot

    def _order(self):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.cab53.id, 'product_uom_qty': 1})]})

    def _picker_lots(self, product, current_lot=False):
        """Run the ACTUAL allocation picker domain and return what it offers."""
        domain_str = self.env['strx.cabin.allocation']._fields['lot_id'].domain
        domain = safe_eval(domain_str, {
            'product_id': product.id,
            'lot_id': current_lot.id if current_lot else False,
        })
        return self.env['stock.lot'].search(domain)

    def test_picker_context_is_a_mapping_for_web_read(self):
        """Odoo's web client expands relational-field context with ``**``."""
        field = self.env['strx.cabin.allocation']._fields['lot_id']
        self.assertIsInstance(
            field.context, dict,
            "Relational field context must be a mapping, not a Python string.")
        self.assertEqual(field.context['strx_selection_label'], 1)
        self.assertEqual(
            field.context['list_view_ref'],
            'strx_cabin_allocation.view_lot_picker_strx')

        # Exercise the exact Odoo 18 path that used to fail while opening the
        # Cabin Allocations list: web_search_read -> web_read -> with_context.
        result = self.env['strx.cabin.allocation'].web_search_read(
            domain=[],
            specification={
                'name': {},
                'lot_id': {
                    'fields': {'display_name': {}},
                    'context': field.context,
                },
            },
            limit=1,
        )
        self.assertIn('records', result)

    def test_multi_serial_count_follows_sale_line_quantity(self):
        order = self._order()
        line = order.order_line[0]
        line.product_uom_qty = 2
        order.action_confirm()
        lot_a = self._serial(self.cab53, 'MULTI-QTY-A')
        lot_b = self._serial(self.cab53, 'MULTI-QTY-B')

        allocation = self.env['strx.cabin.allocation'].create({
            'order_line_id': line.id,
            'lot_ids': [(6, 0, [lot_a.id, lot_b.id])],
        })
        self.assertEqual(allocation.required_serial_count, 2)
        self.assertEqual(allocation.selected_serial_count, 2)
        self.assertEqual(allocation.lot_ids, lot_a | lot_b)

        allocation.action_allocate()
        self.assertEqual(allocation.state, 'allocated')
        self.assertEqual(
            set(allocation.lot_ids.mapped('strx_readiness_state')), {'allocated'})
        with self.assertRaisesRegex(UserError, 'cannot be reduced'):
            line.write({'product_uom_qty': 1})
        self.assertEqual(line.product_uom_qty, 2)

    def test_multi_serial_warns_when_incomplete_and_blocks_allocate(self):
        order = self._order()
        line = order.order_line[0]
        line.product_uom_qty = 2
        order.action_confirm()
        lot_a = self._serial(self.cab53, 'MULTI-LESS-A')

        draft = self.env['strx.cabin.allocation'].new({
            'order_line_id': line.id,
            'lot_ids': [(6, 0, [lot_a.id])],
        })
        warning = draft._onchange_lot_ids()
        self.assertIn('warning', warning)
        self.assertIn('1', warning['warning']['message'])
        self.assertIn('2', warning['warning']['message'])

        allocation = self.env['strx.cabin.allocation'].create({
            'order_line_id': line.id,
            'lot_ids': [(6, 0, [lot_a.id])],
        })
        with self.assertRaisesRegex(UserError, 'selected 1 of 2'):
            allocation.action_allocate()
        self.assertEqual(allocation.state, 'draft')
        self.assertEqual(lot_a.strx_readiness_state, 'available')

    def test_multi_serial_cannot_exceed_sale_line_quantity(self):
        order = self._order()
        line = order.order_line[0]
        line.product_uom_qty = 2
        lots = (
            self._serial(self.cab53, 'MULTI-MAX-A')
            | self._serial(self.cab53, 'MULTI-MAX-B')
            | self._serial(self.cab53, 'MULTI-MAX-C'))

        draft = self.env['strx.cabin.allocation'].new({
            'order_line_id': line.id,
            'lot_ids': [(6, 0, lots.ids)],
        })
        warning = draft._onchange_lot_ids()
        self.assertIn('warning', warning)
        self.assertEqual(len(draft.lot_ids), 2)

        with self.assertRaisesRegex(ValidationError, 'cannot exceed'):
            self.env['strx.cabin.allocation'].create({
                'order_line_id': line.id,
                'lot_ids': [(6, 0, lots.ids)],
            })

    def test_allocation_action_name_follows_user_language(self):
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module'].search([
            ('name', '=', 'strx_cabin_allocation'),
            ('state', '=', 'installed'),
        ])._update_translations(['ar_001'])

        order = self._order()
        self.assertEqual(
            order.with_context(lang='en_US').action_view_strx_allocations()['name'],
            'Cabin Allocations')
        self.assertEqual(
            order.with_context(lang='ar_001').action_view_strx_allocations()['name'],
            'تخصيصات الكبائن')

    # ============================================================ ACCEPTANCE 5
    def test_05_damaged_and_retired_hidden_from_selection(self):
        """A damaged (or retired) cabin is absent from the picker entirely."""
        good = self._serial(self.cab53, 'SEL-5X3-OK')
        damaged = self._serial(self.cab53, 'SEL-5X3-DMG', state='damaged')
        retired = self._serial(self.cab53, 'SEL-5X3-RET', state='retired')

        offered = self._picker_lots(self.cab53)

        self.assertIn(good, offered,
                      "An available unit of the right spec must be offered.")
        self.assertNotIn(damaged, offered,
                         "A damaged cabin must not appear in selection at all.")
        self.assertNotIn(retired, offered,
                         "A retired cabin must not appear in selection at all.")

        # The flags that drive the hiding, asserted directly.
        self.assertTrue(damaged.strx_hidden_from_selection)
        self.assertFalse(damaged.strx_selectable)
        self.assertTrue(retired.strx_hidden_from_selection)
        self.assertFalse(retired.strx_selectable)
        self.assertFalse(good.strx_hidden_from_selection)
        self.assertTrue(good.strx_selectable)

    def test_05b_damaged_stays_hidden_after_state_churn(self):
        """The stored flags follow the state machine, not just the initial write."""
        lot = self._serial(self.cab53, 'SEL-5X3-CHURN')
        self.assertIn(lot, self._picker_lots(self.cab53))

        lot._strx_set_readiness('damaged', reason='Damaged on return')
        self.assertNotIn(lot, self._picker_lots(self.cab53),
                         "Damaging a unit must remove it from the picker.")

        # Repair path: damaged -> in_maintenance -> available (not a POST_RETURN
        # state, so the inspection/cleaning gate does not apply here).
        # Crossing from tier 1 into tier 2 makes the unit REAPPEAR — visible so a
        # planner can see it is being worked on — while staying uncommittable.
        lot._strx_set_readiness('in_maintenance', reason='Repair')
        self.assertIn(lot, self._picker_lots(self.cab53),
                      "An in-maintenance unit is visible again, unlike a damaged one.")
        self.assertFalse(lot.strx_selectable, "...but still not committable.")

        lot._strx_set_readiness('available', reason='Repaired')
        self.assertIn(lot, self._picker_lots(self.cab53),
                      "A repaired unit must come back into the picker.")
        self.assertTrue(lot.strx_selectable, "...and be committable again.")

    def test_05c_condition_damaged_is_hidden_from_selection(self):
        """Changing Condition to Damaged on the Lot form hides the serial too."""
        good = self._serial(self.cab53, 'SEL-5X3-COND-OK')
        damaged = self._serial(
            self.cab53, 'SEL-5X3-COND-DMG', condition='damaged')

        offered = self._picker_lots(self.cab53)

        self.assertIn(good, offered)
        self.assertNotIn(damaged, offered)
        self.assertTrue(damaged.strx_hidden_from_selection)
        self.assertFalse(damaged.strx_selectable)

        with self.assertRaises(ValidationError):
            self.env['strx.cabin.allocation'].create({
                'order_line_id': self._order().order_line[0].id,
                'lot_id': damaged.id,
            })

    # ============================================================ ACCEPTANCE 6
    def _ar_label(self, lot, state):
        """The Arabic label a selection widget renders for `state`."""
        lot_ar = lot.with_context(lang='ar_001')
        field = lot_ar._fields['strx_readiness_state']
        return dict(field._description_selection(lot_ar.env))[state]

    def test_06_on_rent_and_maintenance_not_selectable_but_not_hidden(self):
        """On-rent / in-maintenance sit in their own tier: shown, never offered.

        They must NOT be selectable, but must also NOT be hidden the way damaged
        units are — that distinction is the whole point of the client's
        three-tier selection rule.
        """
        on_rent = self._serial(self.cab53, 'SEL-5X3-RENT', state='on_rent')
        maint = self._serial(self.cab53, 'SEL-5X3-MAINT', state='in_maintenance')
        damaged = self._serial(self.cab53, 'SEL-5X3-DMG6', state='damaged')
        available = self._serial(self.cab53, 'SEL-5X3-OK6')

        # Not offerable to a new rental.
        self.assertFalse(on_rent.strx_selectable)
        self.assertFalse(maint.strx_selectable)

        # ...but not suppressed either — this is what separates them from damaged.
        self.assertFalse(on_rent.strx_hidden_from_selection)
        self.assertFalse(maint.strx_hidden_from_selection)
        self.assertTrue(damaged.strx_hidden_from_selection)

        # Colour coding: green available, red on rent, amber in maintenance.
        self.assertEqual(available.strx_state_color, 10)
        self.assertEqual(on_rent.strx_state_color, 1)
        self.assertEqual(maint.strx_state_color, 3)

    def test_06b_arabic_labels_and_rtl(self):
        """The two unselectable states carry their Arabic labels, in an RTL language."""
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module'].search([
            ('name', '=', 'strx_cabin_base'), ('state', '=', 'installed'),
        ])._update_translations(['ar_001'])

        lang = self.env['res.lang'].with_context(active_test=False).search(
            [('code', '=', 'ar_001')], limit=1)
        self.assertTrue(lang.active, "Arabic must be an installed language.")
        self.assertEqual(lang.direction, 'rtl', "Arabic must render right-to-left.")

        lot = self._serial(self.cab53, 'SEL-5X3-AR', state='on_rent')
        self.assertEqual(self._ar_label(lot, 'on_rent'), 'مؤجرة')
        self.assertEqual(self._ar_label(lot, 'in_maintenance'), 'تحت الصيانة')

    def test_06b2_rented_label_only_for_on_rent(self):
        """The Arabic rented label must not leak onto allocated/reserved units."""
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module'].search([
            ('name', '=', 'strx_cabin_base'), ('state', '=', 'installed'),
        ])._update_translations(['ar_001'])

        on_rent = self._serial(self.cab53, 'LABEL-ON-RENT', state='on_rent')
        allocated = self._serial(self.cab53, 'LABEL-ALLOC', state='allocated')
        reserved = self._serial(self.cab53, 'LABEL-RESERVED', state='reserved')
        damaged = self._serial(self.cab53, 'LABEL-DAMAGED', condition='damaged')

        self.assertIn(
            'مؤجرة',
            on_rent.with_context(lang='ar_001', strx_selection_label=1).display_name)
        self.assertNotIn(
            'مؤجرة',
            allocated.with_context(lang='ar_001', strx_selection_label=1).display_name)
        self.assertNotIn(
            'مؤجرة',
            reserved.with_context(lang='ar_001', strx_selection_label=1).display_name)

        offered = self._picker_lots(self.cab53)
        self.assertIn(on_rent, offered)
        self.assertNotIn(allocated, offered)
        self.assertNotIn(reserved, offered)
        self.assertNotIn(damaged, offered)

    def test_06c_visible_not_selectable_tier(self):
        """The client's three-tier selection rule, end to end.

        Tier 1 damaged/retired  -> absent from the picker entirely
        Tier 2 on-rent/maint    -> present, greyed, but NOT committable
        Tier 3 available        -> present and committable

        Tier 2 is the one that needs both halves proved: appearing in the picker
        is a UI affordance, so the test also forces a commit past the UI and
        requires the model to refuse it.
        """
        available = self._serial(self.cab53, 'TIER-OK')
        on_rent = self._serial(self.cab53, 'TIER-RENT', state='on_rent')
        maint = self._serial(self.cab53, 'TIER-MAINT', state='in_maintenance')
        damaged = self._serial(self.cab53, 'TIER-DMG', state='damaged')
        retired = self._serial(self.cab53, 'TIER-RET', state='retired')

        offered = self._picker_lots(self.cab53)

        # Tier 1 — hidden entirely.
        self.assertNotIn(damaged, offered)
        self.assertNotIn(retired, offered)

        # Tier 2 — visible, not selectable.
        self.assertIn(on_rent, offered,
                      "On-rent units must stay visible in the picker.")
        self.assertIn(maint, offered,
                      "In-maintenance units must stay visible in the picker.")
        self.assertFalse(on_rent.strx_selectable)
        self.assertFalse(maint.strx_selectable)

        # Tier 3 — visible and selectable.
        self.assertIn(available, offered)
        self.assertTrue(available.strx_selectable)

    def test_06d_guard_blocks_forced_allocation_of_visible_unit(self):
        """The tier-2 refusal is server-side, not a UI decoration.

        Both mutation paths are forced directly against the model, the way an
        import or an RPC client would.
        """
        available = self._serial(self.cab53, 'TIER-G-OK')
        on_rent = self._serial(self.cab53, 'TIER-G-RENT', state='on_rent')
        maint = self._serial(self.cab53, 'TIER-G-MAINT', state='in_maintenance')

        # create() — committing a visible-but-unavailable unit is refused.
        with self.assertRaises(ValidationError):
            self.env['strx.cabin.allocation'].create({
                'order_line_id': self._order().order_line[0].id,
                'lot_id': on_rent.id})

        # write() — re-pointing an existing allocation onto one is refused too.
        alloc = self.env['strx.cabin.allocation'].create({
            'order_line_id': self._order().order_line[0].id,
            'lot_id': available.id})
        with self.assertRaises(ValidationError):
            alloc.write({'lot_id': maint.id})
        self.assertEqual(alloc.lot_id, available, "The commitment must not move.")

    def test_06f_onchange_clears_visible_unselectable_serial(self):
        """The UI rejects a visible planning-only row immediately."""
        on_rent = self._serial(self.cab53, 'TIER-UI-RENT', state='on_rent')
        maint = self._serial(self.cab53, 'TIER-UI-MAINT', state='in_maintenance')
        offered = self._picker_lots(self.cab53)
        self.assertIn(on_rent, offered)
        self.assertIn(maint, offered)

        alloc = self.env['strx.cabin.allocation'].new({
            'order_line_id': self._order().order_line[0].id,
            'lot_id': on_rent.id,
        })
        warning = alloc._onchange_lot_id()

        self.assertFalse(alloc.lot_id)
        self.assertIn('warning', warning)

    def test_06e_translated_label_is_scoped_to_the_picker(self):
        """The picker follows the user language without changing other screens."""
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module'].search([
            ('name', 'in', ['strx_cabin_base', 'strx_cabin_allocation']),
            ('state', '=', 'installed'),
        ])._update_translations(['ar_001'])

        on_rent = self._serial(self.cab53, 'TIER-AR', state='on_rent')
        maint = self._serial(self.cab53, 'TIER-AR-M', state='in_maintenance')
        available = self._serial(self.cab53, 'TIER-AR-OK')

        # English users see English only.
        picker_en = on_rent.with_context(
            lang='en_US', strx_selection_label=1).display_name
        self.assertIn('On Rent', picker_en)
        self.assertNotIn('مؤجرة', picker_en)

        # Arabic users see Arabic only.
        picker_ar = on_rent.with_context(
            lang='ar_001', strx_selection_label=1).display_name
        self.assertIn('مؤجرة', picker_ar)
        self.assertNotIn('On Rent', picker_ar)
        self.assertEqual(
            maint.with_context(lang='ar_001').strx_state_label, 'تحت الصيانة')

        # The suffix remains limited to the picker.
        self.assertNotIn('مؤجرة', on_rent.with_context(lang='ar_001').display_name)
        self.assertEqual(on_rent.display_name, 'TIER-AR')

        # Selection pickers show the state for every visible cabin serial.
        self.assertEqual(
            available.with_context(
                lang='ar_001', strx_selection_label=1).display_name,
            'TIER-AR-OK [متاحة]')
