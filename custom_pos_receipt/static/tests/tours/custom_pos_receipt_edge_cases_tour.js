import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import * as PaymentScreen from "@point_of_sale/../tests/pos/tours/utils/payment_screen_util";
import * as ReceiptScreen from "@point_of_sale/../tests/pos/tours/utils/receipt_screen_util";
import { registry } from "@web/core/registry";

// The orders below are the ones that would break a receipt written for the
// happy path only: no customer at all, nothing taxed, several rates at once, a
// customer who belongs to a company, and a tax that has no percentage to
// print. Each is rung up for real and the printed receipt is read back.

const PAYMENT_METHOD = "Bank";

/** Open the register and start an order. */
function openRegister() {
    return [Chrome.startPoS(), Dialog.confirm()].flat();
}

/** Take the order to the receipt screen. */
function payAndPrint() {
    return [
        ProductScreen.clickPayButton(),
        PaymentScreen.clickPaymentMethod(PAYMENT_METHOD),
        PaymentScreen.clickValidate(),
        ReceiptScreen.isShown(),
        ReceiptScreen.receiptIsThere(),
    ].flat();
}

function selectCustomer(name) {
    return [ProductScreen.clickPartnerButton(), ProductScreen.clickCustomer(name)].flat();
}

/** Nothing of the kind is on the receipt. */
function receiptHasNo(selector, what) {
    return {
        content: `the receipt carries no ${what}`,
        trigger: ".pos-receipt",
        run: () => {
            const found = document.querySelectorAll(`.pos-receipt ${selector}`);
            if (found.length) {
                throw new Error(`expected no ${what}, found ${found.length}`);
            }
        },
    };
}

/** The client line reads exactly this, whitespace collapsed. */
function clientNameReads(expected) {
    return {
        content: `the client line names "${expected}"`,
        trigger: ".pos-receipt .pos-receipt-client-name",
        run: () => {
            const actual = document
                .querySelector(".pos-receipt .pos-receipt-client-name")
                .textContent.replace(/\s+/g, " ")
                .trim();
            if (actual !== expected) {
                throw new Error(`expected client "${expected}", got "${actual}"`);
            }
        },
    };
}

/**
 * The VAT table holds exactly these rows, in this order.
 *
 * The order is the taxes' own sequence, so a receipt printed twice reads the
 * same way; asserting it here is what holds that promise.
 */
function vatSummaryRowsAre(expectedRows) {
    return {
        content: `the VAT summary holds ${expectedRows.length} row(s)`,
        trigger: ".pos-receipt .pos-receipt-vat-summary tbody tr",
        run: () => {
            const rows = [
                ...document.querySelectorAll(".pos-receipt-vat-summary tbody tr"),
            ].map((row) =>
                [...row.querySelectorAll("td")].map((cell) => cell.textContent.trim()).join("|")
            );
            const expected = expectedRows.map((row) => row.join("|"));
            if (rows.join(" / ") !== expected.join(" / ")) {
                throw new Error(
                    `expected VAT rows ${expected.join(" / ")}, got ${rows.join(" / ")}`
                );
            }
        },
    };
}

// A walk-in customer: no client line, and the receipt is otherwise printed.
registry.category("web_tour.tours").add("custom_pos_receipt_no_customer_tour", {
    steps: () =>
        [
            openRegister(),
            ProductScreen.clickDisplayedProduct("Corner Desk Left Sit"),
            payAndPrint(),
            receiptHasNo(".pos-receipt-client", "client line"),
            vatSummaryRowsAre([["15 %", "12.75", "85.00", "97.75"]]),
            Chrome.endTour(),
        ].flat(),
});

// Nothing taxed: no table rather than a table of zeroes.
registry.category("web_tour.tours").add("custom_pos_receipt_untaxed_tour", {
    steps: () =>
        [
            openRegister(),
            selectCustomer("Billy Fox"),
            ProductScreen.clickDisplayedProduct("Wall Shelf Unit"),
            payAndPrint(),
            clientNameReads("Billy Fox"),
            receiptHasNo(".pos-receipt-vat-summary", "VAT summary"),
            Chrome.endTour(),
        ].flat(),
});

// Two rates sharing one tax group, as the Saudi chart sets them up: one row
// each, not one blended row for the group.
registry.category("web_tour.tours").add("custom_pos_receipt_multi_vat_tour", {
    steps: () =>
        [
            openRegister(),
            ProductScreen.clickDisplayedProduct("Corner Desk Left Sit"),
            ProductScreen.clickDisplayedProduct("Reduced Rate Item"),
            payAndPrint(),
            vatSummaryRowsAre([
                ["15 %", "12.75", "85.00", "97.75"],
                ["5 %", "5.00", "100.00", "105.00"],
            ]),
            Chrome.endTour(),
        ].flat(),
});

// A contact who belongs to a company: the company is named too, exactly as the
// core receipt used to name it before this module took the line over.
registry.category("web_tour.tours").add("custom_pos_receipt_company_contact_tour", {
    steps: () =>
        [
            openRegister(),
            selectCustomer("Lily Fox"),
            ProductScreen.clickDisplayedProduct("Corner Desk Left Sit"),
            payAndPrint(),
            clientNameReads("Deco Addict, Lily Fox"),
            Chrome.endTour(),
        ].flat(),
});

// A fixed tax has no percentage of its own, so the rate is worked back out of
// the amounts. 10.00 charged on 100.00 prints as 10 %, which is the only rate
// consistent with the rest of the row.
registry.category("web_tour.tours").add("custom_pos_receipt_fixed_tax_tour", {
    steps: () =>
        [
            openRegister(),
            ProductScreen.clickDisplayedProduct("Fixed Duty Item"),
            payAndPrint(),
            vatSummaryRowsAre([["10 %", "10.00", "100.00", "110.00"]]),
            Chrome.endTour(),
        ].flat(),
});

// Zero-rated goods sit in the same group as the 15%. They are taxed, at 0%,
// and a receipt that dropped them would be understating what was sold.
registry.category("web_tour.tours").add("custom_pos_receipt_zero_rated_tour", {
    steps: () =>
        [
            openRegister(),
            ProductScreen.clickDisplayedProduct("Corner Desk Left Sit"),
            ProductScreen.clickDisplayedProduct("Zero Rated Item"),
            payAndPrint(),
            vatSummaryRowsAre([
                ["15 %", "12.75", "85.00", "97.75"],
                ["0 %", "0.00", "50.00", "50.00"],
            ]),
            Chrome.endTour(),
        ].flat(),
});
