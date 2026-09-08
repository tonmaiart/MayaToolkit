"""LED Face Capture -- Maya plug-in entry point.

Load by absolute path (does not need to sit on MAYA_PLUG_IN_PATH):

    import maya.cmds as cmds
    cmds.loadPlugin(r"<...>/LedFaceCapture/led_face_capture_plugin.py")

or via the package helper once maya-scripts/ is already on PYTHONPATH
(MayaToolkit's own plugin.py already contributes that for every tool here):

    import LedFaceCapture
    LedFaceCapture.load()
"""
from __future__ import annotations

import time
from pathlib import Path

# Maya's plug-in loader execs this specific file outside the normal package
# import machinery, so `__name__`/`__package__` are never set here and a
# relative `from . import ...` raises KeyError('__name__' not in globals).
# `LedFaceCapture`'s parent (maya-scripts/) is already on sys.path, so
# absolute imports through the package name work instead. The submodules
# themselves (node_led_face_material.py etc.) are loaded normally through
# that import, so relative imports inside *them* are fine.
import maya.api.OpenMaya as om2
import maya.api.OpenMayaRender as omr

from LedFaceCapture import node_led_face_blend
from LedFaceCapture import node_led_face_material
from LedFaceCapture import texture_registry
from LedFaceCapture.render_override import LedFaceCaptureOverride

maya_useNewAPI = True

_override_instance = None


def _compute_build_stamp():
    """Latest mtime across every .py in the package -- changes automatically
    whenever any of them is edited, so there's never a stale hand-written
    version number to forget to bump. Printed on load so a reload can be
    confirmed as having actually picked up the newest edit.
    """
    package_dir = Path(__file__).resolve().parent
    latest = 0.0
    for py_file in package_dir.glob("*.py"):
        latest = max(latest, py_file.stat().st_mtime)
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest))


BUILD_STAMP = _compute_build_stamp()


def initializePlugin(plugin_obj):
    plugin_fn = om2.MFnPlugin(plugin_obj, "UkoreHub", "0.1.0-prototype", "Any")

    node_led_face_material.register(plugin_fn)
    node_led_face_blend.register(plugin_fn)

    global _override_instance
    _override_instance = LedFaceCaptureOverride()
    omr.MRenderer.registerOverride(_override_instance)

    om2.MGlobal.displayInfo("LedFaceCapture loaded -- build {}".format(BUILD_STAMP))


def uninitializePlugin(plugin_obj):
    # Each step runs independently: a failure in one (e.g. a wrong API method
    # name) must not skip the rest, or a leftover node/override registration
    # will collide with the next loadPlugin's registerNode/registerOverride
    # call (this is exactly how a single AttributeError here previously
    # cascaded into "Cannot find item of required type" on reload).
    global _override_instance
    if _override_instance is not None:
        try:
            omr.MRenderer.deregisterOverride(_override_instance)
        except Exception:
            om2.MGlobal.displayWarning("LedFaceCapture: failed to deregister render override.")
        _override_instance = None

    texture_registry.clear()

    plugin_fn = om2.MFnPlugin(plugin_obj)
    try:
        node_led_face_material.deregister(plugin_fn)
    except Exception:
        om2.MGlobal.displayWarning("LedFaceCapture: failed to deregister ledFaceMaterial.")
    try:
        node_led_face_blend.deregister(plugin_fn)
    except Exception:
        om2.MGlobal.displayWarning("LedFaceCapture: failed to deregister ledFaceBlend.")
