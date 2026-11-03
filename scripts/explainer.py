"""Run the bundled engine directly from a plugin checkout."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explainer_studio.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
