import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fetch


class AnalyticsHQPipelineTests(unittest.TestCase):
    def test_placeholder_property_ids_are_rejected(self):
        placeholder_sites = [
            {"id": "site1", "property_id_env": "", "numeric_property_id": "GA4_PROPERTY_ID_1"},
            {"id": "site2", "property_id_env": "", "numeric_property_id": "G-XXXXXXXXXX"},
            {"id": "site3", "property_id_env": "", "numeric_property_id": "TBD"},
            {"id": "site4", "property_id_env": "", "numeric_property_id": "not-a-number"},
        ]

        for site in placeholder_sites:
            with self.subTest(site=site):
                self.assertIsNone(fetch.resolve_property_id(site, {}))

    def test_env_property_id_override_is_used(self):
        site = {
            "id": "primary",
            "property_id_env": "GA4_PROPERTY_ID_PRIMARY",
            "numeric_property_id": "",
        }

        self.assertEqual(
            fetch.resolve_property_id(site, {"GA4_PROPERTY_ID_PRIMARY": "123456789"}),
            "123456789",
        )

    def test_committed_root_page_is_connector_first(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("Connect GA4. Ship stakeholder reports automatically.", html)
        self.assertIn("Live metrics appear after connection.", html)

        lowered = html.lower()
        self.assertNotIn("sample output", lowered)
        self.assertNotIn("fictional", lowered)
        self.assertNotIn("northwind", lowered)
        self.assertNotIn("cascadia", lowered)
        self.assertNotIn("mesa supply", lowered)


if __name__ == "__main__":
    unittest.main()
