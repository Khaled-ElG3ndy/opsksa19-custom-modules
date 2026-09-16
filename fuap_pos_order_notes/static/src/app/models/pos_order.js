import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    setup(vals) {
        super.setup(vals);
        this.order_note = vals.order_note || "";
    },

    setOrderNote(note) {
        this.order_note = note || "";
    },
});

