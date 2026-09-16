from odoo import models, fields


class ResCompany(models.Model):
    _inherit = "res.company"

    header_img = fields.Binary("Full Header Image")
    footer_img = fields.Binary("Full Footer Image")


class BaseDocumentLayout(models.TransientModel):
    _inherit = 'base.document.layout'

    header_img = fields.Binary(related='company_id.header_img', string='Header Image', readonly=False)
    footer_img = fields.Binary(related='company_id.footer_img', string='Footer Image', readonly=False)
