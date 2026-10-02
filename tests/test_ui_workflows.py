"""User-journey regressions for recovery, final approval, and edited drafts."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from streamlit.testing.v1 import AppTest
from dhaga_os.db import get_engine, get_session_factory, initialize_database, recent_support_cases


class OperatorJourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.keys = ("MODEL_MODE", "GEMINI_API_KEY", "DATABASE_URL", "VERCEL", "DHAGA_APP_PASSWORD", "SQLITE_PATH")
        self.old = {key: os.environ.get(key) for key in self.keys}
        os.environ.update(MODEL_MODE="demo", GEMINI_API_KEY="", DATABASE_URL="", VERCEL="", DHAGA_APP_PASSWORD="", SQLITE_PATH=str(Path(self.temp.name) / "journey.sqlite"))
        self.clear_database_cache()
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
        self.assertFalse(self.app.exception)

    @staticmethod
    def clear_database_cache():
        get_session_factory.cache_clear()
        get_engine.cache_clear()
        initialize_database.cache_clear()

    def tearDown(self):
        self.clear_database_cache()
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def button(self, label):
        return next(item for item in self.app.button if item.label == label)

    def select(self, label):
        return next(item for item in self.app.selectbox if item.label == label)

    def check(self, label):
        return next(item for item in self.app.checkbox if label in item.label)

    def field(self, label):
        return next(item for item in self.app.text_input if item.label == label)

    def test_catalog_approval_survives_reload_without_replacing_saved_work(self):
        self.button("Go to product listings").click().run()
        self.button("Load sample products").click().run()
        self.assertFalse(self.app.exception)
        self.select("Show products").set_value("Ready to review").run()
        key = self.select("Product to review").value
        self.check("compared").check()
        self.button("Approve product").click().run()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.error)
        self.button("Load sample products").click().run()
        record = next(row for row in self.app.session_state["catalog_batch"] if row["row_key"] == key)
        self.assertEqual(record["status"], "approved")
        self.assertEqual(len(self.app.session_state["catalog_batch"]), 26)
        self.select("Show products").set_value("Approved").run()
        self.assertFalse(self.app.exception)
        self.assertNotIn("Approve product", [item.label for item in self.app.button])

    def test_missing_fabric_generates_reviewable_copy_and_recovers_exact_selected_draft(self):
        self.button("Go to product listings").click().run()
        self.button("Load sample products").click().run()
        selected_key = self.select("Product to review").value
        self.select("Fabric or material (required)").set_value("Other — enter below")
        self.field("Other fabric (fill only when choosing Other)").set_value("Modal knit")
        self.check("compared").check()
        self.button("Save draft").click().run()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.error)
        record = next(row for row in self.app.session_state["catalog_batch"] if row["row_key"] == selected_key)
        self.assertEqual(record["fabric_composition"], "Modal knit")
        self.assertTrue(record["generated_copy"]["description_hinglish"])
        self.assertFalse(self.check("compared").value)
        self.app.radio[0].set_value("Overview").run()
        self.button("Go to product listings").click().run()
        self.select("Choose a saved product").set_value(selected_key)
        self.button("Open this draft").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.select("Product to review").value, selected_key)
        self.assertEqual(self.select("Fabric or material (required)").value, "Modal knit")

    def test_edited_reply_saves_recovers_and_rechecks_the_selected_customer_message(self):
        self.button("Go to customer messages").click().run()
        self.button("Track an order").click().run()
        self.button("Check order & prepare reply").click().run()
        self.assertFalse(self.app.exception)
        result = self.app.session_state["support_case"]
        original_message = result["ticket_text"]
        case_id = result["case_id"]
        area = next(item for item in self.app.text_area if item.label == "Reply for your team to review")
        changed = area.value + " Please share any further questions with our team."
        area.set_value(changed)
        self.button("Save reply draft").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(next(row for row in recent_support_cases() if row["case_id"] == case_id)["draft_reply"], changed)
        self.button("Order number is missing").click().run()
        self.select("Choose a saved message").set_value(case_id)
        self.button("Open this message").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(next(item for item in self.app.text_area if item.label == "Message").value, original_message)
        self.assertEqual(next(item for item in self.app.text_area if item.label == "Reply for your team to review").value, changed)
        self.check("checked this reply").check().run()
        next(item for item in self.app.text_area if item.label == "Reply for your team to review").set_value(changed + " Thank you.").run()
        self.assertFalse(self.check("checked this reply").value)
        self.assertTrue(self.button("Approve for team").disabled)
        self.check("checked this reply").check().run()
        self.button("Approve for team").click().run()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.error)
        self.assertEqual(self.app.session_state["support_case"]["status"], "approved_for_handoff")


if __name__ == "__main__":
    unittest.main()
