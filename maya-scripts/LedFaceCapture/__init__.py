"""LedFaceCapture -- prototype RAM-only render-to-texture pipeline for a
boolean LED-panel rig, captured live via an ortho camera and displayed on a
real model's Viewport 2.0 draw with no file texture and no disk writes.

See README.md in this folder for the full setup walkthrough and the list of
API calls that still need version-checking inside a real Maya session.
"""
from __future__ import annotations

from pathlib import Path

import maya.cmds as cmds

_PLUGIN_FILE = str(Path(__file__).resolve().parent / "led_face_capture_plugin.py")


def load():
    if not cmds.pluginInfo(_PLUGIN_FILE, query=True, loaded=True):
        cmds.loadPlugin(_PLUGIN_FILE)


def unload():
    if cmds.pluginInfo(_PLUGIN_FILE, query=True, loaded=True):
        cmds.unloadPlugin(_PLUGIN_FILE)
