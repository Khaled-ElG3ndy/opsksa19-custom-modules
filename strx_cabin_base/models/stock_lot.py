# -*- coding: utf-8 -*-
import base64
import io
from html import escape

import qrcode
from qrcode.constants import ERROR_CORRECT_Q

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.misc import format_date
from markupsafe import Markup

from .constants import (
    READINESS_STATES,
    CABIN_CONDITIONS,
    HIDDEN_FROM_SELECTION,
    VISIBLE_NOT_SELECTABLE,
    SELECTABLE_STATES,
    POST_RETURN_STATES,
)


class StockLot(models.Model):
    """A physical cabin = one serial-tracked stock.lot.

    Adds the readiness state machine, condition/inspection data and an append-only
    history. The readiness state is EVENT-DRIVEN: readonly in the UI and mutated only
    through code. Every change (however it is made) is captured in the readiness log
    via the write() override below.
    """
    _inherit = 'stock.lot'

    _STRX_CODE128_PATTERNS = [
        '212222', '222122', '222221', '121223', '121322', '131222',
        '122213', '122312', '132212', '221213', '221312', '231212',
        '112232', '122132', '122231', '113222', '123122', '123221',
        '223211', '221132', '221231', '213212', '223112', '312131',
        '311222', '321122', '321221', '312212', '322112', '322211',
        '212123', '212321', '232121', '111323', '131123', '131321',
        '112313', '132113', '132311', '211313', '231113', '231311',
        '112133', '112331', '132131', '113123', '113321', '133121',
        '313121', '211331', '231131', '213113', '213311', '213131',
        '311123', '311321', '331121', '312113', '312311', '332111',
        '314111', '221411', '431111', '111224', '111422', '121124',
        '121421', '141122', '141221', '112214', '112412', '122114',
        '122411', '142112', '142211', '241211', '221114', '413111',
        '241112', '134111', '111242', '121142', '121241', '114212',
        '124112', '124211', '411212', '421112', '421211', '212141',
        '214121', '412121', '111143', '111341', '131141', '114113',
        '114311', '411113', '411311', '113141', '114131', '311141',
        '411131', '211412', '211214', '211232', '2331112',
    ]

    # Mirror of the product's cabin flag so views/domains can filter cheaply.
    strx_is_cabin = fields.Boolean(
        related='product_id.strx_is_cabin', store=True, readonly=True)
    strx_cabin_spec = fields.Char(
        related='product_id.strx_cabin_spec', string='Specification', readonly=True)

    strx_readiness_state = fields.Selection(
        selection=READINESS_STATES,
        string='Readiness',
        default='available',
        copy=False,
        index=True,
        tracking=True,
        readonly=True,  # event-driven, never typed by users
        help="Lifecycle state of this physical unit. Set by fulfillment events, "
             "never edited directly.")

    strx_condition = fields.Selection(
        selection=CABIN_CONDITIONS,
        string='Condition', default='good', tracking=True)

    strx_barcode = fields.Char(
        string='Barcode', copy=False, index=True,
        help="Physical scannable barcode printed on the cabin ID card. If left "
             "empty, it is generated from the serial number.")

    # Physical dimensions of THIS unit (default to the product's nominal size).
    strx_length_m = fields.Float(string='Length (m)', digits=(6, 2))
    strx_width_m = fields.Float(string='Width (m)', digits=(6, 2))

    strx_last_inspection_date = fields.Date(string='Last Inspection')
    strx_next_maintenance_date = fields.Date(string='Next Maintenance')

    # Return→Available gate. Both must pass before a returned unit is available again.
    strx_inspection_passed = fields.Boolean(string='Inspection Passed', copy=False)
    strx_cleaning_passed = fields.Boolean(string='Cleaning Passed', copy=False)

    strx_readiness_log_ids = fields.One2many(
        'strx.cabin.readiness.log', 'lot_id', string='Readiness History')
    strx_readiness_log_count = fields.Integer(
        compute='_compute_strx_readiness_log_count')

    # --- Selection-list helpers (client requirement) -------------------------
    # Stored + searchable: allocation domains filter on these
    # (e.g. [('strx_selectable', '=', True)]). Recomputed on every state change.
    strx_hidden_from_selection = fields.Boolean(
        compute='_compute_strx_selection_flags', store=True, compute_sudo=True,
        help="Damaged / Retired units are hidden entirely from selection lists.")
    strx_selectable = fields.Boolean(
        compute='_compute_strx_selection_flags', store=True, compute_sudo=True,
        help="Only Available units may be offered to a new rental.")

    # Display the readiness label in the current user's language. This helper is
    # deliberately scoped to selection pickers; ordinary screens already render the
    # translated Selection field directly.
    strx_state_label = fields.Char(
        string='Readiness Status',
        compute='_compute_strx_state_label',
        help="Readiness label rendered in the current user's language for selection "
             "pickers.")
    # Display-only, non-stored by design — deliberately on its OWN compute method.
    # Sharing one method with the two stored flags above made their 'store' and
    # 'compute_sudo' inconsistent, so merely reading the colour could trigger a
    # sudoed recompute-and-write of the searchable flags. Keep these split.
    strx_state_color = fields.Integer(
        compute='_compute_strx_state_color', compute_sudo=False,
        help="Colour index for selection widgets: green=available, red=on rent, "
             "amber=in maintenance.")
    strx_cabin_card_button_label = fields.Char(
        compute='_compute_strx_cabin_card_button_label',
        string='Cabin Card Button')

    def init(self):
        """Backfill existing cabin lots so every cabin has a scannable barcode."""
        self.env.cr.execute("""
            UPDATE stock_lot lot
               SET strx_barcode = lot.name
              FROM product_product product
              JOIN product_template template
                ON template.id = product.product_tmpl_id
             WHERE lot.product_id = product.id
               AND template.strx_is_cabin IS TRUE
               AND NULLIF(BTRIM(COALESCE(lot.strx_barcode, '')), '') IS NULL
               AND NULLIF(BTRIM(COALESCE(lot.name, '')), '') IS NOT NULL
        """)

    # ------------------------------------------------------------------ compute
    def _compute_strx_readiness_log_count(self):
        for lot in self:
            lot.strx_readiness_log_count = len(lot.strx_readiness_log_ids)

    @api.depends('strx_readiness_state', 'strx_condition')
    def _compute_strx_selection_flags(self):
        """Stored + searchable flags only (store=True, compute_sudo=True)."""
        for lot in self:
            state = lot.strx_readiness_state
            condition_damaged = lot.strx_condition == 'damaged'
            lot.strx_hidden_from_selection = (
                state in HIDDEN_FROM_SELECTION or condition_damaged)
            lot.strx_selectable = (
                state in SELECTABLE_STATES and not condition_damaged)

    @api.depends('strx_readiness_state')
    @api.depends_context('lang')
    def _compute_strx_state_label(self):
        """Render the selection label in the current user's language."""
        field = self._fields['strx_readiness_state']
        labels = dict(field._description_selection(self.env))
        for lot in self:
            state = lot.strx_readiness_state
            lot.strx_state_label = labels.get(state, state) if state else False

    @api.depends('strx_readiness_state')
    def _compute_strx_state_color(self):
        """Display-only colour index (non-stored, compute_sudo=False)."""
        for lot in self:
            state = lot.strx_readiness_state
            if state == 'available':
                lot.strx_state_color = 10          # green
            elif state == 'on_rent':
                lot.strx_state_color = 1            # red
            elif state == 'in_maintenance':
                lot.strx_state_color = 3            # amber
            else:
                lot.strx_state_color = 0            # default

    @api.depends_context('lang')
    def _compute_strx_cabin_card_button_label(self):
        label = _('Cabin Card')
        for lot in self:
            lot.strx_cabin_card_button_label = label

    # ------------------------------------------------------------ display name
    @api.depends('name', 'strx_readiness_state', 'strx_selectable', 'strx_is_cabin')
    @api.depends_context('strx_selection_label', 'lang')
    def _compute_display_name(self):
        """Suffix cabin serials with their translated state, in pickers only.

        Gated on the strx_selection_label context key so the suffix reaches the
        allocation/substitution serial pickers and nothing else — a serial that
        rendered with a status suffix on transfers, move lines and printed delivery
        notes would be noise, not control.
        """
        super()._compute_display_name()
        if not self.env.context.get('strx_selection_label'):
            return
        for lot in self:
            if lot.strx_is_cabin and lot.strx_state_label:
                lot.display_name = '%s [%s]' % (
                    lot.display_name, lot.strx_state_label)

    # -------------------------------------------------------------- identity
    @api.model
    def _strx_product_is_cabin(self, product_id):
        return bool(product_id and self.env['product.product'].browse(
            product_id).strx_is_cabin)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if self._strx_product_is_cabin(vals.get('product_id')) \
                    and not vals.get('strx_barcode') and vals.get('name'):
                vals['strx_barcode'] = vals['name']
        lots = super().create(vals_list)
        lots._strx_autofill_missing_barcodes()
        return lots

    def _strx_autofill_missing_barcodes(self):
        for lot in self.filtered(lambda l: l.strx_is_cabin and not l.strx_barcode and l.name):
            super(StockLot, lot).write({'strx_barcode': lot.name})

    @api.constrains('strx_barcode', 'strx_is_cabin')
    def _check_strx_cabin_barcode_unique(self):
        for lot in self:
            barcode = (lot.strx_barcode or '').strip()
            if not lot.strx_is_cabin or not barcode:
                continue
            if any(ord(char) < 32 or ord(char) > 126 for char in barcode):
                raise ValidationError(_(
                    "Cabin barcode %(barcode)s must contain printable English "
                    "letters, numbers, spaces or symbols only.",
                    barcode=barcode))
            duplicate = self.search([
                ('id', '!=', lot.id),
                ('strx_is_cabin', '=', True),
                ('strx_barcode', '=', barcode),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    "Cabin barcode %(barcode)s is already used by serial %(serial)s.",
                    barcode=barcode,
                    serial=duplicate.name))

    def action_strx_print_cabin_card(self):
        return self.action_strx_open_cabin_card_preview()

    def action_strx_open_cabin_card_preview(self):
        self.ensure_one()
        if not self.strx_is_cabin:
            raise ValidationError(_("Only cabin serials can have a Cabin ID Card."))
        self._strx_autofill_missing_barcodes()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cabin Card Preview'),
            'res_model': 'strx.cabin.id.card.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lot_id': self.id},
        }

    def action_strx_download_cabin_card(self):
        cabins = self.filtered('strx_is_cabin')
        if not cabins:
            raise ValidationError(_("Only cabin serials can have a Cabin ID Card."))
        cabins._strx_autofill_missing_barcodes()
        return self.env.ref(
            'strx_cabin_base.action_report_strx_cabin_id_card'
        ).with_context(discard_logo_check=True).report_action(cabins)

    def _strx_cabin_card_is_rtl(self):
        return self._strx_context_is_rtl()

    def _strx_context_is_rtl(self):
        code = self.env.context.get('lang') or self.env.user.lang or ''
        return self.env['res.lang']._get_data(code=code).direction == 'rtl'

    def _strx_cabin_card_format_dimensions(self):
        self.ensure_one()
        length = self.strx_length_m or self.product_id.strx_length_m or 0.0
        width = self.strx_width_m or self.product_id.strx_width_m or 0.0
        if not length and not width:
            return '—'
        return '%.2f × %.2f %s' % (length, width, _('m'))

    def _strx_cabin_card_format_registered_date(self):
        self.ensure_one()
        if not self.create_date:
            return '-'
        local_dt = fields.Datetime.context_timestamp(self, self.create_date)
        return format_date(self.env, local_dt.date())

    def strx_get_cabin_record_url(self):
        """Return the canonical authenticated Odoo URL for this cabin record."""
        self.ensure_one()
        base_url = (
            self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        ).strip().rstrip('/')
        if not base_url:
            raise ValidationError(_(
                "The system website URL is not configured. Set web.base.url before "
                "printing cabin QR cards."
            ))
        return '%s/odoo/lots/%s' % (base_url, self.id)

    def strx_get_cabin_qr_png_b64(self):
        """Generate a high-error-correction QR that opens this cabin in Odoo."""
        self.ensure_one()
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_Q,
            box_size=10,
            border=4,
        )
        qr.add_data(self.strx_get_cabin_record_url())
        qr.make(fit=True)
        image = qr.make_image(
            fill_color='#111827',
            back_color='#ffffff',
        ).convert('RGB')
        stream = io.BytesIO()
        image.save(stream, format='PNG', optimize=True)
        return base64.b64encode(stream.getvalue()).decode('ascii')

    def strx_get_cabin_card_values(self):
        self.ensure_one()
        readiness_labels = dict(
            self._fields['strx_readiness_state']._description_selection(self.env))
        condition_labels = dict(
            self._fields['strx_condition']._description_selection(self.env))
        is_rtl = self._strx_cabin_card_is_rtl()
        labels = {
            'title': _('Cabin Identity Card'),
            'subtitle': _('Complete serial and QR profile'),
            'unit_badge': _('Physical Unit'),
            'serial': _('Serial'),
            'barcode': _('Barcode'),
            'qr': _('QR Code'),
            'scan_hint': _('Scan to open cabin page'),
            'product': _('Product'),
            'specification': _('Specification'),
            'readiness': _('Readiness'),
            'condition': _('Condition'),
            'dimensions': _('Dimensions'),
            'company': _('Company'),
            'registered_date': _('Registration Date'),
            'operation_readiness': _('Operational Readiness'),
            'internal_id': _('Internal ID'),
        }
        state = self.strx_readiness_state
        accents = {
            'available': {
                'text': '#07884f',
                'bg': '#e8f8ef',
                'border': '#bcebd0',
            },
            'on_rent': {
                'text': '#c33f47',
                'bg': '#fff0f1',
                'border': '#ffd1d5',
            },
            'in_maintenance': {
                'text': '#b46909',
                'bg': '#fff6df',
                'border': '#ffe3a3',
            },
        }
        accent = accents.get(state, {
            'text': '#555bd0',
            'bg': '#f0f1ff',
            'border': '#d8dcff',
        })
        return {
            'dir': 'rtl' if is_rtl else 'ltr',
            'text_align': 'right' if is_rtl else 'left',
            'opposite_align': 'left' if is_rtl else 'right',
            'header_icon_position': 'right:37px;' if is_rtl else 'left:37px;',
            'header_text_position': (
                'right:140px;left:37px;' if is_rtl else 'left:140px;right:37px;'
            ),
            'title': labels['title'],
            'subtitle': labels['subtitle'],
            'unit_badge': labels['unit_badge'],
            'serial_label': labels['serial'],
            'barcode_label': labels['barcode'],
            'qr_label': labels['qr'],
            'scan_hint': labels['scan_hint'],
            'product_label': labels['product'],
            'specification_label': labels['specification'],
            'readiness_label': labels['readiness'],
            'condition_label': labels['condition'],
            'dimensions_label': labels['dimensions'],
            'company_label': labels['company'],
            'registered_date_label': labels['registered_date'],
            'operation_readiness_label': labels['operation_readiness'],
            'internal_id_label': labels['internal_id'],
            'serial': self.name or '-',
            'barcode': self.strx_barcode or self.name or '-',
            'product': self.product_id.name or '-',
            'product_code': self.product_id.default_code or '-',
            'specification': self.product_id.strx_cabin_spec or self.product_id.display_name or '-',
            'readiness': readiness_labels.get(self.strx_readiness_state, self.strx_readiness_state or '-'),
            'condition': condition_labels.get(self.strx_condition, self.strx_condition or '-'),
            'dimensions': self._strx_cabin_card_format_dimensions(),
            'company': self.company_id.name or self.env.company.name or '-',
            'registered_date': self._strx_cabin_card_format_registered_date(),
            'operation_readiness': readiness_labels.get(self.strx_readiness_state, self.strx_readiness_state or '-'),
            'internal_id': self.ref or self.strx_barcode or self.name or '-',
            'barcode_svg_b64': self.strx_get_barcode_svg_b64(),
            'qr_url': self.strx_get_cabin_record_url(),
            'qr_png_b64': self.strx_get_cabin_qr_png_b64(),
            'accent_text': accent['text'],
            'accent_bg': accent['bg'],
            'accent_border': accent['border'],
        }

    def _strx_cabin_card_icon_b64(self, icon, inverse=False):
        """Return crisp, printer-safe monoline SVG icons as data images."""
        paths = {
            'cabin': (
                '<path d="M4 7.5 12 3l8 4.5v9L12 21l-8-4.5z"/>'
                '<path d="m4 7.5 8 4.5 8-4.5M12 12v9"/>'
                '<path d="m8.2 5.1 8 4.5"/>'
            ),
            'product': (
                '<path d="m4 7 8-4 8 4-8 4z"/>'
                '<path d="m4 7 8 4 8-4v10l-8 4-8-4zM12 11v10"/>'
            ),
            'barcode': (
                '<path d="M4 5v14M7 5v14M10 5v14M14 5v14M17 5v14M20 5v14"/>'
            ),
            'qr': (
                '<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4z"/>'
                '<path d="M14 14h2v2h-2zM18 14h2v4h-2zM14 18h4v2h-4z"/>'
            ),
            'document': (
                '<path d="M6 3h8l4 4v14H6zM14 3v5h5M9 12h6M9 16h6"/>'
            ),
            'condition': (
                '<path d="m12 3 2.7 5.5 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>'
            ),
            'company': (
                '<path d="M4 21V7l8-4 8 4v14M8 21v-4h8v4M8 9h1M15 9h1M8 13h1M15 13h1"/>'
            ),
            'dimensions': (
                '<path d="M8 3H3v5M3 3l6 6M16 21h5v-5M21 21l-6-6"/>'
            ),
            'calendar': (
                '<rect x="3" y="5" width="18" height="16" rx="3"/>'
                '<path d="M8 3v4M16 3v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01"/>'
            ),
            'shield': (
                '<path d="M12 3 20 6v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6z"/>'
                '<path d="m8.5 12 2.2 2.2 4.8-4.8"/>'
            ),
            'tag': (
                '<path d="M20 13 13 20 4 11V4h7z"/>'
                '<circle cx="8.5" cy="8.5" r="1.25"/>'
            ),
        }
        color = '#ffffff' if inverse else '#078a63'
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            'width="24" height="24" fill="none" stroke="%(color)s" '
            'stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round">%(paths)s</svg>'
        ) % {'color': color, 'paths': paths[icon]}
        return base64.b64encode(svg.encode('utf-8')).decode('ascii')

    def strx_get_cabin_card_preview_html(self):
        """Build the single shared portrait card used by preview and PDF."""
        self.ensure_one()
        card = self.strx_get_cabin_card_values()

        def esc(value):
            return escape(str(value or ''), quote=True)

        detail_cards = [
            ('product', 'product_label', 'product', 'product_code'),
            ('qr', 'qr_label', 'scan_hint', False),
            ('document', 'specification_label', 'specification', False),
            ('condition', 'condition_label', 'condition', 'readiness'),
            ('company', 'company_label', 'company', False),
            ('dimensions', 'dimensions_label', 'dimensions', False),
        ]
        detail_cells = []
        for icon, label_key, value_key, extra_key in detail_cards:
            extra = (
                '<div style="margin-top:6px;color:#7b8799;font-size:13px;'
                'font-weight:500;line-height:1.3;">%s</div>' % esc(card[extra_key])
                if extra_key else ''
            )
            detail_cells.append('''
                <td style="width:50%%;padding:6px;vertical-align:top;">
                    <div style="height:112px;box-sizing:border-box;padding:16px 18px;
                                border:1px solid #e5eaf0;border-radius:20px;
                                background:#ffffff;">
                        <table dir="%(dir)s" style="width:100%%;height:100%%;border-collapse:collapse;">
                            <tr>
                                <td style="width:59px;vertical-align:middle;">
                                    <span style="display:inline-table;width:52px;height:52px;
                                                 border-radius:16px;background:#edf8f4;text-align:center;">
                                        <span style="display:table-cell;vertical-align:middle;">
                                            <img src="data:image/svg+xml;base64,%(icon)s"
                                                 style="display:block;width:30px;height:30px;margin:0 auto;"/>
                                        </span>
                                    </span>
                                </td>
                                <td style="vertical-align:middle;text-align:%(align)s;">
                                    <div style="color:#7b8799;font-size:12.5px;font-weight:700;line-height:1.15;">%(label)s</div>
                                    <div style="margin-top:6px;color:#172033;font-size:16px;font-weight:800;line-height:1.28;">%(value)s</div>
                                    %(extra)s
                                </td>
                            </tr>
                        </table>
                    </div>
                </td>
            ''' % {
                'dir': esc(card['dir']),
                'align': esc(card['text_align']),
                'icon': self._strx_cabin_card_icon_b64(icon),
                'label': esc(card[label_key]),
                'value': esc(card[value_key]),
                'extra': extra,
            })
        detail_rows = ''.join(
            '<tr>%s%s</tr>' % (detail_cells[index], detail_cells[index + 1])
            for index in range(0, len(detail_cells), 2)
        )

        footer_items = [
            ('calendar', 'registered_date_label', 'registered_date'),
            ('shield', 'operation_readiness_label', 'operation_readiness'),
            ('tag', 'internal_id_label', 'internal_id'),
        ]
        footer_html = ''.join('''
            <td style="width:33.333%%;padding:0 11px;vertical-align:middle;">
                <table dir="%(dir)s" style="width:100%%;border-collapse:collapse;">
                    <tr>
                        <td style="width:44px;vertical-align:middle;">
                            <span style="display:inline-table;width:39px;height:39px;border-radius:12px;
                                         background:#edf8f4;text-align:center;">
                                <span style="display:table-cell;vertical-align:middle;">
                                    <img src="data:image/svg+xml;base64,%(icon)s"
                                         style="display:block;width:24px;height:24px;margin:0 auto;"/>
                                </span>
                            </span>
                        </td>
                        <td style="vertical-align:middle;text-align:%(align)s;">
                            <div style="color:#8490a2;font-size:11px;font-weight:650;line-height:1.2;">%(label)s</div>
                            <div style="margin-top:4px;color:#253147;font-size:13px;font-weight:800;line-height:1.25;">%(value)s</div>
                        </td>
                    </tr>
                </table>
            </td>
        ''' % {
            'dir': esc(card['dir']),
            'align': esc(card['text_align']),
            'icon': self._strx_cabin_card_icon_b64(icon),
            'label': esc(card[label_key]),
            'value': esc(card[value_key]),
        } for icon, label_key, value_key in footer_items)

        qr_img = (
            '<img src="data:image/png;base64,%s" alt="%s" '
            'style="display:block;width:132px;height:132px;margin:0 auto;"/>' % (
                esc(card['qr_png_b64']), esc(card['qr_label']))
            if card['qr_png_b64'] else ''
        )
        html = '''
            <section class="strx-cabin-card-v2" dir="%(dir)s"
                     style="position:relative;width:650px;height:956px;box-sizing:border-box;
                            margin:0 auto;overflow:hidden;border:1px solid #dfe5ec;
                            border-radius:24px;background:#ffffff;color:#172033;
                            font-family:DejaVu Sans,Arial,sans-serif;text-align:%(text_align)s;">
                <div style="height:136px;box-sizing:border-box;padding:27px 37px;
                            position:relative;border-bottom:1px solid #edf0f3;background:#ffffff;">
                    <span style="position:absolute;%(header_icon_position)s;top:33px;
                                 display:inline-table;width:89px;height:69px;
                                 border-radius:20px;background:#078a63;text-align:center;">
                        <span style="display:table-cell;vertical-align:middle;">
                            <img src="data:image/svg+xml;base64,%(logo_icon)s"
                                 style="display:block;width:40px;height:40px;margin:0 auto;"/>
                        </span>
                    </span>
                    <div dir="%(dir)s"
                         style="position:absolute;%(header_text_position)s;top:35px;
                                box-sizing:border-box;text-align:%(text_align)s;">
                        <div style="color:#142033;font-size:30px;font-weight:900;
                                    line-height:1.15;letter-spacing:-.8px;">%(title)s</div>
                        <div style="margin-top:9px;color:#758195;font-size:14px;
                                    font-weight:550;line-height:1.25;">%(subtitle)s</div>
                    </div>
                </div>

                <div style="box-sizing:border-box;padding:23px 39px 13px;text-align:center;">
                    <div style="color:#7b8799;font-size:14px;font-weight:750;">%(serial_label)s</div>
                    <div style="direction:ltr;margin-top:10px;color:%(accent_text)s;font-size:42px;
                                font-weight:900;line-height:1.05;letter-spacing:-1px;
                                text-align:center;word-break:break-all;">%(serial)s</div>
                    <div data-qr-url="%(qr_url)s"
                         style="width:210px;box-sizing:border-box;margin:18px auto 0;
                                padding:12px 14px 10px;border:1px solid #e2e7ed;
                                border-radius:20px;background:#ffffff;text-align:center;">
                        <div style="height:132px;overflow:hidden;">%(qr_img)s</div>
                        <div style="margin-top:7px;color:#657287;font-size:11px;
                                    font-weight:700;line-height:1.25;text-align:center;">%(scan_hint)s</div>
                    </div>
                </div>

                <table dir="%(dir)s" style="width:586px;margin:0 32px;
                                              border-collapse:separate;border-spacing:0;table-layout:fixed;">
                    %(detail_rows)s
                </table>

                <div style="position:absolute;right:34px;bottom:0;left:34px;height:108px;
                            box-sizing:border-box;padding:22px 0;border-top:1px solid #e2e7ed;">
                    <table dir="%(dir)s" style="width:100%%;border-collapse:collapse;table-layout:fixed;">
                        <tr>%(footer_html)s</tr>
                    </table>
                </div>
            </section>
        ''' % {
            'dir': esc(card['dir']),
            'text_align': esc(card['text_align']),
            'accent_text': esc(card['accent_text']),
            'header_icon_position': esc(card['header_icon_position']),
            'header_text_position': esc(card['header_text_position']),
            'title': esc(card['title']),
            'subtitle': esc(card['subtitle']),
            'serial_label': esc(card['serial_label']),
            'serial': esc(card['serial']),
            'qr_url': esc(card['qr_url']),
            'qr_img': qr_img,
            'scan_hint': esc(card['scan_hint']),
            'logo_icon': self._strx_cabin_card_icon_b64('cabin', inverse=True),
            'detail_rows': detail_rows,
            'footer_html': footer_html,
        }
        return Markup(html)

    def strx_get_barcode_svg_b64(self):
        """Return a dependency-free Code128-B SVG barcode for PDF reports."""
        self.ensure_one()
        value = (self.strx_barcode or self.name or '').strip()
        if not value:
            return False
        code_values = [104]  # Start Code B
        code_values.extend(ord(char) - 32 for char in value)
        checksum = 104 + sum(code * position for position, code in enumerate(
            code_values[1:], start=1))
        code_values.append(checksum % 103)
        code_values.append(106)  # Stop

        quiet_modules = 10
        bar_height = 52
        total_modules = quiet_modules * 2 + sum(
            sum(int(width) for width in self._STRX_CODE128_PATTERNS[code])
            for code in code_values
        )
        x = quiet_modules
        rects = []
        for code in code_values:
            pattern = self._STRX_CODE128_PATTERNS[code]
            draw_bar = True
            for width_char in pattern:
                width = int(width_char)
                if draw_bar:
                    rects.append(
                        '<rect x="%s" y="0" width="%s" height="%s"/>' % (
                            x, width, bar_height))
                x += width
                draw_bar = not draw_bar
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 %(width)s %(height)s" width="330" height="92" '
            'role="img" aria-label="%(label)s">'
            '<rect width="100%%" height="100%%" fill="#fff"/>'
            '<g fill="#111827">%(rects)s</g>'
            '</svg>'
        ) % {
            'width': total_modules,
            'height': bar_height,
            'label': escape(value, quote=True),
            'rects': ''.join(rects),
        }
        return base64.b64encode(svg.encode('utf-8')).decode('ascii')

    # --------------------------------------------------------- state machine API
    def _strx_set_readiness(self, new_state, reason=False, note=False):
        """Programmatic entry point for readiness transitions.

        Later modules (allocation, dispatch, return, inspection) call this rather
        than writing the field directly, so a reason is attached to the history.
        The actual logging happens in write() so *any* path is captured.
        """
        for lot in self:
            if new_state == lot.strx_readiness_state:
                continue
            lot.with_context(
                strx_readiness_reason=reason,
                strx_readiness_note=note,
            ).write({'strx_readiness_state': new_state})

    def write(self, vals):
        # Enforce the return→available gate and record history for every state change.
        # A new return cycle must always require fresh clearance.  Without this
        # reset, inspection/cleaning flags from an earlier rental would silently
        # make a later return reusable without anybody clearing it again.
        if vals.get('strx_readiness_state') == 'returned':
            vals = dict(vals, **{
                'strx_inspection_passed': False,
                'strx_cleaning_passed': False,
            })
        old_states = {}
        if 'strx_readiness_state' in vals:
            new_state = vals['strx_readiness_state']
            for lot in self:
                old_states[lot.id] = lot.strx_readiness_state
                if lot.strx_readiness_state == new_state:
                    continue
                # A returned cabin cannot become Available until inspection AND cleaning pass.
                if new_state == 'available' and lot.strx_readiness_state in POST_RETURN_STATES:
                    if not (lot.strx_inspection_passed and lot.strx_cleaning_passed):
                        raise ValidationError(_(
                            "Cabin %(serial)s cannot return to Available: inspection and "
                            "cleaning must both pass first.",
                            serial=lot.name))
        res = super().write(vals)
        if {'name', 'product_id', 'strx_barcode'} & set(vals):
            self._strx_autofill_missing_barcodes()
        if 'strx_readiness_state' in vals:
            self._strx_log_state_change(vals['strx_readiness_state'], old_states)
        return res

    def action_strx_open_readiness_log(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Readiness History'),
            'res_model': 'strx.cabin.readiness.log',
            'view_mode': 'list,form',
            'domain': [('lot_id', '=', self.id)],
            'context': {'default_lot_id': self.id, 'create': False},
        }

    def _strx_log_state_change(self, new_state, old_states):
        Log = self.env['strx.cabin.readiness.log'].sudo()
        reason = self.env.context.get('strx_readiness_reason')
        note = self.env.context.get('strx_readiness_note')
        for lot in self:
            old_state = old_states.get(lot.id)
            if old_state == new_state:
                continue  # no actual transition
            Log.create({
                'lot_id': lot.id,
                'old_state': old_state or False,
                'new_state': new_state,
                'condition': lot.strx_condition,
                'reason': reason or False,
                'note': note or False,
            })
