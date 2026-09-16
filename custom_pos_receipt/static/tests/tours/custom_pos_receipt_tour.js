import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import * as PaymentScreen from "@point_of_sale/../tests/pos/tours/utils/payment_screen_util";
import * as ReceiptScreen from "@point_of_sale/../tests/pos/tours/utils/receipt_screen_util";
import { registry } from "@web/core/registry";

// The customer, the product and the payment method are all created by the
// Python test, so every step below keys off data or off a CSS selector and
// never off interface text. That is what lets the same steps run in English
// and in Arabic.
const CUSTOMER = "Billy Fox";
const PRODUCT = "Corner Desk Left Sit";
const PAYMENT_METHOD = "Bank";

/** Ring up one taxed product for the customer and validate the order. */
function sellOneProduct() {
    return [
        Chrome.startPoS(),
        Dialog.confirm(),
        ProductScreen.clickPartnerButton(),
        ProductScreen.clickCustomer(CUSTOMER),
        ProductScreen.clickDisplayedProduct(PRODUCT),
        ProductScreen.clickPayButton(),
        PaymentScreen.clickPaymentMethod(PAYMENT_METHOD),
        PaymentScreen.clickValidate(),
        ReceiptScreen.isShown(),
        ReceiptScreen.receiptIsThere(),
    ].flat();
}

/** The client line is printed, and it names the customer. */
function clientLineNames(name) {
    return {
        content: `the receipt names the client ${name}`,
        trigger: `.pos-receipt .pos-receipt-client .pos-receipt-client-name:contains("${name}")`,
    };
}

/** The client line carries the label it is supposed to, in the active language. */
function clientLineIsLabelled(label) {
    return {
        content: `the client line is labelled "${label}"`,
        trigger: `.pos-receipt .pos-receipt-client .pos-receipt-client-label:contains("${label}")`,
    };
}

/**
 * The whole client line reads exactly this, spaces included.
 *
 * Checked literally rather than with the whitespace collapsed: OWL drops a
 * whitespace-only text node that spans a line break, which is how the label
 * and the name came out welded together as "Client:Billy Fox".
 */
function clientLineReads(expected) {
    return {
        content: `the client line reads "${expected}"`,
        trigger: ".pos-receipt .pos-receipt-client",
        run: () => {
            const actual = document.querySelector(".pos-receipt .pos-receipt-client").textContent;
            if (actual !== expected) {
                throw new Error(`expected client line "${expected}", got "${actual}"`);
            }
        },
    };
}

/**
 * The client line sits directly under the block holding "Served by".
 *
 * Position is the whole point of the feature, so asserting the name is
 * somewhere on the receipt would not be asserting much.
 */
function clientLineFollowsTheCashier() {
    return {
        content: "the client line comes straight after the cashier block",
        trigger: ".pos-receipt .pos-receipt-contact + .pos-receipt-client",
    };
}

/**
 * The name is printed once.
 *
 * The core receipt prints the customer name unlabelled a few lines lower; this
 * module removes that line and prints it labelled instead. Counting guards the
 * removal - without it the receipt would carry the name twice and nothing else
 * in the suite would notice.
 */
function nameIsPrintedOnce(name) {
    return {
        content: `${name} is printed exactly once on the receipt`,
        trigger: ".pos-receipt",
        run: () => {
            const receipt = document.querySelector(".pos-receipt");
            const found = receipt.textContent.split(name).length - 1;
            if (found !== 1) {
                throw new Error(`expected '${name}' once on the receipt, found ${found}`);
            }
        },
    };
}

/** The VAT table is headed by the four columns, in order. */
function vatSummaryHeadersAre(headers) {
    return {
        content: `the VAT summary is headed ${headers.join(" / ")}`,
        trigger: ".pos-receipt .pos-receipt-vat-summary thead tr",
        run: () => {
            const cells = [
                ...document.querySelectorAll(".pos-receipt-vat-summary thead th"),
            ].map((cell) => cell.textContent.trim());
            const expected = headers.join("|");
            if (cells.join("|") !== expected) {
                throw new Error(`expected headers ${expected}, got ${cells.join("|")}`);
            }
        },
    };
}

