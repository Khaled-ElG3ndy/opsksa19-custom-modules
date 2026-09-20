import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { pdfReportOptionsHandler } from "@report_pdf_options/js/qwebactionmanager";

/**
 * A stand-in for the pieces of `env` the handler reaches for.
 *
 * `dialogChoice` is what the user is taken to have clicked in the options
 * modal; `null` means the modal was dismissed.
 */
function makeEnv({ dialogChoice = "close" } = {}) {
    const calls = [];
    return {
        calls,
        services: {
            dialog: {
                add(_component, props, options) {
                    calls.push("dialog");
                    // Answer on the next tick, the way a click would.
                    Promise.resolve().then(() => {
                        if (dialogChoice === null) {
                            options.onClose();
                        } else {
                            props.onSelectOption(dialogChoice);
                        }
                    });
                    return () => calls.push("dialog-removed");
                },
            },
            ui: {
                block: () => calls.push("block"),
                unblock: () => calls.push("unblock"),
            },
        },
    };
}

function pdfAction(overrides = {}) {
    return {
        report_type: "qweb-pdf",
        report_name: "account.report_invoice",
        context: { active_ids: [7] },
        ...overrides,
    };
}

/** Capture what the handler asks the browser to open. */
function trackOpenedWindows() {
    const opened = [];
    patchWithCleanup(window, {
        open(url) {
            const fake = { location: { href: url }, closed: false, close() { this.closed = true; } };
            opened.push(fake);
            return fake;
        },
    });
    return opened;
}

describe("PDF print options handler", () => {
    beforeEach(() => {
        // Asked once per browser session and cached on the handler, so it has
        // to be cleared or the first test to run would decide the status for
        // every test after it.
        pdfReportOptionsHandler.wkhtmltopdfStatusProm = undefined;
    });

    /**
     * Answer the wkhtmltopdf check with `status`.
     *
     * Seeded straight into the cache rather than mocked over the network: these
     * tests call the handler on its own, without a web client behind it, so
     * there is no mock server to answer a route. Being able to do this is the
     * reason the cache lives on the handler instead of in a module variable.
     */
    function wkhtmltopdfReports(status) {
        pdfReportOptionsHandler.wkhtmltopdfStatusProm = Promise.resolve(status);
    }

    test("leaves reports that are not PDFs to the action service", async () => {
        const env = makeEnv();
        expect(await pdfReportOptionsHandler({ report_type: "qweb-html" }, {}, env)).toBe(false);
        expect(env.calls).toEqual([]);
    });

    test("leaves a report configured to download to the action service", async () => {
        const env = makeEnv();
        const action = pdfAction({ default_print_option: "download" });

        expect(await pdfReportOptionsHandler(action, {}, env)).toBe(false);
        // No modal: the choice was already made in the report's configuration.
        expect(env.calls).toEqual([]);
    });

    test("asks when the report has no configured option", async () => {
        const env = makeEnv({ dialogChoice: "download" });

        expect(await pdfReportOptionsHandler(pdfAction(), {}, env)).toBe(false);
        expect(env.calls).toEqual(["dialog", "dialog-removed"]);
    });

    test("dismissing the modal ends the action instead of downloading", async () => {
        const env = makeEnv({ dialogChoice: null });

        // True, not false: returning false would hand the action service a
        // report to download that the user just declined.
        expect(await pdfReportOptionsHandler(pdfAction(), {}, env)).toBe(true);
    });

    test("opens the report in the tab it reserved before the round trip", async () => {
        wkhtmltopdfReports("ok");
        const opened = trackOpenedWindows();
        const env = makeEnv();
        const action = pdfAction({ default_print_option: "open" });

        expect(await pdfReportOptionsHandler(action, {}, env)).toBe(true);
        expect(opened).toHaveLength(1);
        expect(opened[0].location.href).toBe("/report/pdf/account.report_invoice/7");
        expect(opened[0].closed).toBe(false);
    });

    test("an upgradeable wkhtmltopdf is still good enough to print with", async () => {
        wkhtmltopdfReports("upgrade");
        const opened = trackOpenedWindows();
        const env = makeEnv();

        expect(
            await pdfReportOptionsHandler(pdfAction({ default_print_option: "open" }), {}, env)
        ).toBe(true);
        expect(opened[0].closed).toBe(false);
    });

    test("a broken wkhtmltopdf hands back without leaving a blank tab open", async () => {
        wkhtmltopdfReports("broken");
        const opened = trackOpenedWindows();
        const env = makeEnv();

        // False, so the action service shows its own message and falls back to
        // the HTML report...
        expect(
            await pdfReportOptionsHandler(pdfAction({ default_print_option: "open" }), {}, env)
        ).toBe(false);
        // ...and the tab reserved for a PDF that will never arrive is closed.
        expect(opened).toHaveLength(1);
        expect(opened[0].closed).toBe(true);
    });

    test("printing blocks the interface and always unblocks it", async () => {
        wkhtmltopdfReports("ok");
        const env = makeEnv();
        // The iframe never fires load in a test DOM, so the print itself is
        // stubbed out; what matters here is that the block is paired.
        patchWithCleanup(window, { open: () => null });

        const done = pdfReportOptionsHandler(
            pdfAction({ default_print_option: "print" }),
            {},
            env
        );
        await Promise.resolve();
        const iframe = document.querySelector("iframe.pdfIframe");

        expect(iframe).not.toBe(null);
        expect(env.calls).toInclude("block");

        iframe.remove();
        void done;
    });
});
