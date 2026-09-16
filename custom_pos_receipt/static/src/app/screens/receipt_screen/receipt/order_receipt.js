import { patch } from "@web/core/utils/patch";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { accountTaxHelpers } from "@account/helpers/account_tax";
import { formatCurrency } from "@web/core/currency";
import { formatFloat } from "@web/core/utils/numbers";

/**
 * VAT summary printed at the foot of the Point of Sale receipt.
 *
 * One row per tax, holding its rate, the tax charged, the amount it was
 * charged on and the two added together, so the four columns of a row are
 * always arithmetically consistent with each other.
 *
 * Per tax, and deliberately not per tax group: the Saudi chart puts 15% and
 * the zero-rated taxes in one "VAT Total Amount" group, so a per-group table
 * would print a single blended rate for an order that carries both. Grouping
 * is done by Odoo's own aggregation, only with a different key, so the figures
 * are the ones the order was actually taxed on.
 */
patch(OrderReceipt.prototype, {
    /**
     * Rows of the VAT summary table, already formatted for printing.
     *
     * Empty when the order carries no tax at all, which is what keeps the
     * table off a receipt that has nothing to summarise.
     */
    get vatSummaryRows() {
        const prices = this.order.prices;
        if (!prices?.taxDetails?.has_tax_groups || !prices.baseLines) {
            return [];
        }

        const perTax = accountTaxHelpers.aggregate_base_lines_aggregated_values(
            accountTaxHelpers.aggregate_base_lines_tax_details(
                prices.baseLines,
                // A base line with no tax is grouped under a null key and
                // dropped below; it has no rate to print.
                (baseLine, taxData) => (taxData ? taxData.tax.id : null)
            )
        );

        const taxes = this.order.models["account.tax"];
        const rows = [];
        for (const values of Object.values(perTax)) {
            const tax = values.grouping_key && taxes.get(values.grouping_key);
            if (!tax) {
                continue;
            }
            const base = values.base_amount_currency || 0;
            const taxAmount = values.tax_amount_currency || 0;
            rows.push({
                sequence: tax.sequence,
                id: tax.id,
                rate: this.formatVatRate(tax, base, taxAmount),
                tax: this.formatVatAmount(taxAmount),
                base: this.formatVatAmount(base),
                total: this.formatVatAmount(base + taxAmount),
            });
        }

        // Same order the taxes are applied in, so a receipt printed twice
        // reads the same way, and the rows follow the order the tax lines
        // above them are already printed in.
        return rows.sort((a, b) => a.sequence - b.sequence || a.id - b.id);
    },

    /**
     * The rate to print for one tax.
     *
     * A percentage tax states its own rate, and that is the number the
     * customer expects to read ("15 %"). Anything else - a fixed amount per
     * unit, a division tax - declares no rate, so one is derived from the
     * amounts actually charged. Deriving it rather than leaving the cell blank
     * keeps the row readable, and it can only ever agree with the VAT and
     * ExVAT columns printed beside it.
     */
    formatVatRate(tax, base, taxAmount) {
        let rate;
        if (tax.amount_type === "percent") {
            rate = tax.amount;
        } else {
            // A fully discounted line taxes nothing; there is no rate to show.
            rate = base ? (taxAmount / base) * 100 : 0;
        }
        // The sign is joined here rather than in the template so the markup
        // does not offer a bare "%" to the translation extractor.
        return `${formatFloat(rate, { digits: [false, 2], trailingZeros: false })} %`;
    },

    /**
     * Amounts in the table are bare numbers, as the columns are headed by what
     * they hold and the currency is already printed on the total above.
     */
    formatVatAmount(amount) {
        return formatCurrency(amount, this.order.currency.id, { noSymbol: true });
    },
});
