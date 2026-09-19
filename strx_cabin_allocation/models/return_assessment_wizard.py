# -*- coding: utf-8 -*-
from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.strx_cabin_base.models.constants import CABIN_CONDITIONS


RETURN_ASSESSMENT_STATES = [
    ('available', 'Available'),
    ('in_inspection', 'In Inspection'),
    ('in_cleaning', 'In Cleaning'),
    ('in_maintenance', 'In Maintenance'),
    ('damaged', 'Damaged'),
    ('retired', 'Retired'),
]

RETURN_WORKFLOW_STATES = {'returned', 'in_inspection', 'in_cleaning'}


class StrxCabinReturnAssessmentWizard(models.TransientModel):
    _name = 'strx.cabin.return.assessment.wizard'
    _description = 'Returned Cabin Assessment'

    allocation_id = fields.Many2one(
        'strx.cabin.allocation', string='Allocation', required=True,
        readonly=True, ondelete='cascade')
    order_id = fields.Many2one(
        'sale.order', string='Rental Order', related='allocation_id.order_id',
        readonly=True)
    partner_id = fields.Many2one(
        'res.partner', string='Customer', related='allocation_id.partner_id',
        readonly=True)
    line_ids = fields.One2many(
        'strx.cabin.return.assessment.wizard.line', 'wizard_id',
        string='Returned Cabins')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        allocation_id = (
            values.get('allocation_id')
            or self.env.context.get('default_allocation_id')
            or self.env.context.get('active_id')
        )
        allocation = self.env['strx.cabin.allocation'].browse(
            allocation_id).exists()
        if not allocation:
            return values
        allocation._strx_validate_return_assessment_start()
        values['allocation_id'] = allocation.id
        if 'line_ids' in fields_list:
            values['line_ids'] = [
                (0, 0, {
                    'lot_id': lot.id,
                    'target_state': (
                        'damaged' if lot.strx_condition == 'damaged'
                        else lot.strx_readiness_state
                        if lot.strx_readiness_state in {
                            'in_inspection', 'in_cleaning'}
                        else 'in_inspection'
                    ),
                    'condition': lot.strx_condition or 'good',
                })
                for lot in allocation.lot_ids.sorted('name')
            ]
        return values

    def action_confirm_assessment(self):
        self.ensure_one()
        allocation = self.allocation_id.exists()
        allocation._strx_validate_return_assessment_start()

        expected_lots = set(allocation.lot_ids.ids)
        assessed_lots = set(self.line_ids.mapped('lot_id').ids)
        if not self.line_ids or assessed_lots != expected_lots \
                or len(self.line_ids) != len(expected_lots):
            raise UserError(_(
                "Every returned cabin in this allocation must be assessed exactly "
                "once before saving."))

        changed_elsewhere = self.line_ids.filtered(
            lambda line: line.lot_id.strx_readiness_state
            not in RETURN_WORKFLOW_STATES)[:1]
        if changed_elsewhere:
            raise UserError(_(
                "Cabin %(serial)s is now %(state)s. Close this window and reopen "
                "the assessment to use its latest status.",
                serial=changed_elsewhere.lot_id.name,
                state=changed_elsewhere.lot_id.strx_state_label
                    or changed_elsewhere.lot_id.strx_readiness_state,
            ))

        for line in self.line_ids.sorted(lambda item: item.lot_id.name or ''):
            if line.target_state == 'available' \
                    and line.condition == 'damaged':
                raise ValidationError(_(
                    "Cabin %(serial)s cannot be Available while its physical "
                    "condition is Damaged.", serial=line.lot_id.name))
            if line.target_state == 'damaged' \
                    and line.condition != 'damaged':
                raise ValidationError(_(
                    "Set cabin %(serial)s condition to Damaged when choosing the "
                    "Damaged operational status.", serial=line.lot_id.name))

        # Validate the complete assessment before mutating any cabin, so even RPC
        # integrations that call this method inside a wider transaction get an
        # all-or-nothing result.
        assessment_date = fields.Date.context_today(self)
        reason = _(
            "Return assessment for allocation %(ref)s", ref=allocation.name)
        for line in self.line_ids.sorted(lambda item: item.lot_id.name or ''):
            target_state = line.target_state
            inspection_passed = target_state in {'available', 'in_cleaning'}
            cleaning_passed = target_state == 'available'
            lot_values = {
                'strx_condition': line.condition,
                'strx_inspection_passed': inspection_passed,
                'strx_cleaning_passed': cleaning_passed,
            }
            if target_state != 'in_inspection':
                lot_values['strx_last_inspection_date'] = assessment_date
            line.lot_id.write(lot_values)
            line.lot_id._strx_set_readiness(
                target_state, reason=reason, note=line.note)

        # ``available`` is the legacy technical key for this terminal allocation
        # stage.  Its user-facing label is now "Assessed" because each cabin can
        # leave the return in a different operational state.
        allocation.write({'state': 'available'})
        allocation.message_post(
            body=self._strx_assessment_chatter_body(),
            subtype_xmlid='mail.mt_note',
        )

        ready_count = len(self.line_ids.filtered(
            lambda line: line.target_state == 'available'))
        follow_up_count = len(self.line_ids) - ready_count
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Return Assessment Saved'),
                'message': _(
                    "Assessment saved: %(ready)s ready, %(follow_up)s routed for "
                    "follow-up.",
                    ready=ready_count, follow_up=follow_up_count),
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            },
        }

    def _strx_assessment_chatter_body(self):
        self.ensure_one()
        state_labels = dict(
            self.line_ids._fields['target_state']._description_selection(self.env))
        condition_labels = dict(
            self.line_ids._fields['condition']._description_selection(self.env))
        items = []
        for line in self.line_ids.sorted(lambda item: item.lot_id.name or ''):
            details = _(
                "%(serial)s — %(state)s (Condition: %(condition)s)",
                serial=line.lot_id.name,
                state=state_labels.get(line.target_state, line.target_state),
                condition=condition_labels.get(line.condition, line.condition),
            )
            if line.note:
                details = _(
                    "%(details)s — Note: %(note)s",
                    details=details, note=line.note)
            items.append(Markup('<li>%s</li>') % escape(details))
        return Markup('<p>%s</p><ul>%s</ul>') % (
            escape(_('Returned cabin assessment completed:')),
            Markup('').join(items),
        )


