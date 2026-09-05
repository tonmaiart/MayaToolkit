"""Thin MAYA_PLUG_IN_PATH entry point for LedFaceCapture.

This is the *only* file that should ever live in this folder: maya_launcher's
env bridge scans every MAYA_PLUG_IN_PATH-contributed directory and force-
loads every .py/.mll/.pyd/.so it finds there via `loadPlugin -quiet
"<filename>"`. Keeping the real implementation modules
(node_led_face_material.py, render_override.py, texture_registry.py, ...) in
the parent LedFaceCapture/ package -- which is only on PYTHONPATH, not
MAYA_PLUG_IN_PATH -- keeps that scan from trying to loadPlugin them too (they
have no initializePlugin and would just spam the launch log with caught
errors).

All real logic lives in LedFaceCapture/led_face_capture_plugin.py; this file
just re-exports what Maya's plug-in loader looks for.

Maya's plug-in loader only guarantees a fresh re-exec of *this* file on
unloadPlugin/loadPlugin -- it does not know to evict the LedFaceCapture.*
submodules (node_led_face_material, render_override, texture_registry, ...)
from Python's own sys.modules cache. Left alone, `from LedFaceCapture.x
import y` below would silently hand back whatever was imported on the very
first load, no matter how many times the package's .py files are edited and
the plugin force-unloaded/reloaded afterward -- which is exactly what made
several fixes upstream appear to have "no effect". Purging every
LedFaceCapture.* entry before importing forces a genuine re-read from disk
on every single loadPlugin call.
"""
from __future__ import annotations

import sys

for _mod_name in [n for n in sys.modules if n == "LedFaceCapture" or n.startswith("LedFaceCapture.")]:
    del sys.modules[_mod_name]

from LedFaceCapture.led_face_capture_plugin import (
    maya_useNewAPI,
    initializePlugin,
    uninitializePlugin,
)

__all__ = ["maya_useNewAPI", "initializePlugin", "uninitializePlugin"]
