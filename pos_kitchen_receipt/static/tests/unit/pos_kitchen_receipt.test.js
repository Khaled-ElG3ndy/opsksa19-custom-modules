import { describe, expect, test } from "@odoo/hoot";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { getKitchenOrderNote } from "@pos_kitchen_receipt/js/model";
import { patchTranslations } from "@web/../tests/web_test_helpers";
import { renderToElement } from "@web/core/utils/render";

describe("POS Kitchen Receipt", () => {
    test("uses an add-on order note when available", () => {
        expect(
            getKitchenOrderNote({
                order_note: "No onions",
                general_customer_note: "Customer note",
            })
        ).toBe("No onions");
    });

    test("uses the Odoo 19 whole-order note", () => {
        expect(getKitchenOrderNote({ general_customer_note: "Extra hot" })).toBe("Extra hot");
    });

    test("returns an empty printable value when the order has no note", () => {
        expect(getKitchenOrderNote({})).toBe("");
        expect(getKitchenOrderNote()).toBe("");
    });

    test("adds or removes the note data according to the POS setting", () => {
        const store = {
            config: { print_kitchen_notes_receipt: true },
            getStrNotes: () => "",
        };
        const order = {
            preparationName: "Order 00001",
            config_id: { name: "Kitchen" },
            tracking_number: "1",
            presetDateTime: false,
            preset_id: null,
            employee_id: { name: "Cashier" },
            internal_note: "",
            general_customer_note: "No onions",
        };

        expect(PosStore.prototype.getOrderData.call(store, order, false).order_note).toBe(
            "No onions"
        );
        store.config.print_kitchen_notes_receipt = false;
        expect(PosStore.prototype.getOrderData.call(store, order, false).order_note).toBe("");
    });

    test("renders the note on the Odoo 19 preparation receipt", () => {
        patchTranslations();
        const receipt = renderToElement("point_of_sale.OrderChangeReceipt", {
            data: {
                preset_name: "",
                config_name: "Kitchen",
                time: "12:00",
                employee_name: "Cashier",
                tracking_number: "1",
                pos_reference: "Order 00001",
                reprint: false,
                internal_note: "",
                general_customer_note: "",
                order_note: "No onions",
                changes: {
                    title: "NEW",
                    data: [],
                },
            },
        });
        const note = receipt.querySelector(".pos-order-notes");

        expect(note).not.toBe(null);
        expect(note.textContent).toInclude("No onions");
        expect(receipt.style.fontSize).toBe("25px");
    });

    // Core already prints a whole-order note of its own, under a "CUSTOMER
    // NOTE" heading, but only on a receipt that carries no line changes. On
    // such a receipt this module used to print the very same text a second
    // time under "Note :".
    test("does not print the customer note twice when there are no changes", () => {
        patchTranslations();
        const receipt = renderToElement("point_of_sale.OrderChangeReceipt", {
            data: {
                preset_name: "",
                config_name: "Kitchen",
                time: "12:00",
                employee_name: "Cashier",
                tracking_number: "1",
                pos_reference: "Order 00001",
                reprint: false,
                internal_note: "",
                general_customer_note: "No onions",
                order_note: "No onions",
                changes: { title: "", data: [] },
            },
        });

        expect(receipt.textContent.match(/No onions/g)).toHaveLength(1);
    });

    // The same note alongside actual line changes is the case the module
    // exists for: core prints nothing there, so this line must appear.
    test("prints the note next to the line changes core leaves it off", () => {
        patchTranslations();
        const receipt = renderToElement("point_of_sale.OrderChangeReceipt", {
            data: {
                preset_name: "",
                config_name: "Kitchen",
                time: "12:00",
                employee_name: "Cashier",
                tracking_number: "1",
                pos_reference: "Order 00001",
                reprint: false,
                internal_note: "",
                general_customer_note: "No onions",
                order_note: "No onions",
                changes: { title: "NEW", data: [] },
            },
        });

        expect(receipt.querySelector(".pos-order-notes")).not.toBe(null);
        expect(receipt.querySelector(".pos-order-notes").textContent).toInclude("No onions");
    });

    // A dedicated order note from an add-on is a different text from the
    // customer's own note, so both belong on the receipt.
    test("prints an add-on order note alongside the customer note", () => {
        patchTranslations();
        const receipt = renderToElement("point_of_sale.OrderChangeReceipt", {
            data: {
                preset_name: "",
                config_name: "Kitchen",
                time: "12:00",
                employee_name: "Cashier",
                tracking_number: "1",
                pos_reference: "Order 00001",
                reprint: false,
                internal_note: "",
                general_customer_note: "Table by the window",
                order_note: "No onions",
                changes: { title: "", data: [] },
            },
        });

        expect(receipt.textContent).toInclude("No onions");
        expect(receipt.textContent).toInclude("Table by the window");
    });
});
