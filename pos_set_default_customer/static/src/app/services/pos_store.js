import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    /**
     * Preselect the customer configured on this Point of Sale.
     *
     * Core calls this when it builds a new order and when it looks for a
     * reusable empty one, so returning the configured customer here is enough
     * to both set it and keep an untouched order recognised as empty.
     *
     * `default_customer_id` resolves to a record only once that partner has
     * been loaded in the session; falling back to `super` keeps the stock
     * behaviour (and any other module's) if it has not.
     *
     * @override
     * @returns {number|null} id of the partner to preselect
     */
    getDefaultPartnerId() {
        return this.config.default_customer_id?.id ?? super.getDefaultPartnerId();
    },
});
