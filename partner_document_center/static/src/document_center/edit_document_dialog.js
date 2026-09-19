import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

/** Rename a document, categorise it, flag it as important. */
export class EditDocumentDialog extends Component {
    static template = "partner_document_center.EditDocumentDialog";
    static components = { Dialog };
    static props = {
        doc: { type: Object },
        categories: { type: Array },
        onSaved: { type: Function },
        close: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            name: this.props.doc.name,
            categoryId: this.props.doc.categoryId || false,
            isImportant: this.props.doc.isImportant,
            saving: false,
        });
    }

    async save() {
        const doc = this.props.doc;
        this.state.saving = true;
        try {
            if (this.state.name && this.state.name !== doc.name) {
                await this.orm.call("partner.document.center", "action_rename", [
                    doc.id,
                    this.state.name,
                ]);
            }
            await this.orm.call("partner.document.center", "action_set_metadata", [
                doc.id,
                {
                    category_id: this.state.categoryId || false,
                    is_important: this.state.isImportant,
                },
            ]);
            this.props.onSaved();
            this.props.close();
        } catch (error) {
            this.state.saving = false;
            this.notification.add(error.data?.message || _t("The document could not be saved."), {
                type: "danger",
            });
        }
    }

    onCategoryChange(ev) {
        const value = ev.target.value;
        this.state.categoryId = value ? Number(value) : false;
    }
}
