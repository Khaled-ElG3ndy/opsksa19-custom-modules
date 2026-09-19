/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";


export class CabinDashboard extends Component {
    static template = "strx_cabin_dashboard.CabinDashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            refreshing: false,
            data: null,
        });
        onWillStart(() => this.loadData());
    }

    get isRtl() {
        return localization.direction === "rtl";
    }

    async loadData(refresh = false) {
        if (refresh) {
            this.state.refreshing = true;
        } else {
            this.state.loading = true;
        }
        try {
            this.state.data = await this.orm.call(
                "strx.cabin.dashboard",
                "get_dashboard_data",
                []
            );
        } catch (error) {
            this.notification.add(
                _t("The dashboard could not be loaded. Please try again."),
                { type: "danger" }
            );
            throw error;
        } finally {
            this.state.loading = false;
            this.state.refreshing = false;
        }
    }

    get donutStyle() {
        const segments = this.state.data?.distribution || [];
        const total = segments.reduce((sum, segment) => sum + segment.count, 0);
        if (!total) {
            return "background: #E9ECF4";
        }
        let cursor = 0;
        const stops = segments
            .filter((segment) => segment.count)
            .map((segment) => {
                const start = cursor;
                cursor += (segment.count / total) * 100;
                return `${segment.color} ${start}% ${cursor}%`;
            });
        return `background: conic-gradient(${stops.join(", ")})`;
    }

    openList(resModel, name, domain = []) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: resModel,
            views: [[false, "list"], [false, "form"]],
            view_mode: "list,form",
            domain,
        });
    }

    openRecord(resModel, resId) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            res_id: resId,
            views: [[false, "form"]],
            view_mode: "form",
        });
    }

    openFleet(domain = []) {
        return this.openList(
            "stock.lot",
            _t("Cabin Units"),
            [["strx_is_cabin", "=", true], ...domain]
        );
    }

    openAllocations(domain = []) {
        return this.openList(
            "strx.cabin.allocation",
            _t("Cabin Allocations"),
            domain
        );
    }

    openShipping(domain = []) {
        return this.openList(
            "strx.cabin.shipping.order",
            _t("Shipments"),
            domain
        );
    }

    openSubstitutions(domain = []) {
        return this.openList(
            "strx.cabin.substitution",
            _t("Substitutions"),
            domain
        );
    }

    createRecord(resModel, name) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: resModel,
            views: [[false, "form"]],
            view_mode: "form",
        });
    }

    createAllocation() {
        return this.createRecord(
            "strx.cabin.allocation",
            _t("New Allocation")
        );
    }
}

registry.category("actions").add("strx_cabin_dashboard", CabinDashboard);
