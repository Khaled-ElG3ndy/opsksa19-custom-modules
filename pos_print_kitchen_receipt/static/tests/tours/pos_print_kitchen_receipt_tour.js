// Copyright 2026 Khaled ElGendy. All rights reserved.

import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import { registry } from "@web/core/registry";

// Every product, category and setting below is created by the Python test, so
// the steps key off data and off the module's own CSS classes rather than off
// interface wording.
const BURGER = "Kitchen Burger";
const FRIES = "Kitchen Fries";
const COLA = "Kitchen Cola";
const FOOD_CATEGORY = "Kitchen Food";
const DRINKS_CATEGORY = "Kitchen Drinks";

/** Open the register and ring up the three test products. */
function ringUpTheOrder() {
    return [
        Chrome.startPoS(),
        Dialog.confirm(),
        ProductScreen.clickDisplayedProduct(BURGER),
        ProductScreen.clickDisplayedProduct(FRIES),
        ProductScreen.clickDisplayedProduct(COLA),
    ].flat();
}

/** The control button the module adds to the product screen. */
function kitchenReceiptButtonIsThere() {
    return {
        content: "the kitchen receipt button is on the product screen",
        trigger: ".kitchen-receipt-button",
    };
}

function clickKitchenReceiptButton() {
    return {
        content: "click the kitchen receipt button",
        trigger: ".kitchen-receipt-button",
        run: "click",
    };
}

function kitchenReceiptScreenIsShown() {
    return {
        content: "the kitchen receipt screen is shown",
        trigger: ".kitchen-receipt-screen .kitchen-receipt",
    };
}

/** A category heading is printed, and it reads this. */
function categoryHeadingIs(name) {
    return {
        content: `a category heading reads "${name}"`,
        trigger: `.kitchen-receipt .kitchen-category:contains("${name}")`,
    };
}

/**
 * Exactly this many category headings are printed.
 *
 * Counted rather than merely looked for: the whole point of the exclusion
 * setting is that a category disappears, and "Food is present" would still
 * hold on a receipt that also printed Drinks.
 */
function categoryHeadingCountIs(expected) {
    return {
        content: `${expected} category heading(s) are printed`,
        trigger: ".kitchen-receipt",
        run: () => {
            const actual = document.querySelectorAll(
                ".kitchen-receipt .kitchen-category"
            ).length;
            if (actual !== expected) {
                throw new Error(`expected ${expected} category heading(s), got ${actual}`);
            }
        },
    };
}

function productIsOnTheReceipt(name) {
    return {
        content: `"${name}" is on the kitchen receipt`,
        trigger: `.kitchen-receipt .kitchen-product-name:contains("${name}")`,
    };
}

/** Nothing on the receipt mentions this text at all. */
function receiptDoesNotMention(text) {
    return {
        content: `the kitchen receipt does not mention "${text}"`,
        trigger: ".kitchen-receipt",
        run: () => {
            const receipt = document.querySelector(".kitchen-receipt");
            if (receipt.textContent.includes(text)) {
                throw new Error(`the kitchen receipt should not mention "${text}"`);
            }
        },
    };
}

function customerNoteIsPrinted(note) {
    return {
        content: `the customer note "${note}" is printed under its line`,
        trigger: `.kitchen-receipt .pos-receipt-customer-note:contains("${note}")`,
    };
}

function quantityIsPrintedFor(name, quantity) {
    return {
        content: `"${name}" is printed with quantity ${quantity}`,
        trigger: `.kitchen-receipt .kitchen-product-name:contains("${name}")`,
        run: () => {
            const cell = [
                ...document.querySelectorAll(".kitchen-receipt .kitchen-product-name"),
            ].find((node) => node.textContent.includes(name));
            const qty = cell
                .closest("tr")
                .querySelector(".kitchen-product-qty")
                .textContent.trim();
            if (qty !== String(quantity)) {
                throw new Error(`expected quantity ${quantity} for ${name}, got "${qty}"`);
            }
        },
    };
}

function clickBack() {
    return {
        content: "leave the kitchen receipt screen",
        trigger: ".kitchen-receipt-screen button.discard",
        run: "click",
    };
}

// -- category-wise receipt, with one category excluded ---------------------
//
// The reference run: Food is grouped under its own heading, Drinks is left out
// entirely because the configuration excludes it, and the customer note and
// the quantities travel with the lines.
registry.category("web_tour.tours").add("pos_print_kitchen_receipt_tour", {
    steps: () =>
        [
            ringUpTheOrder(),
            // The note has to land on a line the receipt keeps, so the burger is
            // selected first; the last product rung up is the excluded drink.
            ProductScreen.clickLine(BURGER),
            ProductScreen.addCustomerNote("No onions"),
            kitchenReceiptButtonIsThere(),
            clickKitchenReceiptButton(),
            kitchenReceiptScreenIsShown(),
            categoryHeadingCountIs(1),
            categoryHeadingIs(FOOD_CATEGORY),
            productIsOnTheReceipt(BURGER),
            productIsOnTheReceipt(FRIES),
            receiptDoesNotMention(COLA),
            receiptDoesNotMention(DRINKS_CATEGORY),
            customerNoteIsPrinted("No onions"),
            quantityIsPrintedFor(BURGER, 1),
            clickBack(),
            ProductScreen.isShown(),
            Chrome.endTour(),
        ].flat(),
});

// -- the plain receipt ----------------------------------------------------
//
// With category-wise mode off, the receipt is one flat list and the category
// exclusions do not apply: leaving Cola off here would silently drop it from
// the kitchen's copy of the order.
registry.category("web_tour.tours").add("pos_print_kitchen_receipt_flat_tour", {
    steps: () =>
        [
            ringUpTheOrder(),
            clickKitchenReceiptButton(),
            kitchenReceiptScreenIsShown(),
            categoryHeadingCountIs(0),
            productIsOnTheReceipt(BURGER),
            productIsOnTheReceipt(FRIES),
            productIsOnTheReceipt(COLA),
            Chrome.endTour(),
        ].flat(),
});

// -- the setting actually gates the button --------------------------------
registry.category("web_tour.tours").add("pos_print_kitchen_receipt_disabled_tour", {
    steps: () =>
        [
            ringUpTheOrder(),
            {
                content: "no kitchen receipt button when the setting is off",
                trigger: ".product-screen",
                run: () => {
                    if (document.querySelector(".kitchen-receipt-button")) {
                        throw new Error(
                            "the kitchen receipt button is shown although the setting is off"
                        );
                    }
                },
            },
            Chrome.endTour(),
        ].flat(),
});

// -- an empty order is refused, not printed blank -------------------------
registry.category("web_tour.tours").add("pos_print_kitchen_receipt_empty_order_tour", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm(),
            kitchenReceiptButtonIsThere(),
            clickKitchenReceiptButton(),
            Dialog.is({ title: "No Product Selected" }),
            Dialog.confirm(),
            ProductScreen.isShown(),
            Chrome.endTour(),
        ].flat(),
});