class StrxCabinReturnAssessmentWizardLine(models.TransientModel):
    _name = 'strx.cabin.return.assessment.wizard.line'
    _description = 'Returned Cabin Assessment Line'
    _order = 'lot_id'

    wizard_id = fields.Many2one(
        'strx.cabin.return.assessment.wizard', required=True,
        ondelete='cascade')
    lot_id = fields.Many2one(
        'stock.lot', string='Cabin Serial', required=True, readonly=True)
    product_id = fields.Many2one(
        'product.product', string='Specification', related='lot_id.product_id',
        readonly=True)
    current_state = fields.Selection(
        related='lot_id.strx_readiness_state', string='Current Status',
        readonly=True)
    condition = fields.Selection(
        selection=CABIN_CONDITIONS, string='Physical Condition', required=True,
        default='good')
    target_state = fields.Selection(
        selection=RETURN_ASSESSMENT_STATES, string='Next Operational Status',
        required=True, default='in_inspection')
    note = fields.Char(
        string='Assessment Note',
        help="Optional observation recorded in this cabin's readiness history.")

    _sql_constraints = [
        (
            'return_assessment_lot_unique',
            'unique(wizard_id, lot_id)',
            'Each returned cabin can only be assessed once.',
        ),
    ]

    @api.onchange('target_state')
    def _onchange_target_state(self):
        for line in self:
            if line.target_state == 'damaged':
                line.condition = 'damaged'
            elif line.target_state == 'available' \
                    and line.condition == 'damaged':
                line.condition = 'fair'
