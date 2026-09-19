import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { deserializeDateTime, formatDate, formatDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { Pager } from "@web/core/pager/pager";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { KeepLast } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";

import { DocumentCenterFile } from "./document_center_file";
import { EditDocumentDialog } from "./edit_document_dialog";
import { UploadDocumentDialog } from "./upload_document_dialog";

const DEFAULT_LIMIT = 40;

export class DocumentCenter extends Component {
    static template = "partner_document_center.DocumentCenter";
    static components = { Dropdown, DropdownItem, Pager };
    static props = {
        partnerId: { type: [Number, Boolean] },
        partnerName: { type: String, optional: true },
        // The form-view tab is height-constrained; the client action is not.
        inline: { type: Boolean, optional: true },
    };
    static defaultProps = { inline: false, partnerName: "" };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.fileViewer = useFileViewer();
        // Filters change faster than round-trips complete; only the newest
        // answer is allowed to reach the screen.
        this.keepLast = new KeepLast();

        this.state = useState({
            loading: true,
            error: false,
            documents: [],
            total: 0,
            kpi: {
                total: 0, record: 0, attachment: 0,
                pdf: 0, image: 0, document: 0, other: 0,
                size: 0, latest_date: false,
            },
            sources: [],
            categories: [],
            scopeAvailable: false,
            truncated: false,
            viewMode: "grid",
            groupBy: "none",
            filters: this.defaultFilters,
        });

        this.onSearchInput = useDebounced((ev) => {
            this.state.filters.search = ev.target.value;
            this.state.filters.offset = 0;
            this.load();
        }, 350);

        onWillStart(() => this.load());
        onWillUpdateProps((nextProps) => {
            if (nextProps.partnerId !== this.props.partnerId) {
                this.state.filters = this.defaultFilters;
                this.load(nextProps.partnerId);
            }
        });
    }

    get defaultFilters() {
        return {
            scope: "self",
            source: "all",
            doc_kind: "all",
            file_type: "all",
            date_range: "all",
            date_from: false,
            date_to: false,
            search: "",
            category_id: false,
            important_only: false,
            order: "date_desc",
            offset: 0,
            limit: DEFAULT_LIMIT,
        };
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------
    async load(partnerId = this.props.partnerId) {
        if (!partnerId) {
            this.state.loading = false;
            return;
        }
        this.state.loading = true;
        this.state.error = false;
        try {
            const result = await this.keepLast.add(
                this.orm.call("res.partner", "action_fetch_documents", [
                    [partnerId],
                    { ...this.state.filters },
                ])
            );
            this.state.documents = result.documents.map((data) => new DocumentCenterFile(data));
            this.state.total = result.total;
            this.state.kpi = result.kpi;
            this.state.sources = result.sources;
            this.state.categories = result.categories;
            this.state.scopeAvailable = result.scope_available;
            this.state.truncated = result.truncated;
        } catch {
            this.state.error = true;
        } finally {
            this.state.loading = false;
        }
    }

    async reload() {
        await this.load();
    }

    // ------------------------------------------------------------------
    // Filtering
    // ------------------------------------------------------------------
    setFilter(key, value) {
        this.state.filters[key] = value;
        this.state.filters.offset = 0;
        this.load();
    }

    toggleImportantOnly() {
        this.setFilter("important_only", !this.state.filters.important_only);
    }

    toggleScope() {
        this.setFilter("scope", this.state.filters.scope === "self" ? "commercial" : "self");
    }

    clearFilters() {
        this.state.filters = this.defaultFilters;
        this.load();
    }

    get hasActiveFilters() {
        const f = this.state.filters;
        return Boolean(
            f.search ||
                f.source !== "all" ||
                f.doc_kind !== "all" ||
                f.file_type !== "all" ||
                f.date_range !== "all" ||
                f.category_id ||
                f.important_only
        );
    }

    get docKindOptions() {
        return [
            { value: "all", label: _t("All"), count: this.state.kpi.total },
            { value: "record", label: _t("Business Documents"), count: this.state.kpi.record },
            { value: "attachment", label: _t("Attachments"), count: this.state.kpi.attachment },
        ];
    }

    onPagerUpdate({ offset, limit }) {
        this.state.filters.offset = offset;
        this.state.filters.limit = limit;
        this.load();
    }

    // ------------------------------------------------------------------
    // Labels for the filter menus
    // ------------------------------------------------------------------
    get fileTypeOptions() {
        return [
            { value: "all", label: _t("All types") },
            { value: "pdf", label: _t("PDF") },
            { value: "image", label: _t("Images") },
            { value: "excel", label: _t("Excel") },
            { value: "word", label: _t("Word") },
            { value: "other", label: _t("Other") },
        ];
    }

    get dateOptions() {
        return [
            { value: "all", label: _t("Any date") },
            { value: "today", label: _t("Today") },
            { value: "week", label: _t("This week") },
            { value: "month", label: _t("This month") },
            { value: "year", label: _t("This year") },
            { value: "custom", label: _t("Custom range") },
        ];
    }

    get orderOptions() {
        return [
            { value: "date_desc", label: _t("Newest first") },
            { value: "date_asc", label: _t("Oldest first") },
            { value: "name_asc", label: _t("Filename A-Z") },
            { value: "name_desc", label: _t("Filename Z-A") },
            { value: "size_desc", label: _t("Largest first") },
            { value: "size_asc", label: _t("Smallest first") },
            { value: "source", label: _t("Source") },
        ];
    }

    get groupByOptions() {
        return [
            { value: "none", label: _t("No grouping") },
            { value: "record", label: _t("Business document") },
            { value: "source", label: _t("Source") },
            { value: "category", label: _t("Category") },
        ];
    }

    labelFor(options, value) {
        return options.find((option) => option.value === value)?.label || options[0].label;
    }

    get currentFileTypeLabel() {
        return this.labelFor(this.fileTypeOptions, this.state.filters.file_type);
    }

    get currentDateLabel() {
        return this.labelFor(this.dateOptions, this.state.filters.date_range);
    }

    get currentOrderLabel() {
        return this.labelFor(this.orderOptions, this.state.filters.order);
    }

    get currentCategoryLabel() {
        const id = this.state.filters.category_id;
        if (!id) {
            return _t("All categories");
        }
        return this.state.categories.find((c) => c.id === id)?.name || _t("All categories");
    }

    // ------------------------------------------------------------------
    // Presentation
    // ------------------------------------------------------------------
    formatSize(bytes) {
        if (!bytes) {
            return "0 KB";
        }
        const units = ["B", "KB", "MB", "GB", "TB"];
        let index = 0;
        let value = bytes;
        while (value >= 1024 && index < units.length - 1) {
            value /= 1024;
            index++;
        }
        return `${value < 10 && index > 0 ? value.toFixed(1) : Math.round(value)} ${units[index]}`;
    }

    formatDocumentDate(value) {
        if (!value) {
            return "";
        }
        return formatDate(deserializeDateTime(value));
    }

    formatDocumentDateTime(value) {
        if (!value) {
            return "";
        }
        return formatDateTime(deserializeDateTime(value));
    }

    /**
     * Groups for the current page.
     *
     * Grouping is applied to the page the server returned, not to the whole
     * result set: the sort and the pagination stay authoritative server-side,
     * and the client never asks for every doc just to draw headers.
     */
    get groups() {
        const documents = this.state.documents;
        if (this.state.viewMode !== "timeline" && this.state.groupBy === "none") {
            return [{ key: "all", label: "", documents }];
        }
        const groups = new Map();
        for (const doc of documents) {
            const { key, label } = this.groupKeyFor(doc);
            if (!groups.has(key)) {
                groups.set(key, { key, label, documents: [] });
            }
            groups.get(key).documents.push(doc);
        }
        if (this.state.groupBy === "record" && this.state.viewMode !== "timeline") {
            // Put the live document first inside its own group, so its files
            // read as belonging to it rather than sitting beside it.
            for (const group of groups.values()) {
                group.documents.sort((a, b) => Number(b.isRecord) - Number(a.isRecord));
            }
        }
        return [...groups.values()];
    }

    groupKeyFor(doc) {
        if (this.state.viewMode === "timeline") {
            return this.dateBucketFor(doc);
        }
        if (this.state.groupBy === "record") {
            // Files and the record they hang on share a group_key, so an
            // invoice and its scans land under one heading.
            return {
                key: doc.groupKey,
                label: doc.sourceDisplayName
                    ? `${doc.sourceLabel} ${doc.sourceDisplayName}`
                    : doc.sourceLabel,
            };
        }
        if (this.state.groupBy === "source") {
            return { key: doc.sourceCode, label: doc.sourceLabel };
        }
        if (this.state.groupBy === "category") {
            return {
                key: doc.categoryId || "none",
                label: doc.categoryName || _t("Uncategorised"),
            };
        }
        return { key: "all", label: "" };
    }

    dateBucketFor(doc) {
        const date = doc.createDate ? deserializeDateTime(doc.createDate) : null;
        if (!date) {
            return { key: "unknown", label: _t("Undated") };
        }
        const today = luxon.DateTime.now().startOf("day");
        const day = date.startOf("day");
        const days = today.diff(day, "days").days;
        if (days <= 0) {
            return { key: "today", label: _t("Today") };
        }
        if (days === 1) {
            return { key: "yesterday", label: _t("Yesterday") };
        }
        if (days < 7) {
            return { key: "week", label: _t("Earlier this week") };
        }
        return { key: date.toFormat("yyyy-MM"), label: date.toFormat("LLLL yyyy") };
    }

    // ------------------------------------------------------------------
    // Per-doc actions
    // ------------------------------------------------------------------
    onDocumentClick(doc) {
        if (doc.isViewable) {
            this.fileViewer.open(
                doc,
                this.state.documents.filter((d) => d.isViewable)
            );
        } else if (doc.isRecord) {
            // Nothing to preview without a report: go to the record instead.
            this.openSource(doc);
        } else {
            window.open(doc.downloadUrl, "_blank");
        }
    }

    async openSource(doc) {
        try {
            const action = doc.isRecord
                ? await this.orm.call("partner.document.center", "action_open_live_document", [
                      doc.sourceModel,
                      doc.sourceRecordId,
                  ])
                : await this.orm.call("partner.document.center", "action_open_source", [doc.id]);
            await this.action.doAction(action);
        } catch (error) {
            this.notification.add(error.data?.message || _t("This document cannot be opened."), {
                type: "warning",
            });
        }
    }

    /**
     * Print a live document.
     *
     * The report is rendered from the record at this moment, by Odoo's own
     * report action - the Document Center never holds a generated PDF.
     */
    async printDocument(doc) {
        try {
            const action = await this.orm.call(
                "partner.document.center",
                "action_print_live_document",
                [doc.sourceModel, doc.sourceRecordId]
            );
            await this.action.doAction(action);
        } catch (error) {
            this.notification.add(error.data?.message || _t("This document cannot be printed."), {
                type: "warning",
            });
        }
    }

    /** Narrow the list to one business record and the files hanging on it. */
    focusOnRecord(doc) {
        this.state.filters.source = `src:${doc.sourceCode}`;
        this.state.filters.doc_kind = "all";
        this.state.filters.search = doc.sourceDisplayName || doc.name;
        this.state.filters.offset = 0;
        this.state.groupBy = "record";
        this.load();
    }

    async toggleImportant(doc) {
        const next = !doc.isImportant;
        await this.orm.call("partner.document.center", "action_set_metadata", [
            doc.id,
            { is_important: next },
        ]);
        doc.isImportant = next;
        if (this.state.filters.important_only) {
            await this.reload();
        }
    }

    editDocument(doc) {
        this.dialog.add(EditDocumentDialog, {
            doc,
            categories: this.state.categories,
            onSaved: () => this.reload(),
        });
    }

    deleteDocument(doc) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete document"),
            body: _t('"%s" will be permanently deleted.', doc.name),
            confirmLabel: _t("Delete"),
            confirmClass: "btn-danger",
            confirm: async () => {
                await this.orm.call("partner.document.center", "action_delete", [doc.id]);
                await this.reload();
            },
            cancel: () => {},
        });
    }

    openUploadDialog() {
        this.dialog.add(UploadDocumentDialog, {
            partnerId: this.props.partnerId,
            categories: this.state.categories,
            sources: this.state.sources,
            onUploaded: () => this.reload(),
        });
    }
}
