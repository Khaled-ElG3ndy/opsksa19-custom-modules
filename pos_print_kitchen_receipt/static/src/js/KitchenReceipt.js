/** @odoo-module **/

// Copyright 2026 Khaled ElGendy. All rights reserved.

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ReceiptHeader } from "@point_of_sale/app/screens/receipt_screen/receipt/receipt_header/receipt_header";
import { getKitchenReceiptCategory } from "./Model";

function relationId(value) {
    if (Array.isArray(value)) {
        return value[0];
    }
    return typeof value === "object" && value !== null ? value.id : value;
}

export function getExcludedCategoryIds(config) {
    return new Set(
        (config?.print_kitchen_categories_exclude_ids || [])
            .map(relationId)
            .filter((id) => id !== undefined && id !== null)
    );
}

export function getKitchenReceiptLines(order, config = order?.config || order?.config_id) {
    const lines = order?.getOrderlines?.() || order?.lines || order?.orderlines || [];
    if (!config?.print_kitchen_receipt_categ) {
        return [...lines];
    }
    const excludedCategoryIds = getExcludedCategoryIds(config);
    return lines.filter((line) => {
        const category = getKitchenReceiptCategory(line);
        return !category || !excludedCategoryIds.has(category.id);
    });
}

export function getKitchenReceiptCategories(order, config = order?.config || order?.config_id) {
    const categories = new Map();
    for (const line of getKitchenReceiptLines(order, config)) {
        const category = getKitchenReceiptCategory(line) || {
            id: "uncategorized",
            name: _t("Uncategorized"),
        };
        if (!categories.has(category.id)) {
            categories.set(category.id, category);
        }
    }
    return [...categories.values()];
}

export class KitchenReceipt extends Component {
    static template = "pos_print_kitchen_receipt.KitchenReceipt";
    static components = { ReceiptHeader };
    static props = {
        order: Object,
    };

    get order() {
        return this.props.order;
    }

    get config() {
        return this.order.config || this.order.config_id || {};
    }

    get orderLines() {
        return getKitchenReceiptLines(this.order, this.config);
    }

    get orderCategories() {
        return getKitchenReceiptCategories(this.order, this.config);
    }

    linesForCategory(category) {
        return this.orderLines.filter((line) => {
            const lineCategory = getKitchenReceiptCategory(line);
            return category.id === "uncategorized"
                ? !lineCategory
                : lineCategory?.id === category.id;
        });
    }

    lineName(line) {
        return (
            line.getFullProductName?.() ||
            line.full_product_name ||
            line.productName ||
            line.product_id?.display_name ||
            line.product_id?.name ||
            ""
        );
    }

    lineQuantity(line) {
        return line.quantityStr?.qtyStr ?? line.getQuantity?.() ?? line.qty ?? line.quantity ?? 0;
    }

    lineCustomerNote(line) {
        return line.getCustomerNote?.() || line.customer_note || line.customerNote || "";
    }

    get orderName() {
        const orderName = this.order.name && this.order.name !== "/" ? this.order.name : "";
        return orderName || this.order.pos_reference || this.order.getName?.() || "";
    }

    get orderDate() {
        return this.order.date_order && this.order.formatDateOrTime
            ? this.order.formatDateOrTime("date_order")
            : this.order.date || "";
    }
}

