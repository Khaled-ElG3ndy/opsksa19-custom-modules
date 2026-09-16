import { describe, expect, test } from "@odoo/hoot";
import { queryAll, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { getFilledOrder, setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { getKitchenReceiptCategory } from "@pos_print_kitchen_receipt/js/Model";
import {
    KitchenReceipt,
    getExcludedCategoryIds,
    getKitchenReceiptCategories,
    getKitchenReceiptLines,
} from "@pos_print_kitchen_receipt/js/KitchenReceipt";
import { canPrintKitchenReceipt } from "@pos_print_kitchen_receipt/js/PrintkitchenReceiptButton";

function makeOrder({ categoryWise = false, excluded = [] } = {}) {
    const food = { id: 10, name: "Food" };
    const drinks = { id: 20, name: "Drinks" };
    const makeLine = (id, name, quantity, category, customerNote = "") => ({
        id,
        uuid: `line-${id}`,
        qty: quantity,
        product_id: {
            display_name: name,
            product_tmpl_id: { categ_id: category },
        },
        getFullProductName: () => name,
        getCustomerNote: () => customerNote,
        getQuantity: () => quantity,
    });
    const lines = [
        makeLine(1, "Burger (Large)", 2, food, "No onions"),
        makeLine(2, "Fries", 1, food),
        makeLine(3, "Cola", 3, drinks),
    ];
    return {
        name: "Order 00001",
        pos_reference: "Order 00001",
        date_order: true,
        lines,
        config: {
            receiptLogoUrl: "",
            receipt_header: "",
            receipt_footer: "Kitchen copy",
            _IS_VAT: false,
            displayTrackingNumber: false,
            print_kitchen_receipt_categ: categoryWise,
            print_kitchen_categories_exclude_ids: excluded,
        },
        partner_id: false,
        tracking_number: false,
        presetDateTime: false,
        getOrderlines: () => lines,
        getCashierName: () => "Cashier",
        getName: () => "Order 00001",
        formatDateOrTime: () => "09/01/2026 18:00",
    };
}

definePosModels();

describe("POS Kitchen Receipt", () => {
    test("normalizes and reads the product category from an Odoo 19 line", () => {
        const category = getKitchenReceiptCategory({
            product_id: { product_tmpl_id: { categ_id: { id: 7, name: "Food" } } },
        });
        expect(category).toEqual({ id: 7, name: "Food" });
    });

    test("accepts related records, ids, and legacy pairs for excluded categories", () => {
        const ids = getExcludedCategoryIds({
            print_kitchen_categories_exclude_ids: [{ id: 1 }, 2, [3, "Three"]],
        });
        expect([...ids]).toEqual([1, 2, 3]);
    });

    test("groups lines and excludes the configured product categories", () => {
        const order = makeOrder({ categoryWise: true, excluded: [{ id: 20 }] });
        expect(getKitchenReceiptLines(order).map((line) => line.id)).toEqual([1, 2]);
        expect(getKitchenReceiptCategories(order)).toEqual([{ id: 10, name: "Food" }]);
    });

    test("does not apply category exclusions when category-wise mode is disabled", () => {
        const order = makeOrder({ categoryWise: false, excluded: [{ id: 20 }] });
        expect(getKitchenReceiptLines(order)).toHaveLength(3);
    });

    test("requires a selected product before opening the print screen", () => {
        expect(canPrintKitchenReceipt({ getSelectedOrderline: () => ({ id: 1 }) })).toBe(true);
        expect(canPrintKitchenReceipt({ getSelectedOrderline: () => undefined })).toBe(false);
        expect(canPrintKitchenReceipt()).toBe(false);
    });

    // Rendered against a real Point of Sale store rather than the literals
    // above: the receipt reads its categories off product.template records and
    // its exclusions off a pos.config many2many, and only the real models say
    // whether those readings hold.
    test("renders grouped product names, notes, quantities and footer", async () => {
        const store = await setupPosEnv();
        const order = await getFilledOrder(store);

        const food = store.models["product.category"].get(4);
        const services = store.models["product.category"].get(3);
        const [kept, excluded] = order.lines;
        kept.product_id.product_tmpl_id.categ_id = food;
        excluded.product_id.product_tmpl_id.categ_id = services;
        kept.customer_note = "No onions";

        order.config.print_kitchen_receipt_categ = true;
        order.config.print_kitchen_categories_exclude_ids = [services];
        order.config.receipt_footer = "Kitchen copy";

        await mountWithCleanup(KitchenReceipt, { props: { order } });

        expect(queryAll(".kitchen-category")).toHaveLength(1);
        expect(queryOne(".kitchen-category").textContent).toInclude(food.name);
        expect(queryAll(".kitchen-product-name")).toHaveLength(1);
        expect(queryAll(".kitchen-product-name")[0].textContent).toInclude(
            kept.getFullProductName()
        );
        expect(queryOne(".pos-receipt-customer-note").textContent).toInclude("No onions");
        expect(queryAll(".kitchen-product-qty")[0].textContent).toInclude(String(kept.qty));
        expect(document.body.textContent).toInclude("Kitchen copy");
        expect(document.body.textContent).not.toInclude(excluded.getFullProductName());
    });
});
