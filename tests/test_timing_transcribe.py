from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from explainer_studio.common import ProjectError
from explainer_studio.timing import transcribe


class TranscribeScriptHintTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "assets").mkdir()
        (self.root / "assets" / "voice.mp3").write_bytes(b"voice")
        self.data = self.root / "studio-data" / "explainer"
        self.data.mkdir(parents=True)
        (self.data / "project.json").write_text(json.dumps({"voice": "assets/voice.mp3"}), encoding="utf-8")
        segment = types.SimpleNamespace(words=[types.SimpleNamespace(word="Hello", start=0.2, end=0.4)])
        self.model = MagicMock()
        self.model.transcribe.return_value = ([segment], None)
        self.whisper = types.ModuleType("faster_whisper")
        self.whisper.WhisperModel = MagicMock(return_value=self.model)
        self.modules = patch.dict("sys.modules", {"faster_whisper": self.whisper})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def run_transcribe(self, *args, **kwargs):
        with patch("explainer_studio.timing.probe_duration", return_value=1.0):
            return transcribe(self.root, *args, **kwargs)

    def test_project_script_guides_selected_model_and_language(self):
        (self.data / "script.txt").write_text("Tingnan mo kung buhay pa siya.", encoding="utf-8")

        self.assertEqual(self.run_transcribe("medium", "tl"), 1)

        self.whisper.WhisperModel.assert_called_once_with("medium", device="cpu", compute_type="int8")
        self.model.transcribe.assert_called_once_with(
            str(self.root / "assets" / "voice.mp3"), language="tl", word_timestamps=True,
            vad_filter=True, initial_prompt="Tingnan mo kung buhay pa siya.",
        )

    def test_script_argument_overrides_project_script(self):
        (self.data / "script.txt").write_text("Project version", encoding="utf-8")
        hint = self.root / "approved-script.txt"
        hint.write_text("Approved version", encoding="utf-8")

        self.run_transcribe(script=hint)

        self.assertEqual(self.model.transcribe.call_args.kwargs["initial_prompt"], "Approved version")

    def test_empty_script_does_not_pass_prompt(self):
        (self.data / "script.txt").write_text("  \n  ", encoding="utf-8")

        self.run_transcribe()

        self.assertNotIn("initial_prompt", self.model.transcribe.call_args.kwargs)

    def test_missing_explicit_script_fails_before_model_load(self):
        with self.assertRaisesRegex(ProjectError, "missing transcription script"):
            self.run_transcribe(script=self.root / "missing.txt")

        self.whisper.WhisperModel.assert_not_called()


if __name__ == "__main__":
    unittest.main()
