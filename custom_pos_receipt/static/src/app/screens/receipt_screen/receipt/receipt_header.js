import { patch } from "@web/core/utils/patch";
import { ReceiptHeader } from "@point_of_sale/app/screens/receipt_screen/receipt/receipt_header/receipt_header";

/**
 * The client named on the Point of Sale receipt.
 *
 * Composed here rather than in the template so the template can print it on a
 * single line: OWL drops a whitespace-only text node that spans a line break,
 * so a name assembled across several template lines loses the spaces between
 * its parts.
 */
patch(ReceiptHeader.prototype, {
    /**
     * The customer's name, prefixed by the company they belong to.
     *
     * Empty when the order has no customer, which is what keeps the client
     * line off a walk-in sale's receipt.
     */
    get clientName() {
        const partner = this.order.partner_id;
        if (!partner?.name) {
            return "";
        }
        // The core receipt named the company this way before this module took
        // the line over; dropping it would lose which company was served.
        return partner.parent_name ? `${partner.parent_name}, ${partner.name}` : partner.name;
    },
});
