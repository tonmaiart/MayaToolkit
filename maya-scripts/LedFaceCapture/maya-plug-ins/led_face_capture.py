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
"""
from __future__ import annotations

from LedFaceCapture.led_face_capture_plugin import (
    maya_useNewAPI,
    initializePlugin,
    uninitializePlugin,
)

__all__ = ["maya_useNewAPI", "initializePlugin", "uninitializePlugin"]
