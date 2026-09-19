# -*- coding: utf-8 -*-
from odoo import fields, models


class GrMaintenanceTemplate(models.Model):
    _name = 'gr.maintenance.template'
    _description = 'Generator PM Template'
    _order = 'name'

    name = fields.Char(string='Template Name', required=True)
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company)
    job_type = fields.Selection([
        ('preventive', 'Preventive'),
        ('corrective', 'Corrective'),
        ('breakdown', 'Breakdown'),
    ], string='Default Job Type', default='preventive', required=True)
    default_interval_hours = fields.Float(string='Default PM Interval (hours)')
    default_interval_days = fields.Integer(string='Default PM Interval (days)')
    description = fields.Text(string='Description')
    checklist_line_ids = fields.One2many(
        'gr.maintenance.template.line', 'template_id', string='Checklist Items')
    active = fields.Boolean(default=True)


class GrMaintenanceTemplateLine(models.Model):
    _name = 'gr.maintenance.template.line'
    _description = 'Generator PM Template Checklist Item'
    _order = 'template_id, sequence, id'

    template_id = fields.Many2one(
        'gr.maintenance.template', string='Template', required=True,
        ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Check Item', required=True)
    note = fields.Char(string='Note')
