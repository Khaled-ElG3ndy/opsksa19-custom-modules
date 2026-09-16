import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { OrderNotePopup } from "@fuap_pos_order_notes/app/components/order_note_popup/order_note_popup";

export class OrderNoteButton extends Component {
    static template = "fuap_pos_order_notes.OrderNoteButton";
    static props = {
        class: { type: String, optional: true },
        label: { type: String, optional: true },
    };
    static defaultProps = {
        label: "Order Note",
    };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
    }

    async onClick() {
        const order = this.pos.getOrder();
        const tags = this.pos.models["pos.order.note"]?.readAll() || [];
        const payload = await makeAwaitable(this.dialog, OrderNotePopup, {
            title: _t("Order Note"),
            startingValue: order.order_note || "",
            tags,
        });
        if (typeof payload === "string") {
            order.setOrderNote(payload);
        }
    }
}

ControlButtons.components = {
    ...ControlButtons.components,
    OrderNoteButton,
};

