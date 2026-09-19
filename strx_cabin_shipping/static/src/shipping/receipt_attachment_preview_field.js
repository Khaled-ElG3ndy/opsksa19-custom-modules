/** @odoo-module **/

import { FileModel } from "@web/core/file_viewer/file_model";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { url } from "@web/core/utils/urls";
import {
    Many2ManyBinaryField,
    many2ManyBinaryField,
} from "@web/views/fields/many2many_binary/many2many_binary_field";

const MIMETYPE_BY_EXTENSION = {
    bmp: "image/bmp",
    gif: "image/gif",
    jpeg: "image/jpeg",
    jpg: "image/jpeg",
    png: "image/png",
    svg: "image/svg+xml",
    tif: "image/tiff",
    tiff: "image/tiff",
    webp: "image/webp",
    pdf: "application/pdf",
    txt: "text/plain",
    csv: "text/plain",
    mp4: "video/mp4",
    webm: "video/webm",
};

export class StrxReceiptAttachmentPreviewField extends Many2ManyBinaryField {
    static template = "strx_cabin_shipping.ReceiptAttachmentPreviewField";
    static components = Many2ManyBinaryField.components;

    setup() {
        super.setup();
        this.fileViewer = useFileViewer();
    }

    get uploadButtonText() {
        return _t("Upload attachments");
    }

    getNormalizedMimetype(file) {
        if (file.mimetype && file.mimetype.includes("/")) {
            return file.mimetype;
        }
        return MIMETYPE_BY_EXTENSION[this.getExtension(file).toLowerCase()] || file.mimetype || "";
    }

    getFileModel(file) {
        return Object.assign(new FileModel(), {
            id: file.id,
            filename: file.name,
            name: file.name,
            mimetype: this.getNormalizedMimetype(file),
            type: "binary",
        });
    }

    getFileKind(file) {
        const model = this.getFileModel(file);
        if (model.isImage) {
            return "image";
        }
        if (model.isPdf) {
            return "pdf";
        }
        if (model.isVideo) {
            return "video";
        }
        if (model.isText) {
            return "text";
        }
        return "file";
    }

    getFileKindLabel(file) {
        const labels = {
            image: _t("Image"),
            pdf: _t("PDF document"),
            video: _t("Video"),
            text: _t("Text document"),
            file: _t("File"),
        };
        return labels[this.getFileKind(file)];
    }

    getFileIcon(file) {
        const icons = {
            pdf: "fa-file-pdf-o",
            video: "fa-file-video-o",
            text: "fa-file-text-o",
            file: "fa-file-o",
        };
        return icons[this.getFileKind(file)] || icons.file;
    }

    getImageUrl(file) {
        return url(`/web/image/${file.id}`, { width: 720, height: 420 });
    }

    getPreviewLabel(file) {
        return _t("Preview %s", file.name);
    }

    getPreviewActionLabel(file) {
        return this.getFileModel(file).isViewable ? _t("Preview") : _t("Open");
    }

    openPreview(file) {
        const previewFiles = this.files.map((attachment) => this.getFileModel(attachment));
        const currentFile = previewFiles.find((attachment) => attachment.id === file.id);
        if (currentFile.isViewable) {
            this.fileViewer.open(currentFile, previewFiles);
            return;
        }

        const link = document.createElement("a");
        link.href = currentFile.defaultSource;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.click();
    }

    onPreviewKeydown(ev, file) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.openPreview(file);
        }
    }
}

export const strxReceiptAttachmentPreviewField = {
    ...many2ManyBinaryField,
    component: StrxReceiptAttachmentPreviewField,
};

registry
    .category("fields")
    .add("strx_receipt_attachment_preview", strxReceiptAttachmentPreviewField);
