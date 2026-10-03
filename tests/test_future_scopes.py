"""The roadmap is navigable without processing or changing operator work."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from dhaga_os.cx_examples import load_cx_examples
from dhaga_os.db import get_engine, get_session_factory, initialize_database, workspace_counts


class FutureScopesNavigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {
            "MODEL_MODE": "demo",
            "GEMINI_API_KEY": "",
            "DATABASE_URL": "",
            "VERCEL": "",
            "SQLITE_PATH": str(Path(self.temp.name) / "future-scopes.sqlite"),
        })
        self.environment.start()
        self.clear_database_cache()

    def tearDown(self) -> None:
        self.clear_database_cache()
        self.environment.stop()
        self.temp.cleanup()

    @staticmethod
    def clear_database_cache() -> None:
        get_session_factory.cache_clear()
        get_engine.cache_clear()
        initialize_database.cache_clear()

    def test_future_scopes_is_read_only_and_preserves_an_unsubmitted_message(self) -> None:
        with patch("dhaga_os.model_gateway.generate_json") as model:
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
            self.assertFalse(app.exception)
            before = workspace_counts()
            message = "Keep this unsubmitted customer message for later."
            app.session_state["cx_ticket_text"] = message
            self.assertIn("Future scopes", app.radio[0].options)
            app.radio[0].set_value("Future scopes").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.radio[0].value, "Future scopes")
            self.assertEqual(len([item for item in app.expander if item.label.startswith("Phase ")]), 4)
            content = "\n".join(item.value for item in app.markdown)
            self.assertIn("Future scopes", content)
            self.assertIn("The MVP you can use today", "\n".join(item.value for item in app.subheader))
            self.assertIn("no delivery dates are committed", "\n".join(item.value for item in app.info))
            self.assertEqual(workspace_counts(), before)
            app.radio[0].set_value("Customer messages").run()
            self.assertFalse(app.exception)
            self.assertEqual(next(item for item in app.text_area if item.label == "Message").value, message)
            self.assertEqual(workspace_counts(), before)
            model.assert_not_called()

    def test_fresh_example_selection_preserves_edits_until_explicit_load(self) -> None:
        with patch("dhaga_os.model_gateway.generate_json") as model:
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
            app.radio[0].set_value("Customer messages").run()
            self.assertFalse(app.exception)
            before = workspace_counts()
            original = "An operator's unsaved message should stay here."
            next(item for item in app.text_area if item.label == "Message").set_value(original).run()
            examples = load_cx_examples()
            selector = next(item for item in app.selectbox if item.label == "Fresh message example")
            self.assertEqual(len(selector.options), 8)
            selector.set_value(examples[-1]["id"]).run()
            self.assertFalse(app.exception)
            self.assertEqual(next(item for item in app.text_area if item.label == "Message").value, original)
            next(item for item in app.button if item.label == "Load this fresh message").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(next(item for item in app.text_area if item.label == "Message").value, examples[-1]["message"])
            self.assertEqual(workspace_counts(), before)
            model.assert_not_called()
