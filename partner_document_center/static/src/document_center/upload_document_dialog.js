import { Component, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

/**
 * "Upload a file" for the Document Center.
 *
 * The default - and the only destination that needs no extra decision - is the
 * contact itself. Attaching to a business document is deliberately a second,
 * explicit step, and the record list it offers is fetched server-side and
 * restricted to records that already belong to this contact.
 */
export class UploadDocumentDialog extends Component {
    static template = "partner_document_center.UploadDocumentDialog";
    static components = { Dialog };
    static props = {
        partnerId: { type: Number },
        categories: { type: Array },
        sources: { type: Array },
        onUploaded: { type: Function },
        close: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        this.fileUpload = useService("file_upload");
        this.notification = useService("notification");
        this.fileInputRef = useRef("fileInput");

        this.state = useState({
            destination: "partner",
            sourceCode: "",
            targetId: false,
            targetQuery: "",
            targetOptions: [],
            categoryId: false,
            fileName: "",
            uploading: false,
        });
    }

    /** Sources a file can be attached to: never the contact source itself. */
    get linkableSources() {
        const sources = [];
        for (const group of this.props.sources) {
            for (const source of group.sources) {
                if (source.code !== "partner" && source.count) {
                    sources.push({ ...source, groupLabel: group.label });
                }
            }
        }
        return sources;
    }

    get canLink() {
        return this.linkableSources.length > 0;
    }

    get canConfirm() {
        if (this.state.uploading || !this.state.fileName) {
            return false;
        }
        return this.state.destination === "partner" || Boolean(this.state.targetId);
    }

    onFileChange(ev) {
        this.state.fileName = ev.target.files?.[0]?.name || "";
    }

    async onSourceChange(ev) {
        this.state.sourceCode = ev.target.value;
        this.state.targetId = false;
        await this.searchTargets();
    }

    async onTargetQueryInput(ev) {
        this.state.targetQuery = ev.target.value;
        await this.searchTargets();
    }

    async searchTargets() {
        if (!this.state.sourceCode) {
            this.state.targetOptions = [];
            return;
        }
        this.state.targetOptions = await this.orm.call(
            "res.partner",
            "action_upload_document_target_records",
            [this.props.partnerId, this.state.sourceCode, this.state.targetQuery, 20]
        );
    }

    onDestinationChange(destination) {
        this.state.destination = destination;
        if (destination === "partner") {
            this.state.targetId = false;
        }
    }

    async confirm() {
        const files = this.fileInputRef.el?.files;
        if (!files?.length) {
            return;
        }
        this.state.uploading = true;

        const targetModel =
            this.state.destination === "record"
                ? this.linkableSources.find((s) => s.code === this.state.sourceCode)?.model
                : null;

        const upload = await this.fileUpload.upload(
            "/partner_document_center/upload",
            files,
            {
                buildFormData: (formData) => {
                    formData.append("partner_id", this.props.partnerId);
                    if (this.state.destination === "record" && this.state.targetId) {
                        formData.append("target_model", targetModel || "");
                        formData.append("target_id", this.state.targetId);
                    }
                    if (this.state.categoryId) {
                        formData.append("category_id", this.state.categoryId);
                    }
                },
            }
        );
        // The service registers its own "load" handler first and sets
        // upload.state there, so by the time this one runs the outcome is known.
        // Failures already surfaced a notification carrying the server message.
        upload.xhr.addEventListener("load", () => {
            this.state.uploading = false;
            if (upload.state === "loaded") {
                this.props.onUploaded();
                this.props.close();
            }
        });
        upload.xhr.addEventListener("error", () => {
            this.state.uploading = false;
        });
    }
}
