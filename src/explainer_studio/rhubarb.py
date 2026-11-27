"""Optional install of Rhubarb Lip Sync 1.14.0 for Linux and macOS."""

from __future__ import annotations

import hashlib
import hmac
import os
import platform
import shutil
import stat
import subprocess
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from .common import ProjectError, studio_home


RHUBARB_VERSION = "1.14.0"
_DOWNLOAD_LIMIT = 96 * 1024 * 1024
_MEMBER_LIMIT = 80 * 1024 * 1024
_EXTRACT_LIMIT = 250 * 1024 * 1024
RHUBARB_RELEASES = {
    ("Linux", "x86_64"): {
        "url": "https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/Rhubarb-Lip-Sync-1.14.0-Linux.zip",
        "sha256": "a9a9074862cff47b2d59b8bf399a678a3b0b74f9452ad6ad94cb292913dd8667",
        "root": "Rhubarb-Lip-Sync-1.14.0-Linux/",
    },
    ("Darwin", "x86_64"): {
        "url": "https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/Rhubarb-Lip-Sync-1.14.0-macOS.zip",
        "sha256": "f991deacac6c973a14a4431a16a58b842f436531e120cfaea142c87c0d3ab4c5",
        "root": "Rhubarb-Lip-Sync-1.14.0-macOS/",
    },
}


def installed_rhubarb_path(home: Path | None = None) -> Path:
    return (home or studio_home()) / "rhubarb" / RHUBARB_VERSION / "rhubarb"


def _release_for(system: str, machine: str) -> dict:
    release = RHUBARB_RELEASES.get((system, machine))
    if release:
        return release
    raise ProjectError(
        "optional Rhubarb install supports x86_64 Linux and macOS; "
        "set RHUBARB_PATH or pass --rhubarb-path for another platform"
    )


def _download(url: str, destination: Path, opener) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "explainer-studio"})
    digest = hashlib.sha256()
    try:
        with opener(request, timeout=180) as response, destination.open("wb") as output:
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _DOWNLOAD_LIMIT:
                    raise ProjectError("Rhubarb download is larger than expected")
                digest.update(chunk)
                output.write(chunk)
    except ProjectError:
        destination.unlink(missing_ok=True)
        raise
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        destination.unlink(missing_ok=True)
        raise ProjectError(f"could not download Rhubarb Lip Sync: {exc}") from exc
    return digest.hexdigest()


def _safe_members(archive: zipfile.ZipFile, root: str) -> list[zipfile.ZipInfo]:
    selected = []
    for info in archive.infolist():
        name = info.filename
        if name.startswith("/") or "\\" in name or ".." in Path(name).parts:
            raise ProjectError("Rhubarb archive has an unsafe path")
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise ProjectError("Rhubarb archive has an unsafe path")
        if not name.startswith(root):
            raise ProjectError("Rhubarb archive layout was not recognized")
        relative = name[len(root) :]
        if relative == "rhubarb" or relative.startswith("res/"):
            if info.file_size > _MEMBER_LIMIT:
                raise ProjectError("Rhubarb archive is larger than expected")
            selected.append(info)
    names = {info.filename[len(root) :] for info in selected}
    if "rhubarb" not in names:
        raise ProjectError("Rhubarb archive did not contain the executable")
    return selected


def _extract(archive_path: Path, staging: Path, root: str) -> None:
    extracted = 0
    with zipfile.ZipFile(archive_path) as archive:
        for info in _safe_members(archive, root):
            relative = info.filename[len(root) :]
            target = (staging / relative).resolve()
            if not target.is_relative_to(staging.resolve()):
                raise ProjectError("Rhubarb archive has an unsafe path")
            extracted += info.file_size
            if extracted > _EXTRACT_LIMIT:
                raise ProjectError("Rhubarb archive is larger than expected")
            if info.is_dir() or relative.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    binary = staging / "rhubarb"
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _version_matches(binary: Path) -> bool:
    if not binary.is_file():
        return False
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and RHUBARB_VERSION in result.stdout


def install_rhubarb(
    home: Path | None = None,
    *,
    system: str | None = None,
    machine: str | None = None,
    opener=urllib.request.urlopen,
) -> Path:
    """Download Rhubarb 1.14.0 into the Studio home and point RHUBARB_PATH at it."""
    home = (home or studio_home()).expanduser().resolve()
    release = _release_for(system or platform.system(), machine or platform.machine())
    destination = home / "rhubarb" / RHUBARB_VERSION
    binary = destination / "rhubarb"
    if destination.is_symlink() or binary.is_symlink():
        raise ProjectError("Rhubarb install directory must not be a symlink")
    if _version_matches(binary):
        os.environ["RHUBARB_PATH"] = str(binary)
        return binary

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f"{destination.name}.staging")
    archive_path = destination.with_name(f"{destination.name}.download")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        digest = _download(release["url"], archive_path, opener)
        if len(digest) != len(release["sha256"]) or not hmac.compare_digest(digest, release["sha256"]):
            raise ProjectError("Rhubarb download did not match the expected checksum")
        _extract(archive_path, staging, release["root"])
        if not _version_matches(staging / "rhubarb"):
            raise ProjectError("downloaded Rhubarb did not report version 1.14.0")
        backup = destination.with_name(f"{destination.name}.previous")
        if backup.exists():
            shutil.rmtree(backup)
        if destination.exists():
            destination.rename(backup)
        try:
            staging.rename(destination)
        except OSError:
            if backup.exists() and not destination.exists():
                backup.rename(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        archive_path.unlink(missing_ok=True)

    os.environ["RHUBARB_PATH"] = str(binary)
    return binary
