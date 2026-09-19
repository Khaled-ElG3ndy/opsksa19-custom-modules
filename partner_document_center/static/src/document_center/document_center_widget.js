import { Component, onWillStart, onWillUpdateProps, useState, useSubEnv } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { getDefaultConfig } from "@web/views/view";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

import { DocumentCenter } from "./document_center";

/** The "Document Center" tab of the contact form. */
export class DocumentCenterWidget extends Component {
    static template = "partner_document_center.DocumentCenterWidget";
    static components = { DocumentCenter };
    static props = { ...standardWidgetProps };

    get partnerId() {
        return this.props.record.resId;
    }
}

registry.category("view_widgets").add("partner_document_center", {
    component: DocumentCenterWidget,
});

/**
 * The contact's "Files" smart button.
 *
 * The count is fetched after the form is painted instead of being a computed
 * field, so opening a contact - or listing 80 of them - costs nothing extra.
 */
export class DocumentCenterButton extends Component {
    static template = "partner_document_center.DocumentCenterButton";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ count: null, loading: false });

        onWillStart(() => this.fetchCount(this.props.record.resId));
        onWillUpdateProps((nextProps) => {
            if (nextProps.record.resId !== this.props.record.resId) {
                this.fetchCount(nextProps.record.resId);
            }
        });
    }

    async fetchCount(resId) {
        if (!resId) {
            this.state.count = null;
            return;
        }
        this.state.loading = true;
        try {
            this.state.count = await this.orm.call(
                "res.partner",
                "action_count_documents",
                [[resId], "self"]
            );
        } catch {
            this.state.count = null;
        } finally {
            this.state.loading = false;
        }
    }

    get label() {
        return _t("Files");
    }

    async onClick() {
        const action = await this.orm.call("res.partner", "action_open_document_center", [
            [this.props.record.resId],
        ]);
        await this.action.doAction(action);
    }
}

registry.category("view_widgets").add("partner_document_center_button", {
    component: DocumentCenterButton,
});

/** Full-width Document Center, opened by the smart button. */
export class DocumentCenterAction extends Component {
    static template = "partner_document_center.DocumentCenterAction";
    static components = { DocumentCenter, Layout };
    static props = ["*"];

    setup() {
        // Layout renders the control panel (and therefore the breadcrumb back
        // to the contact) from env.config; a client action does not get a full
        // one by default, so fill in the gaps the way core actions do.
        useSubEnv({
            config: { ...getDefaultConfig(), ...this.env.config },
        });
    }

    get partnerId() {
        return this.props.action.params?.partner_id || false;
    }

    get partnerName() {
        return this.props.action.params?.partner_name || "";
    }
}

registry.category("actions").add("partner_document_center", DocumentCenterAction);
