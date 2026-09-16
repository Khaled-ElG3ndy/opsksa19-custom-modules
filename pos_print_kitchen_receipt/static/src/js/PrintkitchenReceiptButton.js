/** @odoo-module **/

// Copyright 2026 Khaled ElGendy. All rights reserved.

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";

export function canPrintKitchenReceipt(order) {
    return Boolean(order?.getSelectedOrderline?.());
}

export class PrintKitchenReceiptButton extends Component {
    static template = "pos_print_kitchen_receipt.PrintKitchenReceiptButton";
    static props = {
        buttonClass: { type: String, optional: true },
        close: { type: Function, optional: true },
    };
    static defaultProps = {
        buttonClass: "btn btn-secondary btn-lg lh-lg",
    };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
    }

    async click() {
        const order = this.pos.getOrder();
        if (!canPrintKitchenReceipt(order)) {
            this.dialog.add(AlertDialog, {
                title: _t("No Product Selected"),
                body: _t("You must first choose a product."),
            });
            return;
        }
        this.props.close?.();
        this.pos.navigate("PrintKitchenReceiptScreen", { orderUuid: order.uuid });
    }
}

ControlButtons.components = {
    ...ControlButtons.components,
    PrintKitchenReceiptButton,
};

