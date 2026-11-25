import glob
import zipfile

import pytest


def _addon_path():
    matches = glob.glob("*.nvda-addon")
    return matches[0] if matches else None


def test_addon_artifact_exists():
    assert _addon_path() is not None, "No .nvda-addon file found — run `scons` first"


def test_addon_contains_expected_files():
    path = _addon_path()
    assert path is not None, "No .nvda-addon file found — run `scons` first"
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
    assert "manifest.ini" in names
    for module in ("__init__.py", "vision.py", "capture.py", "settings.py", "webnarration.py"):
        assert "globalPlugins/lima/" + module in names


def test_addon_carries_no_compiled_caches():
    # Running the tests or loading the add-on from source leaves __pycache__ folders in addon/,
    # and the build packs every file it finds there.
    path = _addon_path()
    assert path is not None, "No .nvda-addon file found — run `scons` first"
    with zipfile.ZipFile(path) as zf:
        compiled = [name for name in zf.namelist() if name.endswith(".pyc")]
    assert not compiled, f"compiled caches in the package: {compiled}"


def test_manifest_declares_lima_name():
    path = _addon_path()
    assert path is not None, "No .nvda-addon file found — run `scons` first"
    with zipfile.ZipFile(path) as zf:
        manifest = zf.read("manifest.ini").decode("utf-8")
    assert "name = LIMA" in manifest
