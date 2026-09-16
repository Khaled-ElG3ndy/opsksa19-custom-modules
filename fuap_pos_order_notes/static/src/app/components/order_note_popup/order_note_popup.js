import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { localization } from "@web/core/l10n/localization";

export class OrderNotePopup extends Component {
    static template = "fuap_pos_order_notes.OrderNotePopup";
    static components = { Dialog };
    static props = {
        title: String,
        startingValue: { type: String, optional: true },
        tags: { type: Array, optional: true },
        getPayload: Function,
        close: Function,
    };
    static defaultProps = {
        startingValue: "",
        tags: [],
    };

    setup() {
        this.state = useState({ value: this.props.startingValue });
        this.inputRef = useRef("orderNoteInput");
        onMounted(() => {
            const input = this.inputRef.el;
            input.focus();
            input.setSelectionRange(input.value.length, input.value.length);
        });
    }

    get direction() {
        return localization.direction;
    }

    addTag(tag) {
        const value = this.state.value.trim();
        const parts = value
            .split(/\s*(?:,|\n)\s*/)
            .map((part) => part.trim())
            .filter(Boolean);
        if (!parts.includes(tag.name)) {
            this.state.value = value ? `${value}, ${tag.name}` : tag.name;
        }
        this.inputRef.el.focus();
    }

    save() {
        this.props.getPayload(this.state.value.trim());
        this.props.close();
    }

    cancel() {
        this.props.close();
    }
}

