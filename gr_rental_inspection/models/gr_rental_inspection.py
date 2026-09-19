# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class GrRentalInspection(models.Model):
    """One inspection event, mirroring ABSAL's Unified Delivery/Return/
    Replacement Note. Delivery inspections gate dispatch; return inspections
    gate closing (release back to Available)."""
    _name = 'gr.rental.inspection'
    _description = 'Rental Inspection (Delivery / Return / Replacement)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(
        string='Inspection Ref', required=True, copy=False, tracking=True,
        default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    mode = fields.Selection([
        ('delivery', 'Delivery'),
        ('return', 'Return'),
        ('replacement', 'Replacement'),
    ], string='Mode', required=True, default='delivery', tracking=True, index=True)

    rental_order_id = fields.Many2one(
        'gr.rental.order', string='Rental Order', required=True, index=True,
        ondelete='cascade', tracking=True)
    asset_id = fields.Many2one(
        'gr.generator.asset', string='Equipment (Asset No)',
        related='rental_order_id.asset_id', store=True, readonly=True)
    partner_id = fields.Many2one(
        'res.partner', related='rental_order_id.partner_id', store=True,
        readonly=True, string='Customer')

    inspection_date = fields.Datetime(
        string='Inspection Date', default=fields.Datetime.now)
    current_hours = fields.Float(
        string='Current Hours',
        help="Running-hours reading at this inspection. Captured at delivery "
             "and at return; feeds the hours-based PM trigger.")

    checklist_ids = fields.One2many(
        'gr.rental.inspection.line', 'inspection_id', string='Machine Condition')

    inspected_by_id = fields.Many2one(
        'res.users', string='Inspected By', default=lambda self: self.env.user)
    customer_ack_name = fields.Char(string='Customer Acknowledged (name)')
    remarks = fields.Text(string='Remarks')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('passed', 'Passed'),
        ('failed', 'Failed'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        "The inspection reference must be unique per company.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'gr.rental.inspection') or _('New')
        return super().create(vals_list)

    def _populate_default_checklist(self):
        """Fill the standard ABSAL machine-condition checklist if empty."""
        Item = self.env['gr.rental.checklist.item']
        for insp in self:
            if not insp.checklist_ids:
                items = Item.search([], order='sequence, id')
                insp.checklist_ids = [(0, 0, {
                    'name': it.name, 'sequence': it.sequence})
                    for it in items]

    @api.onchange('rental_order_id')
    def _onchange_order(self):
        if self.rental_order_id and not self.current_hours:
            self.current_hours = self.rental_order_id.asset_id.current_hour_meter

    # ------------------------------------------------------------------
    def action_pass(self):
        for insp in self:
            if insp.state != 'draft':
                raise UserError(_("Only draft inspections can be passed."))
            # any failed checklist item blocks a pass
            failed = insp.checklist_ids.filtered(lambda l: l.result == 'fail')
            if failed:
                raise UserError(_(
                    "Inspection %s has failed checklist items: %s. Resolve them "
                    "or mark the inspection Failed.")
                    % (insp.name, ', '.join(failed.mapped('name'))))
            insp.state = 'passed'
        return True

    def action_fail(self):
        for insp in self:
            if insp.state not in ('draft', 'passed'):
                raise UserError(_("Only draft/passed inspections can be failed."))
            insp.state = 'failed'
        return True

    def action_reset(self):
        for insp in self:
            insp.state = 'draft'
        return True


class GrRentalInspectionLine(models.Model):
    _name = 'gr.rental.inspection.line'
    _description = 'Rental Inspection Checklist Line'
    _order = 'inspection_id, sequence, id'

    inspection_id = fields.Many2one(
        'gr.rental.inspection', string='Inspection', required=True,
        ondelete='cascade', index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Check Item', required=True)
    result = fields.Selection([
        ('ok', 'OK'),
        ('fail', 'Fail'),
        ('na', 'N/A'),
    ], string='Result', default='ok')
    note = fields.Char(string='Note')


class GrRentalChecklistItem(models.Model):
    """The reusable master list of machine-condition check items (ABSAL's form)."""
    _name = 'gr.rental.checklist.item'
    _description = 'Rental Inspection Checklist Item (master)'
    _order = 'sequence, id'

    name = fields.Char(string='Check Item', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
