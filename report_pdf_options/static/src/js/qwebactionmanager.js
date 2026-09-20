import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";
import { getReportUrl } from "@web/webclient/actions/reports/utils";
import { PdfOptionsModal } from "./PdfOptionsModal";

/**
 * Handlers in the "ir.actions.report handlers" registry are called as
 * handler(action, options, env), and the return value decides what happens:
 *
 *   truthy - we handled the report; the action service stops and only takes
 *            care of close_on_report_download / onClose.
 *   falsy  - we are not interested; the action service runs its own path,
 *            which already does downloadReport() with the merged user context,
 *            the ui block/unblock, the wkhtmltopdf notification, and the
 *            fallback to the HTML client action.
 *
 * So every branch we do not want to own is a `return false` rather than a
 * reimplementation of what the action service already does.
 */

let iframe;

/** Load the pdf in a hidden iframe and print it from there. */
function printPdf(url) {
    return new Promise((resolve) => {
        if (!iframe) {
            iframe = document.createElement("iframe");
            iframe.className = "pdfIframe";
            iframe.style.display = "none";
            document.body.appendChild(iframe);
        }
        // Reassign on every call: the handler closes over this call's resolve,
        // and keeping the previous one would settle an earlier promise instead.
        iframe.onload = () => {
            setTimeout(() => {
                iframe.contentWindow.focus();
                iframe.contentWindow.print();
                resolve();
            }, 1);
        };
        iframe.src = url;
    });
}

/** Ask the user, resolving to "print" | "download" | "open" | "close". */
async function askPrintOption(env) {
    let removeDialog;
    const choice = await new Promise((resolve) => {
        removeDialog = env.services.dialog.add(
            PdfOptionsModal,
            { onSelectOption: resolve },
            { onClose: () => resolve("close") }
        );
    });
    removeDialog();
    return choice;
}

/**
 * The handler itself, exported and holding its own cache.
 *
 * The wkhtmltopdf status is asked for once per browser session, as core's
 * `downloadReport` does. Core keeps that cache on the function object rather
 * than in a module variable precisely so a test can clear it and exercise more
 * than one status; the same is done here.
 */
export async function pdfReportOptionsHandler(action, options, env) {
    if (action.report_type !== "qweb-pdf") {
        return false;
    }

    let choice = action.default_print_option;
    if (choice === "download") {
        return false; // the action service downloads it
    }
    if (!choice) {
        choice = await askPrintOption(env);
        if (choice === "close") {
            return true; // dismissed on purpose, nothing left to do
        }
        if (choice === "download") {
            return false;
        }
    }
    if (choice !== "print" && choice !== "open") {
        return false;
    }

    // Open the tab while the browser still considers this a direct user
    // gesture. Waiting for the wkhtmltopdf RPC first makes popup blockers
    // reject window.open() in several browsers.
    const openedWindow = choice === "open" ? window.open("about:blank", "_blank") : null;

    // Both remaining options need a real pdf, so the renderer has to be
    // usable. On anything else hand back to the action service, which
    // shows the proper message and falls back to the HTML report.
    pdfReportOptionsHandler.wkhtmltopdfStatusProm ||= rpc("/report/check_wkhtmltopdf");
    let status;
    try {
        status = await pdfReportOptionsHandler.wkhtmltopdfStatusProm;
    } catch (error) {
        openedWindow?.close();
        throw error;
    }
    if (!["ok", "upgrade"].includes(status)) {
        openedWindow?.close();
        return false;
    }

    const context = { ...user.context, ...(action.context || {}) };
    const url = getReportUrl(action, "pdf", context);

    if (choice === "print") {
        env.services.ui.block();
        try {
            await printPdf(url);
        } finally {
            env.services.ui.unblock();
        }
    } else {
        if (openedWindow) {
            openedWindow.location.href = url;
        } else {
            // A strict popup policy may still deny the pre-open. Keep the
            // legacy attempt as a best-effort fallback.
            window.open(url, "_blank");
        }
    }
    return true;
}

registry
    .category("ir.actions.report handlers")
    .add("pdf_report_options_handler", pdfReportOptionsHandler);
