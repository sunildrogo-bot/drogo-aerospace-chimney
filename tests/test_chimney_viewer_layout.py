"""Static checks for 3D inspection viewer and compact file toolbar.

Run: python -m unittest discover -s tests -v
A real desktop and mobile browser smoke test is still needed before release.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class ChimneyViewerLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / 'templates/chimney_project.html').read_text()
        cls.viewer = (ROOT / 'static/js/chimney_viewer.js').read_text()
        cls.assets = (ROOT / 'static/js/chimney_assets.js').read_text()

    def test_compact_files_menu_preserves_upload_handlers(self):
        self.assertEqual(self.html.count('id="chim-assets"'), 1)
        self.assertEqual(self.html.count('id="chim-files-menu"'), 1)
        self.assertLess(self.html.index('id="chim-files-dropdown"'),
                        self.html.index('id="map-style-dropdown"'))
        self.assertLess(self.html.index('id="chim-files-menu"'),
                        self.html.index('id="chim-assets"'))
        for id_ in ('chim-assets-input','chim-assets-list',
                    'chim-assets-progress','chim-assets-progress-value',
                    'chim-assets-status'):
            self.assertIn(f'id="{id_}"', self.html)
        self.assertIn('window.toggleChimneyFilesMenu', self.assets)
        self.assertIn('window.closeChimneyFilesMenu', self.assets)

    def test_compass_reflows_and_avoids_panels(self):
        self.assertIn("['chim-toolbar-panel', 'defect-form']", self.viewer)
        self.assertIn("'ResizeObserver' in window", self.viewer)
        self.assertIn('compass.hidden = !choice', self.viewer)
        self.assertIn('ring.replaceChildren()', self.viewer)
        self.assertIn('Math.round(norm) % 360', self.viewer)
        self.assertIn('function setCompassVisible() { positionCompass(); }', self.viewer)

    def test_map_style_and_attribution(self):
        for kind in ('dark','satellite','osm'):
            self.assertIn(f'id="ms-switch-{kind}" role="radio"', self.html)
        self.assertIn('id="chim-map-attribution"', self.html)
        self.assertIn('openstreetmap.org/copyright', self.html)
        self.assertNotIn('cesium-credit-lightbox-overlay{display:none', self.html)
        self.assertNotIn("creditContainer.style.display = 'none'", self.viewer)

    def test_client_measure_safe_and_report_fallback(self):
        self.assertIn(
            "document.getElementById('btn-add-defect')?.classList.remove('active');",
            self.viewer)
        self.assertIn('Straight-line:', self.viewer)
        self.assertIn("if (!tab) {", self.viewer)

if __name__ == '__main__':
    unittest.main()
