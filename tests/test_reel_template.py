import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "library" / "templates" / "reel-shot-plan"


class ReelTemplateTest(unittest.TestCase):
    def test_template_documents_scene_beats_and_native_attach_flow(self):
        guide = (TEMPLATE_DIR / "README.md").read_text(encoding="utf-8")
        scene = (TEMPLATE_DIR / "scene.html").read_text(encoding="utf-8")

        self.assertIn("scene-composition", guide)
        self.assertIn("{{SCENE_DURATION}}", scene)
        self.assertIn("{{PROJECT_WIDTH}}", scene)
        self.assertIn("{{PROJECT_HEIGHT}}", scene)
        self.assertIn("{{COMPOSITION_ID}}", scene)
        for selector in (".packet", ".route-bad", ".route-good", "#loopback-path"):
            self.assertIn(selector, scene)
        self.assertIn('id="sample-count"', scene)
        self.assertIn("window.__timelines", scene)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the template script syntax check")
    def test_template_gsap_script_has_valid_javascript_syntax(self):
        scene = (TEMPLATE_DIR / "scene.html").read_text(encoding="utf-8")
        script = re.search(r"<script>\s*(.*?)\s*</script>", scene, re.DOTALL).group(1)
        script = script.replace("{{COMPOSITION_ID}}", "starter-scene")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scene.js"
            path.write_text(script, encoding="utf-8")
            subprocess.run([shutil.which("node"), "--check", str(path)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
