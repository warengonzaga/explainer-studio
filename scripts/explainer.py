"""Run the bundled engine directly from a plugin checkout."""

import json
import os
import subprocess
import sys
from pathlib import Path


def in_managed_venv(home: Path, prefix: Path) -> bool:
    """Return whether prefix resolves to the managed Studio virtual environment."""
    venv = os.path.normcase((home / "venv").resolve())
    current = os.path.normcase(Path(prefix).resolve())
    return venv == current


def _exit_incomplete_environment() -> None:
    """Tell the caller to bootstrap. --json stays on the shared result schema."""
    message = "The managed Studio environment is incomplete; run `explainer bootstrap`."
    if "--json" not in sys.argv[1:]:
        print(message, file=sys.stderr)
        return
    command_name = next((token for token in sys.argv[1:] if not token.startswith("-")), "")
    print(json.dumps({
        "ok": False,
        "command": command_name,
        "data": {},
        "next_steps": ["explainer bootstrap --json"],
        "error": message,
    }, ensure_ascii=False))


def launch() -> None:
    plugin_root = Path(__file__).resolve().parents[1]
    home = Path(os.environ.get("EXPLAINER_STUDIO_HOME", Path.home() / ".explainer-studio")).expanduser()
    managed_python = home / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if managed_python.is_file() and not in_managed_venv(home, Path(sys.prefix)):
        ready = subprocess.run([str(managed_python), "-c", "import explainer_studio"], capture_output=True)
        if ready.returncode == 0:
            command = [str(managed_python), str(Path(__file__).resolve()), *sys.argv[1:]]
            raise SystemExit(subprocess.run(command).returncode)
        if sys.argv[1:2] != ["bootstrap"]:
            _exit_incomplete_environment()
            raise SystemExit(1)

    sys.path.insert(0, str(plugin_root / "src"))
    if not os.environ.get("RHUBARB_PATH"):
        from explainer_studio.rhubarb import installed_rhubarb_path

        installed = installed_rhubarb_path(home)
        if installed.is_file():
            os.environ["RHUBARB_PATH"] = str(installed)
    from explainer_studio.cli import main

    raise SystemExit(main())


if __name__ == "__main__":
    launch()
