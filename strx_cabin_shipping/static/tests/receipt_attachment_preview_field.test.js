import {
    defineMailModels,
    mailModels,
} from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import { setInputFiles } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    contains,
    defineModels,
    fields,
    MockServer,
    mockService,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

class ShippingPreviewTest extends models.Model {
    _name = "strx.shipping.preview.test";

    receipt_attachment_ids = fields.Many2many({
        string: "Receipt Attachments",
        relation: "ir.attachment",
    });

    _records = [{ id: 1, receipt_attachment_ids: [17, 18] }];
}

defineMailModels();
defineModels([ShippingPreviewTest]);
mailModels.IrAttachment._records = [
    { id: 17, name: "signed-receipt.png", mimetype: "image/png" },
    { id: 18, name: "delivery-proof.pdf", mimetype: "application/pdf" },
];

test("receipt attachments are clear and previewable", async () => {
    await mountView({
        type: "form",
        resModel: "strx.shipping.preview.test",
        resId: 1,
        arch: `
            <form>
                <field name="receipt_attachment_ids" widget="strx_receipt_attachment_preview"/>
            </form>`,
    });

    expect(".o_strx_receipt_attachment_card").toHaveCount(2);
    expect(".o_strx_receipt_attachment_name:eq(0)").toHaveText("signed-receipt.png");
    expect(".o_strx_receipt_attachment_name:eq(1)").toHaveText("delivery-proof.pdf");
    expect(".o_strx_receipt_attachment_media img").toHaveCount(1);
    expect(".o_strx_receipt_attachment_icon.o_kind_pdf").toHaveCount(1);
    expect(".o_strx_receipt_upload").toHaveCount(1);

    await contains(".o_strx_receipt_attachment_card:eq(0)").click();
    expect(".o-FileViewer").toHaveCount(1);
    expect(".o-FileViewer-header").toHaveText(/signed-receipt\.png/);
});

test("a newly uploaded attachment appears immediately", async () => {
    mockService("http", () => ({
        post(route, { ufile }) {
            expect(route).toBe("/web/binary/upload_attachment");
            const ids = MockServer.env["ir.attachment"].create(
                ufile.map(({ name }) => ({ name, mimetype: "image/jpeg" }))
            );
            return JSON.stringify(MockServer.env["ir.attachment"].read(ids));
        },
    }));

    await mountView({
        type: "form",
        resModel: "strx.shipping.preview.test",
        resId: 1,
        arch: `
            <form>
                <field name="receipt_attachment_ids" widget="strx_receipt_attachment_preview"/>
            </form>`,
    });

    const uploadedFile = new File(["receipt"], "receipt-just-uploaded.jpg", {
        type: "image/jpeg",
    });
    await contains(".o_file_input_trigger").click();
    await setInputFiles([uploadedFile]);
    await animationFrame();

    expect(".o_strx_receipt_attachment_card").toHaveCount(3);
    expect(".o_strx_receipt_attachment_name:eq(2)").toHaveText("receipt-just-uploaded.jpg");
});

test("readonly receipt attachments keep previews and hide edit controls", async () => {
    await mountView({
        type: "form",
        resModel: "strx.shipping.preview.test",
        resId: 1,
        arch: `
            <form>
                <field name="receipt_attachment_ids"
                       widget="strx_receipt_attachment_preview"
                       readonly="1"/>
            </form>`,
    });

    expect(".o_strx_receipt_attachment_card").toHaveCount(2);
    expect(".o_strx_receipt_upload").toHaveCount(0);
    expect(".o_strx_receipt_attachment_delete").toHaveCount(0);

    await contains(".o_strx_receipt_attachment_card:eq(1)").click();
    expect(".o-FileViewer").toHaveCount(1);
    expect(".o-FileViewer-header").toHaveText(/delivery-proof\.pdf/);
    expect("iframe.o-FileViewer-view").toHaveCount(1);
});
