import unittest
from pathlib import Path

DASHBOARD_DIR = Path(__file__).parents[1] / "src" / "recall" / "dashboard"


class DashboardAssetsTests(unittest.TestCase):
    def test_dashboard_html_exposes_model_picker_and_general_knowledge_toggle(self):
        html = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('list="ask-model-options"', html)
        self.assertIn('id="ask-allow-general-knowledge"', html)
        self.assertIn('aria-controls="panel-search"', html)
        self.assertIn('aria-controls="panel-ask"', html)
        self.assertIn("RECALL_DASHBOARD_BOOTSTRAP", html)
        self.assertNotIn('/dashboard/config.js', html)

    def test_dashboard_js_uses_same_preview_renderer_for_search_and_ask(self):
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("renderPreviewCard(hit)", script)
        self.assertIn("renderPreviewCard(source, { reference: source.reference })", script)
        self.assertIn('button.setAttribute("aria-expanded", "false")', script)
        self.assertIn('apiRequest("/v1/models")', script)
        self.assertIn("allow_general_knowledge", script)
        self.assertIn('readMeta("recall-api-token")', script)
        self.assertIn('readMeta("recall-api-base")', script)
        self.assertNotIn("__RECALL_TOKEN__", script)

    def test_dashboard_js_avoids_unsafe_html_sinks(self):
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("insertAdjacentHTML", script)
