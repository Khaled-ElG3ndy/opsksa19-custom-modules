/** @odoo-module **/

import { registry } from "@web/core/registry";
import { getCurrency } from "@web/core/currency";
import { nbsp } from "@web/core/utils/strings";
import { formatMonetary } from "@web/views/fields/formatters";
import { parseMonetary } from "@web/views/fields/parsers";
import { useInputField } from "@web/views/fields/input_field_hook";
import { useNumpadDecimal } from "@web/views/fields/numpad_decimal_hook";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

import { Component } from "@odoo/owl";

export class StrxAgreedCostField extends Component {
    static template = "strx_cabin_shipping.AgreedCostField";
    static props = {
        ...standardFieldProps,
        currencyField: { type: String, optional: true },
        placeholder: { type: String, optional: true },
    };

    setup() {
        this.inputRef = useInputField({
            getValue: () => this.formattedInputValue,
            refName: "numpadDecimal",
            parse: (value) => this.parse(value),
        });
        useNumpadDecimal();
    }

    parse(value) {
        return value && value.trim() ? parseMonetary(value) : 0;
    }

    get currencyId() {
        const currencyField =
            this.props.currencyField ||
            this.props.record.fields[this.props.name].currency_field ||
            "currency_id";
        const currency = this.props.record.data[currencyField];
        return currency && currency[0];
    }

    get currency() {
        if (!isNaN(this.currencyId)) {
            return getCurrency(this.currencyId) || null;
        }
        return null;
    }

    get currencySymbol() {
        return this.currency ? this.currency.symbol : "";
    }

    get currencyDigits() {
        return this.currency ? this.currency.digits : null;
    }

    get value() {
        const value = this.props.record.data[this.props.name];
        return value === false || value === undefined || value === null ? 0 : value;
    }

    get formattedInputValue() {
        return formatMonetary(this.value, {
            digits: this.currencyDigits,
            minDigits: 2,
            currencyId: this.currencyId,
            noSymbol: true,
        });
    }

    get formattedReadonlyValue() {
        return formatMonetary(this.value, {
            digits: this.currencyDigits,
            minDigits: 2,
            currencyId: this.currencyId,
        });
    }

    get placeholder() {
        return this.props.placeholder || `0.00${nbsp}${this.currencySymbol || ""}`;
    }
}

export const strxAgreedCostField = {
    component: StrxAgreedCostField,
    supportedTypes: ["monetary", "float"],
    extractProps: ({ attrs, options }) => ({
        currencyField: options.currency_field,
        placeholder: attrs.placeholder,
    }),
};

registry.category("fields").add("strx_agreed_cost", strxAgreedCostField);
