/** @odoo-module **/

// Copyright 2026 Khaled ElGendy. All rights reserved.

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useErrorHandlers, useTrackedAsync } from "@point_of_sale/app/hooks/hooks";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useRouterParamsChecker } from "@point_of_sale/app/hooks/pos_router_hook";
import { KitchenReceipt } from "./KitchenReceipt";

export class PrintKitchenReceiptScreen extends Component {
    static template = "pos_print_kitchen_receipt.PrintKitchenReceiptScreen";
    static components = { KitchenReceipt };
    static props = {
        orderUuid: { type: String },
    };

    setup() {
        super.setup();
        this.pos = usePos();
        this.ui = useService("ui");
        this.printer = useService("printer");
        useRouterParamsChecker();
        useErrorHandlers();
        this.doPrint = useTrackedAsync(() => this.printReceipt());
    }

    get currentOrder() {
        return this.pos.models["pos.order"].getBy("uuid", this.props.orderUuid);
    }

    goBack() {
        this.pos.navigate("ProductScreen", { orderUuid: this.currentOrder.uuid });
    }

    async printReceipt() {
        const result = await this.printer.print(
            KitchenReceipt,
            { order: this.currentOrder },
            this.pos.printOptions || { webPrintFallback: true }
        );
        if (result?.warningCode) {
            this.pos.displayPrinterWarning(result, "Kitchen Receipt Printer");
        }
        return result;
    }
}

registry.category("pos_pages").add("PrintKitchenReceiptScreen", {
    name: "PrintKitchenReceiptScreen",
    component: PrintKitchenReceiptScreen,
    route: `/pos/ui/${odoo.pos_config_id}/kitchen-receipt/{string:orderUuid}`,
    params: {
        orderUuid: true,
        // useRouterParamsChecker compares order.finalized against this value and
        // sends the cashier back to the default page when they differ. The kitchen
        // receipt is printed for an order still being taken, exactly like
        // ProductScreen and PaymentScreen, so the expected state is "not finalized".
        orderFinalized: false,
    },
});

