import { FileModelMixin } from "@web/core/file_viewer/file_model";

/**
 * A Document Center row, adapted to what Odoo's own file viewer expects.
 *
 * Extending FileModelMixin rather than re-implementing preview gives us
 * `isViewable`, `defaultSource`, `downloadUrl` and the PDF/image handling that
 * the chatter already uses - no second preview engine, and no binary payload
 * in the list response: the viewer streams from /web/content/<id>, which
 * re-checks access server-side.
 */
export class DocumentCenterFile extends FileModelMixin(Object) {
    constructor(data) {
        super();
        this.update(data);
    }

    update(data) {
        this.kind = data.kind || "attachment";
        this.itemId = data.item_id;
        this.groupKey = data.group_key;
        this.id = data.attachment_id;
        this.name = data.name;
        this.mimetype = data.mimetype;
        this.checksum = data.checksum;
        this.type = data.type || "binary";
        this.url = data.url || undefined;
        this.extension = this.name?.includes(".") ? this.name.split(".").pop() : undefined;

        // Live business document: the card stands for the record itself.
        this.state = data.state;
        this.stateLabel = data.state_label || "";
        this.amountLabel = data.amount_label || "";
        this.currencyName = data.currency_name || "";
        this.writeDate = data.write_date || "";
        this.attachmentCount = data.attachment_count || 0;
        this.canPrint = Boolean(data.can_print);
        this.reportName = data.report_name || "";

        this.fileSize = data.file_size;
        this.fileType = data.file_type;
        this.createDate = data.create_date;
        this.description = data.description;

        this.sourceCode = data.source_code;
        this.sourceModel = data.source_model;
        this.sourceGroup = data.source_group;
        this.sourceRecordId = data.source_record_id;
        this.sourceLabel = data.source_label;
        this.sourceDisplayName = data.source_display_name;

        this.partnerId = data.partner_id;
        this.uploadedBy = data.uploaded_by;
        this.categoryId = data.category_id;
        this.categoryName = data.category_name;
        this.isImportant = data.is_important;

        this.canDownload = data.can_download;
        this.canOpenSource = data.can_open_source;
        this.canWrite = data.can_write;
        this.canDelete = data.can_delete;
        return this;
    }

    get isRecord() {
        return this.kind === "record";
    }

    /** Icon for the card. Live documents read differently from files on purpose. */
    get icon() {
        if (this.isRecord) {
            switch (this.sourceGroup) {
                case "accounting":
                    return "fa-file-text-o";
                case "purchase":
                    return "fa-shopping-cart";
                case "inventory":
                    return "fa-truck";
                case "sales":
                    return "fa-handshake-o";
                case "maintenance":
                    return "fa-wrench";
                case "rental":
                    return "fa-calendar-check-o";
                default:
                    return "fa-clipboard";
            }
        }
        switch (this.fileType) {
            case "pdf":
                return "fa-file-pdf-o";
            case "image":
                return "fa-file-image-o";
            case "excel":
                return "fa-file-excel-o";
            case "word":
                return "fa-file-word-o";
            default:
                return "fa-file-o";
        }
    }

    get thumbnailUrl() {
        // /web/image resizes server-side, so a grid of 40 photos does not pull
        // 40 full-resolution originals over the wire.
        return this.isImage && !this.isRecord
            ? `/web/image/${this.id}?height=160&width=280`
            : "";
    }

    // ------------------------------------------------------------------
    // Viewer plumbing
    //
    // A live document has no stored file. When its provider declares a report
    // we point the very same FileViewer at /report/pdf/<report>/<id>, which
    // Odoo renders from the record on each request - so the preview is always
    // the current document, and nothing is ever cached to show it.
    // ------------------------------------------------------------------
    get isPdf() {
        return this.isRecord ? this.canPrint : super.isPdf;
    }

    get isImage() {
        return this.isRecord ? false : super.isImage;
    }

    get isViewable() {
        return this.isRecord ? this.canPrint : super.isViewable;
    }

    get urlRoute() {
        if (this.isRecord) {
            return `/report/pdf/${this.reportName}/${this.sourceRecordId}`;
        }
        return super.urlRoute;
    }

    get urlQueryParams() {
        // The report controller takes no access_token/checksum; keep the URL
        // clean so it stays a plain, cacheable-by-nothing report request.
        return this.isRecord ? {} : super.urlQueryParams;
    }
}
