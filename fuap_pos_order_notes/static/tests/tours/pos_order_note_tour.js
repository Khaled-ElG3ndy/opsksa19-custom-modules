import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import * as PaymentScreen from "@point_of_sale/../tests/pos/tours/utils/payment_screen_util";
import * as ReceiptScreen from "@point_of_sale/../tests/pos/tours/utils/receipt_screen_util";
import * as TicketScreen from "@point_of_sale/../tests/pos/tours/utils/ticket_screen_util";
import { registry } from "@web/core/registry";

function clickOrderNote() {
    return {
        content: "open the order note popup",
        trigger: ".product-screen .fuap-order-note-button:not(:disabled)",
        run: "click",
    };
}

function popupDirectionIs(direction) {
    return {
        content: `the Order Note popup is ${direction}`,
        trigger: `.fuap-order-note-popup > div[dir='${direction}']`,
        run: () => {
            const mirrored = [...document.styleSheets].some((sheet) =>
                (sheet.href || "").includes(".rtl.")
            );
            if (mirrored !== (direction === "rtl")) {
                throw new Error(`expected ${direction} POS stylesheets`);
            }
        },
    };
}

function enterOrderNote(value) {
    return {
        content: "enter a free-text order note",
        trigger: ".fuap-order-note-popup textarea",
        run: `edit ${value}`,
    };
}

function clickTag(label) {
    return {
        content: `insert the predefined note ${label}`,
        trigger: `.fuap-order-note-popup .fuap-order-note-tag:contains('${label}')`,
        run: "click",
    };
}

function noteInputIs(value) {
    return {
        content: "the free text and predefined note are combined",
        trigger: ".fuap-order-note-popup textarea",
        run: () => {
            const actual = document.querySelector(".fuap-order-note-popup textarea").value;
            if (actual !== value) {
                throw new Error(`expected note '${value}', got '${actual}'`);
            }
        },
    };
}

function saveOrderNote() {
    return {
        content: "save the order note",
        trigger: ".modal-footer .fuap-order-note-save",
        run: "click",
    };
}

function cancelOrderNote() {
    return {
        content: "cancel the order note popup",
        trigger: ".modal-footer .fuap-order-note-cancel",
        run: "click",
    };
}

registry.category("web_tour.tours").add("fuap_pos_order_note_flow", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm(),
            ProductScreen.isShown(),
            ProductScreen.clickDisplayedProduct("Whiteboard Pen"),
            clickOrderNote(),
            popupDirectionIs("ltr"),
            enterOrderNote("test note"),
            clickTag("Gluten free"),
            noteInputIs("test note, Gluten free"),
            saveOrderNote(),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod("Bank"),
            PaymentScreen.clickValidate(),
            ReceiptScreen.isShown(),
            {
                content: "order note is printed on the receipt",
                trigger:
                    ".receipt-screen .fuap-order-note-receipt-value:contains('test note, Gluten free')",
            },
            Chrome.endTour(),
        ].flat(),
});

registry.category("web_tour.tours").add("fuap_pos_order_note_hidden_receipt", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm(),
            ProductScreen.isShown(),
            ProductScreen.clickDisplayedProduct("Whiteboard Pen"),
            clickOrderNote(),
            enterOrderNote("private order note"),
            saveOrderNote(),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod("Bank"),
            PaymentScreen.clickValidate(),
            ReceiptScreen.isShown(),
            {
                content: "order note is intentionally hidden from the receipt",
                trigger: ".receipt-screen .pos-receipt",
                run: () => {
                    if (document.querySelector(".receipt-screen .fuap-order-note-receipt")) {
                        throw new Error("the disabled receipt option still printed the order note");
                    }
                },
            },
            Chrome.endTour(),
        ].flat(),
});

registry.category("web_tour.tours").add("fuap_pos_order_note_reprint", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm(),
            ProductScreen.isShown(),
            ProductScreen.clickDisplayedProduct("Whiteboard Pen"),
            clickOrderNote(),
            enterOrderNote("reprint order note"),
            saveOrderNote(),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod("Bank"),
            PaymentScreen.clickValidate(),
            ReceiptScreen.isShown(),
            ReceiptScreen.clickNextOrder(),
            ProductScreen.isShown(),
            Chrome.clickOrders(),
            TicketScreen.selectFilter("Paid"),
            {
                content: "select the paid order for receipt reprinting",
                trigger: ".ticket-screen .order-row:contains('Paid')",
                run: "click",
            },
            {
                content: "reprint the paid order receipt",
                trigger: ".ticket-screen .control-buttons button:contains('Print Receipt')",
                run: () => {
                    window.__fuapOriginalPrint = window.print;
                    window.print = (receipt) => {
                        window.__fuapReprintedReceipt = receipt?.textContent || "";
                        document.body.dataset.fuapReprintDone = "1";
                    };
                    [...document.querySelectorAll(".ticket-screen .control-buttons button")]
                        .find((button) => button.textContent.includes("Print Receipt"))
                        .click();
                },
            },
            {
                content: "the reprinted receipt contains the persisted order note",
                trigger: "body[data-fuap-reprint-done='1']",
                run: () => {
                    window.print = window.__fuapOriginalPrint;
                    if (!window.__fuapReprintedReceipt.includes("reprint order note")) {
                        throw new Error("the reprinted receipt did not contain the order note");
                    }
                },
            },
            Chrome.endTour(),
        ].flat(),
});

registry.category("web_tour.tours").add("fuap_pos_order_note_ltr", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm(),
            ProductScreen.isShown(),
            ProductScreen.clickDisplayedProduct("Whiteboard Pen"),
            clickOrderNote(),
            popupDirectionIs("ltr"),
            {
                content: "English Order Note title is loaded",
                trigger: ".modal-title:contains('Order Note')",
            },
            cancelOrderNote(),
            Chrome.endTour(),
        ].flat(),
});

registry.category("web_tour.tours").add("fuap_pos_order_note_rtl", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm(),
            ProductScreen.isShown(),
            ProductScreen.clickDisplayedProduct("Whiteboard Pen"),
            clickOrderNote(),
            popupDirectionIs("rtl"),
            {
                content: "Arabic Order Note title is loaded",
                trigger: ".modal-title:contains('ملاحظة الطلب')",
            },
            {
                content: "Arabic predefined tag is loaded",
                trigger: ".fuap-order-note-tag:contains('تم تجهيز الطلب')",
            },
            cancelOrderNote(),
            Chrome.endTour(),
        ].flat(),
});
