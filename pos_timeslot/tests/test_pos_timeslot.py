from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestPosTimeslot(TransactionCase):
    def test_adjacent_slots_match_and_overlap_is_rejected(self):
        morning = self.env["pos.timeslot"].create(
            {"name": "Morning", "time_from": 0.0, "time_to": 12.0}
        )
        afternoon = self.env["pos.timeslot"].create(
            {"name": "Afternoon", "time_from": 12.0, "time_to": 24.0}
        )

        with self.assertRaises(ValidationError):
            self.env["pos.timeslot"].create(
                {"name": "Overlap", "time_from": 11.0, "time_to": 13.0}
            )

        order = self.env["pos.order"].new({"user_id": self.env.user.id})
        self.assertIn(order._match_timeslot(morning | afternoon), morning | afternoon)

    def test_slot_bounds_are_validated(self):
        for time_from, time_to in [(-1.0, 1.0), (5.0, 5.0), (23.0, 25.0)]:
            with self.subTest(time_from=time_from, time_to=time_to):
                with self.assertRaises(ValidationError):
                    self.env["pos.timeslot"].create(
                        {
                            "name": "Invalid",
                            "time_from": time_from,
                            "time_to": time_to,
                        }
                    )

    def test_access_is_limited_to_pos_groups(self):
        accesses = self.env["ir.model.access"].search(
            [("model_id.model", "=", "pos.timeslot")]
        )
        self.assertTrue(accesses)
        self.assertTrue(all(access.group_id for access in accesses))
        by_group = {access.group_id: access for access in accesses}
        pos_user = self.env.ref("point_of_sale.group_pos_user")
        pos_manager = self.env.ref("point_of_sale.group_pos_manager")
        self.assertTrue(by_group[pos_user].perm_read)
        self.assertFalse(by_group[pos_user].perm_write)
        self.assertFalse(by_group[pos_user].perm_create)
        self.assertFalse(by_group[pos_user].perm_unlink)
        self.assertTrue(by_group[pos_manager].perm_read)
        self.assertTrue(by_group[pos_manager].perm_write)
        self.assertTrue(by_group[pos_manager].perm_create)
        self.assertTrue(by_group[pos_manager].perm_unlink)

    def test_sales_analysis_view_exposes_timeslot(self):
        self.assertIn("pos_timeslot_id", self.env["report.pos.order"]._fields)
        self.env.cr.execute(
            "SELECT pos_timeslot_id FROM report_pos_order LIMIT 0"
        )
