# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class GrGeneratorAssetMeterCorrectionWizard(models.TransientModel):
    _name = 'gr.generator.asset.meter.correction.wizard'
    _description = 'Generator Asset Meter Correction Wizard'

    asset_id = fields.Many2one(
        'gr.generator.asset', string='Asset', required=True, readonly=True)
    old_meter = fields.Float(
        string='Current Meter (old)', related='asset_id.current_hour_meter',
        readonly=True)
    last_verified_hour_meter = fields.Float(
        related='asset_id.last_verified_hour_meter', readonly=True)
    new_meter = fields.Float(string='Corrected Meter', required=True)
    is_decrease = fields.Boolean(
        string='Is a Decrease', compute='_compute_is_decrease')
    reason = fields.Text(string='Reason', required=True)

    @api.depends('new_meter', 'old_meter')
    def _compute_is_decrease(self):
        for wiz in self:
            wiz.is_decrease = wiz.new_meter < wiz.old_meter

    @api.constrains('new_meter')
    def _check_new_meter_non_negative(self):
        for wiz in self:
            if wiz.new_meter < 0:
                raise ValidationError(_("Corrected meter cannot be negative."))

    def _user_can_correct(self):
        """Any correction requires Maintenance Manager or Administrator."""
        return (
            self.env.user.has_group('gr_security_base.group_generator_maint_manager')
            or self.env.user.has_group('gr_security_base.group_generator_administrator')
        )

    def _user_can_decrease(self):
        """A decrease requires the higher Administrator approval group."""
        return self.env.user.has_group('gr_security_base.group_generator_administrator')

    def action_apply(self):
        self.ensure_one()
        if not self._user_can_correct():
            raise UserError(_(
                "Only a Maintenance Manager or Administrator may correct a "
                "generator meter."))

        if self.is_decrease and not self._user_can_decrease():
            raise UserError(_(
                "Decreasing a meter reading requires Generator Administrator "
                "approval. Please ask an administrator to apply this correction."))

        asset = self.asset_id
        old_value = asset.current_hour_meter

        # Apply with the bypass flag so the write() rollback guard allows it,
        # and record the verification stamp.
        asset.with_context(gr_meter_correction=True).write({
            'current_hour_meter': self.new_meter,
            'last_verified_hour_meter': self.new_meter,
            'last_verified_date': fields.Datetime.now(),
            'last_verified_by': self.env.user.id,
        })

        # Permanent audit trail in chatter. message_type='comment' with the
        # mail.mt_note subtype logs a note without triggering an outgoing email,
        # so it never depends on outgoing-mail configuration.
        asset.message_post(
            body=_(
                "<b>Meter correction applied.</b><br/>"
                "Old reading: %(old)s h<br/>"
                "New reading: %(new)s h<br/>"
                "By: %(user)s<br/>"
                "Reason: %(reason)s",
                old=old_value, new=self.new_meter,
                user=self.env.user.display_name, reason=self.reason or _('(none)'),
            ),
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
        return {'type': 'ir.actions.act_window_close'}
