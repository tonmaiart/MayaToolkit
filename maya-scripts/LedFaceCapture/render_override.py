"""LedFaceCaptureOverride: a Viewport 2.0 MRenderOverride that adds one extra
offscreen ortho-camera pass (the boolean-rig capture) ahead of an otherwise
plain main scene render.

Scope/caveats (read before enabling this in the Renderer menu):

- Activating any MRenderOverride replaces Maya's *entire* operation list for
  that viewport -- there is no way to "just add a pass" to the stock
  pipeline. The main-scene reproduction below is intentionally minimal
  (clear + one MSceneRender + present) and will visibly drop things the
  default Viewport 2.0 pipeline draws in separate passes: transparency
  sorting, manipulators/grid/HUD overlays, selection highlighting nuances.
  Treat this as a v0 for validating the capture -> texture_registry ->
  ledFaceMaterial pipeline in isolation, not a drop-in replacement for daily
  animation viewport use. Expand the operation list against Maya devkit's
  own `viewRenderOverrideTargets` / `viewRenderOverridePostColor` samples
  (installed under `devkit/plug-ins/` with Maya) once the capture mechanism
  itself is confirmed working.
- `objectSetOverride` isolates the capture pass to one object set (the
  boolean rig). Some Maya releases exposed this virtual under a different
  name (`getObjectSetOverride`) -- if the capture pass renders the whole
  scene instead of just the rig, check
  `help(maya.api.OpenMayaRender.MSceneRender)` for the exact name in your
  version.
"""
from __future__ import annotations

import maya.api.OpenMaya as om2
import maya.api.OpenMayaRender as omr

from . import texture_registry
from .node_led_capture_config import NODE_NAME as CONFIG_NODE_NAME

OVERRIDE_NAME = "ledFaceCaptureOverride"


def _find_config_node_fn():
    """First ledCaptureConfig node in the scene, or None if there isn't one yet."""
    iterator = om2.MItDependencyNodes(om2.MFn.kPluginDependNode)
    while not iterator.isDone():
        node_fn = om2.MFnDependencyNode(iterator.thisNode())
        if node_fn.typeName == CONFIG_NODE_NAME:
            return node_fn
        iterator.next()
    return None


def _resolve_dag_path(name):
    if not name:
        return None
    sel = om2.MSelectionList()
    try:
        sel.add(name)
    except RuntimeError:
        return None
    return sel.getDagPath(0)


def _resolve_depend_node(name):
    if not name:
        return None
    sel = om2.MSelectionList()
    try:
        sel.add(name)
    except RuntimeError:
        return None
    return sel.getDependNode(0)


class _CaptureSceneRender(omr.MSceneRender):
    """Offscreen ortho-camera pass restricted to the boolean-rig capture set."""

    def __init__(self, name, config_node_fn):
        omr.MSceneRender.__init__(self, name)
        self._config_node_fn = config_node_fn
        self._target = None

    def cameraOverride(self):
        camera_name = self._config_node_fn.findPlug("cameraName", False).asString()
        dag_path = _resolve_dag_path(camera_name)
        if dag_path is None:
            return None
        override = omr.MCameraOverride()
        override.mCameraPath = dag_path
        return override

    def objectSetOverride(self):
        set_name = self._config_node_fn.findPlug("captureSetName", False).asString()
        return _resolve_depend_node(set_name)

    def renderTargets(self):
        width = self._config_node_fn.findPlug("resolutionX", False).asInt()
        height = self._config_node_fn.findPlug("resolutionY", False).asInt()
        width = max(1, width)
        height = max(1, height)

        target_mgr = omr.MRenderer.getRenderTargetManager()
        if target_mgr is None:
            return []

        if self._target is None or self._target.width() != width or self._target.height() != height:
            if self._target is not None:
                target_mgr.releaseRenderTarget(self._target)
            desc = omr.MRenderTargetDescription(
                "ledFaceCaptureTarget", width, height, 1,
                omr.MRasterFormat.kR8G8B8A8_UNORM, 0, False,
            )
            self._target = target_mgr.acquireRenderTarget(desc)

        return [self._target] if self._target is not None else []

    def postSceneRender(self, context):
        if self._target is None:
            return
        raw, row_pitch = self._target.rawData()
        if raw is None:
            return
        texture_name = self._config_node_fn.findPlug("textureName", False).asString()
        texture_registry.push_frame(texture_name, self._target.width(), self._target.height(), bytes(raw))
        self._target.freeRawData(raw)


class LedFaceCaptureOverride(omr.MRenderOverride):
    def __init__(self):
        omr.MRenderOverride.__init__(self, OVERRIDE_NAME)
        self._clear_op = omr.MClearOperation("ledFaceClear")
        self._clear_op.setClearColor((0.0, 0.0, 0.0, 1.0))
        self._clear_op.setClearGradient(False)
        self._main_scene_op = omr.MSceneRender("ledFaceMainScene")
        self._present_op = omr.MPresentTarget("ledFacePresent")
        self._capture_op = None
        self._operations = [self._clear_op, self._main_scene_op, self._present_op]
        self._operation_index = 0

    def uiName(self):
        return "LED Face Capture"

    def supportedDrawAPIs(self):
        return omr.MRenderer.kAllDevices

    def setup(self, destination):
        config_fn = _find_config_node_fn()
        if config_fn is not None:
            self._capture_op = _CaptureSceneRender("ledFaceCapture", config_fn)
            self._operations = [self._capture_op, self._clear_op, self._main_scene_op, self._present_op]
        else:
            self._capture_op = None
            self._operations = [self._clear_op, self._main_scene_op, self._present_op]
        self._operation_index = 0

    def cleanup(self):
        self._operation_index = 0

    def startOperationIterator(self):
        self._operation_index = 0
        return True

    def renderOperation(self):
        return self._operations[self._operation_index]

    def nextRenderOperation(self):
        self._operation_index += 1
        return self._operation_index < len(self._operations)
