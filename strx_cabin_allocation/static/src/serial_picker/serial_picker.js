/** @odoo-module **/

import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { onWillStart } from "@odoo/owl";

// The autocomplete option carries only a display name, so the readiness state
// has to be read back out of the label. The label is translated, so the mapping
// is fetched from the field's own selection in the user's language instead of a
// hardcoded English/Arabic table - which silently lost the colour coding in any
// other language.
function parseSerialLabel(label, stateByLabel) {
    const text = (label || "").split("\n")[0].trim();
    const match = text.match(/^(.*?)\s*\[([^\]]+)\]\s*$/);
    if (!match) {
        return false;
    }
    const serial = match[1].trim();
    const stateLabel = match[2].trim();
    const stateClass = stateByLabel[stateLabel.toLowerCase()] || stateByLabel[stateLabel];
    if (!serial || !stateClass) {
        return false;
    }
    return { serial, stateLabel, stateClass };
}

patch(Many2XAutocomplete.prototype, {
    setup() {
        super.setup();
        this.strxStateByLabel = {};
        if (this.props.resModel === "stock.lot" && this.props.context?.strx_selection_label) {
            const orm = useService("orm");
            onWillStart(async () => {
                const fields = await orm.call(
                    "stock.lot", "fields_get",
                    [["strx_readiness_state"], ["selection"]]);
                for (const [key, label] of fields.strx_readiness_state?.selection || []) {
                    this.strxStateByLabel[String(label).toLowerCase()] = key;
                    this.strxStateByLabel[label] = key;
                }
            });
        }
    },

    get optionsSource() {
        const source = super.optionsSource;
        if (this.props.resModel === "stock.lot" && this.props.context?.strx_selection_label) {
            return {
                ...source,
                optionTemplate: "strx_cabin_allocation.SerialPickerAutocompleteOption",
            };
        }
        return source;
    },

    mapRecordToOption(result) {
        const option = super.mapRecordToOption(result);
        if (this.props.resModel !== "stock.lot" || !this.props.context?.strx_selection_label) {
            return option;
        }
        const serialLabel = parseSerialLabel(option.label, this.strxStateByLabel);
        if (!serialLabel) {
            return option;
        }
        return {
            ...option,
            label: serialLabel.serial,
            strxSerialStateLabel: serialLabel.stateLabel,
            strxSerialStateClass: serialLabel.stateClass,
            classList: [
                option.classList,
                "o_strx_serial_picker_dropdown_item",
                `o_strx_serial_state_${serialLabel.stateClass}`,
            ].filter(Boolean).join(" "),
        };
    },
});
