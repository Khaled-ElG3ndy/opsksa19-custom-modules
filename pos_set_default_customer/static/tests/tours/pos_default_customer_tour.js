import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import * as PaymentScreen from "@point_of_sale/../tests/pos/tours/utils/payment_screen_util";
import * as ReceiptScreen from "@point_of_sale/../tests/pos/tours/utils/receipt_screen_util";
import { registry } from "@web/core/registry";

// The default customer configured on the Point of Sale must already be on the
// order the session opens with, survive a full sale, and come back on the next
// order -- without the cashier ever opening the customer list.
registry.category("web_tour.tours").add("pos_default_customer_tour", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            ProductScreen.isShown(),

            // The opening order already carries the configured customer.
            ProductScreen.customerIsSelected("Default POS Customer"),

            ProductScreen.clickDisplayedProduct("Whiteboard Pen"),
            ProductScreen.customerIsSelected("Default POS Customer"),

            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod("Bank"),
            PaymentScreen.clickValidate(),
            ReceiptScreen.isShown(),
            ReceiptScreen.clickNextOrder(),

            // ... and so does the order that follows it.
            ProductScreen.isShown(),
            ProductScreen.customerIsSelected("Default POS Customer"),

            Chrome.endTour(),
        ].flat(),
});
