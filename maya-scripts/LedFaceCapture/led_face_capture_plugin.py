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

# Maya's plug-in loader execs this specific file outside the normal package
# import machinery, so `__name__`/`__package__` are never set here and a
# relative `from . import ...` raises KeyError('__name__' not in globals).
# `LedFaceCapture`'s parent (maya-scripts/) is already on sys.path, so
# absolute imports through the package name work instead. The submodules
# themselves (node_led_capture_config.py etc.) are loaded normally through
# that import, so relative imports inside *them* are fine.
import maya.api.OpenMaya as om2
import maya.api.OpenMayaRender as omr

from LedFaceCapture import node_led_capture_config
from LedFaceCapture import node_led_face_material
from LedFaceCapture import texture_registry
from LedFaceCapture.render_override import LedFaceCaptureOverride

maya_useNewAPI = True

_override_instance = None


def initializePlugin(plugin_obj):
    plugin_fn = om2.MFnPlugin(plugin_obj, "UkoreHub", "0.1.0-prototype", "Any")

    node_led_capture_config.register(plugin_fn)
    node_led_face_material.register(plugin_fn)

    global _override_instance
    _override_instance = LedFaceCaptureOverride()
    omr.MRenderer.registerOverride(_override_instance)


def uninitializePlugin(plugin_obj):
    global _override_instance
    if _override_instance is not None:
        omr.MRenderer.unregisterOverride(_override_instance)
        _override_instance = None

    texture_registry.clear()

    plugin_fn = om2.MFnPlugin(plugin_obj)
    node_led_face_material.deregister(plugin_fn)
    node_led_capture_config.deregister(plugin_fn)
