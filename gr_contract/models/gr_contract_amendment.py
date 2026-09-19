# -*- coding: utf-8 -*-
import json
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class GrContractAmendment(models.Model):
    _name = 'gr.contract.amendment'
    _description = 'Generator Contract Amendment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Amendment Reference', required=True, copy=False,
        default=lambda self: _('New'))
    contract_id = fields.Many2one(
        'gr.rental.contract', string='Contract', required=True,
        ondelete='cascade', index=True, tracking=True)
    company_id = fields.Many2one(
        related='contract_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(
        related='contract_id.currency_id', store=True, string='Currency')

    requested_by = fields.Many2one(
        'res.users', string='Requested By', default=lambda self: self.env.user)
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True)
    request_date = fields.Datetime(string='Request Date', default=fields.Datetime.now)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)
    reason = fields.Text(string='Reason', required=True)

    # Proposed new commercial values. Only the fields the user fills are applied.
    new_included_hours_per_day = fields.Float(string='New Included Hours / Day')
    new_max_hours_per_day = fields.Float(string='New Max Hours / Day')
    new_base_daily_rate = fields.Monetary(string='New Base Daily Rate', currency_field='currency_id')
    new_base_monthly_rate = fields.Monetary(string='New Base Monthly Rate', currency_field='currency_id')
    new_hourly_rate = fields.Monetary(string='New Hourly Rate', currency_field='currency_id')
    new_overtime_hour_rate = fields.Monetary(string='New Overtime Hour Rate', currency_field='currency_id')
    new_violation_hour_rate = fields.Monetary(string='New Violation Hour Rate', currency_field='currency_id')

    # Audit snapshots.
    old_values_json = fields.Text(string='Old Values (JSON)', readonly=True)
    new_values_json = fields.Text(string='New Values (JSON)', readonly=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('applied', 'Applied'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)

    # Map amendment field -> contract field for the ones that are set (non-zero).
    _FIELD_MAP = {
        'new_included_hours_per_day': 'included_hours_per_day',
        'new_max_hours_per_day': 'max_hours_per_day',
        'new_base_daily_rate': 'base_daily_rate',
        'new_base_monthly_rate': 'base_monthly_rate',
        'new_hourly_rate': 'hourly_rate',
        'new_overtime_hour_rate': 'overtime_hour_rate',
        'new_violation_hour_rate': 'violation_hour_rate',
    }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                seq = self.env['ir.sequence'].next_by_code('gr.contract.amendment')
                vals['name'] = seq or _('New')
        return super().create(vals_list)

    def _collect_changes(self):
        """Return {contract_field: new_value} for amendment fields the user set."""
        self.ensure_one()
        changes = {}
        for amend_field, contract_field in self._FIELD_MAP.items():
            value = self[amend_field]
            if value:  # only apply fields the user actually filled
                changes[contract_field] = value
        return changes

    def action_submit(self):
        for a in self:
            if a.state != 'draft':
                raise UserError(_("Only draft amendments can be submitted."))
            a.state = 'submitted'
        return True

    def action_reject(self):
        for a in self:
            if a.state != 'submitted':
                raise UserError(_("Only submitted amendments can be rejected."))
            a.state = 'rejected'
        return True

    def action_approve(self):
        if not (self.env.user.has_group('gr_security_base.group_generator_general_manager')
                or self.env.user.has_group('gr_security_base.group_generator_administrator')):
            raise UserError(_("Only a General Manager or Administrator may approve amendments."))
        for a in self:
            if a.state != 'submitted':
                raise UserError(_("Only submitted amendments can be approved."))
            a.approved_by = self.env.user.id
            a.approval_date = fields.Datetime.now()
            a.state = 'approved'
        return True

    def action_apply(self):
        for a in self:
            if a.state != 'approved':
                raise UserError(_("Only approved amendments can be applied."))
            contract = a.contract_id
            changes = a._collect_changes()
            if not changes:
                raise UserError(_("This amendment does not set any new values."))

            # Snapshot old values for audit.
            old_values = {f: contract[f] for f in changes}
            a.old_values_json = json.dumps(old_values, default=str)
            a.new_values_json = json.dumps(changes, default=str)

            # Apply with the bypass flag so the contract's approval-lock allows it.
            contract.with_context(gr_amendment_apply=True).write(changes)

            a.state = 'applied'
            contract.message_post(
                body=_("Amendment %(ref)s applied. Changes: %(changes)s",
                       ref=a.name, changes=changes),
                message_type='comment', subtype_xmlid='mail.mt_note')
        return True
