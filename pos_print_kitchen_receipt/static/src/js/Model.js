/** @odoo-module **/

// Copyright 2026 Khaled ElGendy. All rights reserved.

import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { patch } from "@web/core/utils/patch";

/**
 * Convert either an Odoo 19 related record, a legacy [id, name] pair, or a raw
 * id into the small category value needed by the receipt.
 */
export function normalizeCategory(category) {
    if (!category) {
        return null;
    }
    if (Array.isArray(category)) {
        return category.length
            ? { id: category[0], name: category[1] || String(category[0]) }
            : null;
    }
    if (typeof category === "number" || typeof category === "string") {
        return { id: category, name: String(category) };
    }
    return {
        id: category.id,
        name: category.display_name || category.name || String(category.id),
    };
}

/** Return the internal product category used by the original kitchen receipt. */
export function getKitchenReceiptCategory(line) {
    const product = line?.product_id || line?.product;
    const productTemplate = product?.product_tmpl_id || product;
    return normalizeCategory(productTemplate?.categ_id || product?.categ_id || line?.categ_id);
}

patch(PosOrderline.prototype, {
    get kitchenReceiptCategory() {
        return getKitchenReceiptCategory(this);
    },
});

