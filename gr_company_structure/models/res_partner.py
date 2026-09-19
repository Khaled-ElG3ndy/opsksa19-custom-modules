from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # Odoo 19 merged mobile into phone, but the approved company profiles have
    # distinct values for both.  The migrated database already contains the
    # legacy column; declaring it again makes the value supported and visible.
    mobile = fields.Char(string="Mobile")
