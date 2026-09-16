/** @odoo-module **/

// Copyright 2026 Khaled ElGendy
// License OPL-1.

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";

/**
 * Odoo 19 calls its built-in whole-order note `general_customer_note`.
 * Keep compatibility with the `order_note` field supplied by POS order-note
 * add-ons, which is the direct equivalent of the `note` value used by the
 * original Odoo 17 implementation.
 */
export function getKitchenOrderNote(order) {
    return order?.order_note || order?.general_customer_note || "";
}

patch(PosStore.prototype, {
    getOrderData(order, reprint) {
        const orderData = super.getOrderData(...arguments);
        orderData.order_note = this.config.print_kitchen_notes_receipt
            ? getKitchenOrderNote(order)
            : "";
        return orderData;
    },
});