/** The VAT table holds one row, reading the given four figures. */
function vatSummaryRowIs(rate, vat, exVat, total) {
    return {
        content: `the VAT summary reads ${rate} / ${vat} / ${exVat} / ${total}`,
        trigger: ".pos-receipt .pos-receipt-vat-summary tbody tr",
        run: () => {
            const rows = document.querySelectorAll(".pos-receipt-vat-summary tbody tr");
            if (rows.length !== 1) {
                throw new Error(`expected a single VAT row, found ${rows.length}`);
            }
            const cells = [...rows[0].querySelectorAll("td")].map((cell) =>
                cell.textContent.trim()
            );
            const expected = [rate, vat, exVat, total].join("|");
            if (cells.join("|") !== expected) {
                throw new Error(`expected ${expected}, got ${cells.join("|")}`);
            }
        },
    };
}

/**
 * The receipt is laid out in the direction under test.
 *
 * The receipt declares its own direction rather than inheriting the page's,
 * and rtlcss flips that declaration when the Arabic bundle is built. Reading
 * the computed style is therefore the only honest way to tell whether an
 * Arabic cashier really gets a mirrored ticket - without it the RTL run would
 * pass while printing a left-to-right receipt.
 */
function receiptDirectionIs(direction) {
    return {
        content: `the receipt is laid out ${direction}`,
        trigger: ".pos-receipt-container .pos-receipt",
        run: () => {
            const container = document.querySelector(".pos-receipt-container");
            const actual = getComputedStyle(container).direction;
            if (actual !== direction) {
                throw new Error(`expected a ${direction} receipt, got ${actual}`);
            }
        },
    };
}

/** Figures stay left to right even on a mirrored receipt. */
function figuresReadLeftToRight() {
    return {
        content: "the VAT figures are not mirrored with the table",
        trigger: ".pos-receipt .pos-receipt-vat-summary tbody td",
        run: () => {
            const cells = [...document.querySelectorAll(".pos-receipt-vat-summary tbody td")];
            const wrong = cells.filter(
                (cell) => getComputedStyle(cell).direction !== "ltr"
            );
            if (wrong.length) {
                throw new Error(`${wrong.length} VAT figures are not left to right`);
            }
        },
    };
}

// The English run: the full receipt, labels and figures included.
registry.category("web_tour.tours").add("custom_pos_receipt_tour", {
    steps: () =>
        [
            sellOneProduct(),
            clientLineIsLabelled("Client:"),
            clientLineNames(CUSTOMER),
            clientLineReads("Client: Billy Fox"),
            clientLineFollowsTheCashier(),
            nameIsPrintedOnce(CUSTOMER),
            vatSummaryHeadersAre(["VAT%", "VAT", "ExVAT", "Total"]),
            vatSummaryRowIs("15 %", "12.75", "85.00", "97.75"),
            receiptDirectionIs("ltr"),
            figuresReadLeftToRight(),
            Chrome.endTour(),
        ].flat(),
});

// The Arabic run: the same receipt, mirrored, with the label translated. The
// figures are asserted unchanged, because a translated receipt that quietly
// reformatted the money would be a bug, not a feature.
registry.category("web_tour.tours").add("custom_pos_receipt_rtl_tour", {
    steps: () =>
        [
            sellOneProduct(),
            receiptDirectionIs("rtl"),
            clientLineIsLabelled("العميل:"),
            clientLineNames(CUSTOMER),
            clientLineReads("العميل: Billy Fox"),
            clientLineFollowsTheCashier(),
            nameIsPrintedOnce(CUSTOMER),
            vatSummaryHeadersAre(["نسبة الضريبة", "الضريبة", "قبل الضريبة", "الإجمالي"]),
            vatSummaryRowIs("15 %", "12.75", "85.00", "97.75"),
            figuresReadLeftToRight(),
            Chrome.endTour(),
        ].flat(),
});
