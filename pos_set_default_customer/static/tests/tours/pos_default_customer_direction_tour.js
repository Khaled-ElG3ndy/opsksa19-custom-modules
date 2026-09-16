import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import { registry } from "@web/core/registry";

/**
 * Assert the session really is laid out in the direction under test.
 *
 * The Point of Sale screen carries no `dir` attribute: Odoo mirrors it by
 * serving the stylesheet through rtlcss, so the `.rtl.css` bundle in the page
 * is what says the cashier is working right to left. Checking it keeps the RTL
 * tour from quietly passing while running in LTR, which is the mistake that
 * makes "it supports RTL" untrue in practice.
 */
function sessionDirectionIs(direction) {
    return {
        content: `the session is laid out ${direction}`,
        trigger: "body",
        run: () => {
            const sheets = [...document.styleSheets].map((sheet) => sheet.href || "");
            const mirrored = sheets.some((href) => href.includes(".rtl."));
            if (mirrored !== (direction === "rtl")) {
                throw new Error(
                    `expected a ${direction} session, got stylesheets: ${sheets.join(", ")}`
                );
            }
        },
    };
}

// Every step below keys off a CSS selector or off customer data, never off
// interface text, so the same tour runs unchanged in Arabic and in English.
function directionTour(direction) {
    return [
        Chrome.startPoS(),
        Dialog.confirm(),
        ProductScreen.isShown(),
        sessionDirectionIs(direction),
        ProductScreen.customerIsSelected("Default POS Customer"),
        Chrome.endTour(),
    ].flat();
}

registry.category("web_tour.tours").add("pos_default_customer_rtl_tour", {
    steps: () => directionTour("rtl"),
});

registry.category("web_tour.tours").add("pos_default_customer_ltr_tour", {
    steps: () => directionTour("ltr"),
});
