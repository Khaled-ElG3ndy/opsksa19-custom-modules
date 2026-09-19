# -*- coding: utf-8 -*-
from io import BytesIO
from os.path import exists

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from odoo import _, models
from odoo.tools.misc import file_path


_UNIFIED_REPORTS = {
    'gr_customer_approval.report_approval_rental_agreement',
    'gr_customer_approval.report_approval_delivery',
    'gr_customer_approval.report_approval_visit',
    'gr_customer_approval.report_approval_return',
    'gr_contract.report_gr_rental_contract',
    'gr_rental_order.report_gr_delivery_note',
    'gr_rental_order.report_gr_install_report',
    'gr_rental_order.report_gr_return_inspection',
}


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        pdf, report_type = super()._render_qweb_pdf(
            report_ref, res_ids=res_ids, data=data)
        report = self._get_report(report_ref)
        if report.report_name in _UNIFIED_REPORTS and pdf and res_ids:
            pdf = self._gr_stamp_document_footer(pdf, report, res_ids)
        return pdf, report_type

    def _gr_stamp_document_footer(self, pdf, report, res_ids):
        records = self.env[report.model].browse(res_ids).exists()
        if not records:
            return pdf
        record = records[0]
        lang = self.env.context.get('lang') or record.env.lang or 'en_US'
        version = 1
        approval_document_id = self.env.context.get('approval_document_id')
        if approval_document_id:
            approval_document = self.env['gr.customer.approval.document'].sudo().browse(
                approval_document_id).exists()
            if approval_document:
                version = approval_document.version

        localized = self.with_context(lang=lang)
        version_text = localized._gr_footer_version_text(version)
        controlled_text = localized._gr_footer_controlled_text()
        company = (
            record.company_id.name
            if 'company_id' in record._fields else self.env.company.name
        )
        reference = record.display_name or str(record.id)

        reader = PdfReader(BytesIO(pdf))
        writer = PdfWriter()
        total_pages = len(reader.pages)
        for page_number, page in enumerate(reader.pages, 1):
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            page_text = localized._gr_footer_page_text(page_number, total_pages)
            footer_image = localized._gr_footer_image(
                width, company, reference, version_text, controlled_text,
                page_text, lang)
            overlay = localized._gr_footer_overlay(width, height, footer_image)
            page.merge_page(overlay)
            writer.add_page(page)

        metadata = {
            str(key): str(value)
            for key, value in (reader.metadata or {}).items()
            if value is not None
        }
        metadata['/GRFooterStamped'] = 'true'
        writer.add_metadata(metadata)
        result = BytesIO()
        writer.write(result)
        return result.getvalue()

    def _gr_footer_controlled_text(self):
        return _('Controlled version stored in the system')

    def _gr_footer_version_text(self, version):
        return _('Version %(version)s', version=version)

    def _gr_footer_page_text(self, page, total):
        return _('Page %(page)s / %(total)s', page=page, total=total)

    def _gr_footer_font(self, rtl, size):
        path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        if not exists(path):
            # Odoo 19 removed get_resource_path; tools.misc.file_path is the
            # supported way to resolve a file inside an addon.
            path = file_path(
                'gr_customer_approval/static/src/fonts/'
                'NotoSansArabic-Regular.ttf')
        return ImageFont.truetype(path, size=size)

    def _gr_fit_footer_font(self, draw, text, rtl, max_width, initial_size):
        direction = 'rtl' if rtl else 'ltr'
        for size in range(initial_size, 14, -1):
            font = self._gr_footer_font(rtl, size)
            bounds = draw.textbbox(
                (0, 0), text, font=font, direction=direction,
                language='ar' if rtl else 'en')
            if bounds[2] - bounds[0] <= max_width:
                return font
        return self._gr_footer_font(rtl, 15)

    def _gr_footer_image(self, page_width, company, reference, version_text,
                         controlled_text, page_text, lang):
        rtl = self.env['res.lang']._get_data(code=lang or '').direction == 'rtl'
        scale = 2
        width = max(int((page_width - 44) * scale), 600)
        height = 58
        image = Image.new('RGB', (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        line_color = (174, 185, 188)
        text_color = (84, 105, 112)
        draw.line((0, 3, width, 3), fill=line_color, width=2)

        if rtl:
            metadata = '%s | %s | %s | %s' % (
                controlled_text, version_text, reference, company)
            metadata_font = self._gr_fit_footer_font(
                draw, metadata, True, width * 0.74, 16)
            page_font = self._gr_footer_font(True, 15)
            draw.text(
                (width - 4, 13), metadata, font=metadata_font,
                fill=text_color, anchor='ra', direction='rtl', language='ar')
            draw.text(
                (4, 13), page_text, font=page_font,
                fill=text_color, anchor='la', direction='rtl', language='ar')
        else:
            metadata = '%s | %s | %s | %s' % (
                company, reference, version_text, controlled_text)
            metadata_font = self._gr_fit_footer_font(
                draw, metadata, False, width * 0.78, 15)
            page_font = self._gr_footer_font(False, 14)
            draw.text(
                (4, 13), metadata, font=metadata_font,
                fill=text_color, anchor='la', direction='ltr', language='en')
            draw.text(
                (width - 4, 13), page_text, font=page_font,
                fill=text_color, anchor='ra', direction='ltr', language='en')
        return image

    def _gr_footer_overlay(self, page_width, page_height, footer_image):
        packet = BytesIO()
        footer_height = 26
        pdf_canvas = canvas.Canvas(packet, pagesize=(page_width, page_height))
        pdf_canvas.drawImage(
            ImageReader(footer_image), 22, 7,
            width=page_width - 44, height=footer_height,
            preserveAspectRatio=False)
        pdf_canvas.save()
        packet.seek(0)
        return PdfReader(packet).pages[0]
