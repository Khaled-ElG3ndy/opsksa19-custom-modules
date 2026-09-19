from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    mobile = fields.Char(related="partner_id.mobile", readonly=False)
