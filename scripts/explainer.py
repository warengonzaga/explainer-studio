"""Run the bundled engine directly from a plugin checkout."""

from pathlib import Path
import os
import subprocess
import sys

plugin_root = Path(__file__).resolve().parents[1]
home = Path(os.environ.get("EXPLAINER_STUDIO_HOME", Path.home() / ".explainer-studio")).expanduser()
managed_python = home / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if managed_python.is_file() and managed_python.resolve() != Path(sys.executable).resolve():
    ready = subprocess.run([str(managed_python), "-c", "import explainer_studio"], capture_output=True)
    if ready.returncode == 0:
        raise SystemExit(subprocess.run([str(managed_python), str(Path(__file__).resolve()), *sys.argv[1:]]).returncode)
    if sys.argv[1:2] != ["bootstrap"]:
        print("The managed Studio environment is incomplete; run `explainer bootstrap`.", file=sys.stderr)
        raise SystemExit(1)

sys.path.insert(0, str(plugin_root / "src"))

from explainer_studio.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
