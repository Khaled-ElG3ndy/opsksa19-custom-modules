import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { localization } from "@web/core/l10n/localization";
import { Component } from "@odoo/owl";

export class PdfOptionsModal extends Component {
    static template = "report_pdf_options.ButtonOptions";
    static components = { Dialog };
    static props = {
        onSelectOption: Function,
        close: { type: Function, optional: true },
    };

    setup() {
        this.title = _t("PDF report");
        this.subtitle = _t("Choose how you would like to continue.");
        this.direction = localization.direction;
        this.dialogClass = `o_pdf_options_dialog o_pdf_options_${this.direction}`;
        this.options = [
            {
                key: "print",
                icon: "fa-print",
                title: _t("Print"),
                description: _t("Open the browser print dialog."),
            },
            {
                key: "download",
                icon: "fa-download",
                title: _t("Download"),
                description: _t("Save a PDF copy to your device."),
            },
            {
                key: "open",
                icon: "fa-external-link",
                title: _t("Open"),
                description: _t("View the PDF in a new browser tab."),
            },
        ];
    }

    executePdfAction(option) {
        this.props.onSelectOption(option);
    }
}
