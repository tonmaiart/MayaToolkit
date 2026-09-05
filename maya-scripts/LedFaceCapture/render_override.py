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

import ctypes

import maya.api.OpenMaya as om2
import maya.api.OpenMayaRender as omr

from . import _debug
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
    """Resolves `name` to a dag path, nudged onto its shape if it has one.

    Accepts either a camera's transform or shape name -- cameraOverride
    wants the camera itself, and extendToShape() is a no-op (raises, caught
    below) if `name` was already a shape or has none.
    """
    if not name:
        return None
    sel = om2.MSelectionList()
    try:
        sel.add(name)
    except RuntimeError:
        return None
    path = sel.getDagPath(0)
    try:
        path.extendToShape()
    except RuntimeError:
        pass
    return path


def _resolve_selection_list(name):
    """objectSetOverride wants an MSelectionList (confirmed: passing a bare
    MObject raised `MSelectionList expected` on Maya 2026), not the set's
    MObject directly -- add the set node's name to a fresh list and hand
    that back.
    """
    if not name:
        return None
    sel = om2.MSelectionList()
    try:
        sel.add(name)
    except RuntimeError:
        return None
    return sel


class _CaptureSceneRender(omr.MSceneRender):
    """Offscreen ortho-camera pass restricted to the boolean-rig capture set."""

    def __init__(self, name, config_node_fn):
        omr.MSceneRender.__init__(self, name)
        self._config_node_fn = config_node_fn
        self._target = None
        # MRenderTarget has no .width()/.height() (confirmed: AttributeError
        # on Maya 2026) -- cache the dimensions we requested when we created
        # it instead of trying to query the target object for them again.
        self._target_width = 0
        self._target_height = 0
        # A fixed target name ("ledFaceCaptureTarget") bit us hard: once any
        # earlier crash/force-unload leaked one under that exact name (VP2
        # render targets are process-level GPU resources, not scene state --
        # File > New does not release them), every subsequent
        # acquireRenderTarget() with the same name silently returned None
        # forever, with no exception to explain why. A per-instance unique
        # suffix means a stale leak from a previous plugin load can never
        # collide with this session's target.
        self._target_name = "ledFaceCaptureTarget_{:08x}".format(id(self) & 0xFFFFFFFF)
        # Without an explicit clear, the offscreen target's alpha channel is
        # whatever garbage/zero was already there -- k3dSolidTextureShader
        # samples that alpha too, so an uncleared background reads back as
        # fully transparent (this is what made the preview plane invisible).
        # Opaque black background: "off" LEDs read as solid black, "on" ones
        # show through as whatever the rig cube's own shading is.
        self._clear_op = omr.MClearOperation(name + "Clear")
        self._clear_op.setClearColor((0.0, 0.0, 0.0, 1.0))
        self._clear_op.setClearGradient(False)

    def clearOperation(self):
        return self._clear_op

    def cameraOverride(self):
        print("LedFaceCapture: _CaptureSceneRender.cameraOverride() called")
        try:
            camera_name = self._config_node_fn.findPlug("cameraName", False).asString()
            dag_path = _resolve_dag_path(camera_name)
            if dag_path is None:
                return None
            override = omr.MCameraOverride()
            override.mCameraPath = dag_path
            return override
        except Exception:
            _debug.log_exception("cameraOverride")
            return None

    def objectSetOverride(self):
        print("LedFaceCapture: _CaptureSceneRender.objectSetOverride() called")
        try:
            set_name = self._config_node_fn.findPlug("captureSetName", False).asString()
            return _resolve_selection_list(set_name)
        except Exception:
            _debug.log_exception("objectSetOverride")
            return None

    def targetOverrideList(self):
        # NOTE: this virtual is named `targetOverrideList` on MSceneRender in
        # the Python API, not `renderTargets` (the name used by earlier
        # drafts of this file) -- confirmed by `dir(omr.MSceneRender)` never
        # listing `renderTargets` at all. That earlier name silently defined
        # an ordinary, never-invoked Python method: Maya kept calling the
        # *default* targetOverrideList() instead, which is why self._target
        # stayed None forever and texture_registry never received a frame.
        print("LedFaceCapture: _CaptureSceneRender.targetOverrideList() called")
        try:
            width = self._config_node_fn.findPlug("resolutionX", False).asInt()
            height = self._config_node_fn.findPlug("resolutionY", False).asInt()
            width = max(1, width)
            height = max(1, height)

            target_mgr = omr.MRenderer.getRenderTargetManager()
            if target_mgr is None:
                print("LedFaceCapture: targetOverrideList -- no target manager")
                return []

            if self._target is None or self._target_width != width or self._target_height != height:
                if self._target is not None:
                    target_mgr.releaseRenderTarget(self._target)
                # MRenderTargetDescription is setter-based, not a
                # positional-argument constructor (confirmed via dir(): it
                # exposes setWidth/setHeight/setRasterFormat/etc., no 7-arg
                # constructor) -- and setRasterFormat takes a plain int, see
                # texture_registry.RASTER_FORMAT_R8G8B8A8_UNORM's docstring
                # for why.
                desc = omr.MRenderTargetDescription()
                desc.setName(self._target_name)
                desc.setWidth(width)
                desc.setHeight(height)
                desc.setMultiSampleCount(1)
                # 0, not 1 -- confirmed by brute-force probing every
                # rasterFormat 0-39 with arraySliceCount(1): every single one
                # returned None from acquireRenderTarget with no exception.
                # Switching to 0 (meaning "not an array") let formats
                # 0/1/2/22-39 all succeed. 1 apparently means "an array of
                # one slice" and needs handling this simple 2D target
                # doesn't set up.
                desc.setArraySliceCount(0)
                desc.setIsCubeMap(False)
                desc.setRasterFormat(texture_registry.RASTER_FORMAT_R8G8B8A8_UNORM)
                self._target = target_mgr.acquireRenderTarget(desc)
                self._target_width = width
                self._target_height = height
                print("LedFaceCapture: targetOverrideList -- acquired target:", self._target)

            return [self._target] if self._target is not None else []
        except Exception:
            _debug.log_exception("targetOverrideList")
            return []

    def postSceneRender(self, context):
        print("LedFaceCapture: _CaptureSceneRender.postSceneRender() called, target =", self._target)
        try:
            if self._target is None:
                return
            # rawData() -> [long, rowPitch, slicePitch] per
            # help(omr.MRenderTarget.rawData) -- the first element is a raw
            # memory address (an int), not a bytes-like object, so it has to
            # be read out via ctypes before it means anything in Python.
            raw_ptr, row_pitch, slice_pitch = self._target.rawData()
            print("LedFaceCapture: postSceneRender -- rawData ptr =", raw_ptr, "rowPitch", row_pitch, "slicePitch", slice_pitch)
            if not raw_ptr:
                return
            raw_bytes = ctypes.string_at(raw_ptr, slice_pitch)
            texture_name = self._config_node_fn.findPlug("textureName", False).asString()
            texture_registry.push_frame(texture_name, self._target_width, self._target_height, raw_bytes)
            print("LedFaceCapture: postSceneRender -- pushed frame for", repr(texture_name))
            self._target.freeRawData(raw_ptr)
        except Exception:
            _debug.log_exception("postSceneRender")


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
        try:
            config_fn = _find_config_node_fn()
            print("LedFaceCapture: setup() -- config node found:", config_fn.name() if config_fn else None)
            if config_fn is not None:
                # setup() runs on every redraw, not once -- building a brand
                # new _CaptureSceneRender here every time (as an earlier
                # version of this method did) throws away its live
                # self._target without ever releasing it, so every
                # subsequent acquireRenderTarget("ledFaceCaptureTarget", ...)
                # collides with the still-held-but-orphaned previous target
                # and silently returns None. Reuse the same instance across
                # calls; only its config reference needs refreshing (the
                # underlying scene node could have been deleted/recreated).
                if self._capture_op is None:
                    self._capture_op = _CaptureSceneRender("ledFaceCapture", config_fn)
                else:
                    self._capture_op._config_node_fn = config_fn
                self._operations = [self._capture_op, self._clear_op, self._main_scene_op, self._present_op]
            else:
                self._capture_op = None
                self._operations = [self._clear_op, self._main_scene_op, self._present_op]
            self._operation_index = 0
        except Exception:
            _debug.log_exception("setup")

    def cleanup(self):
        try:
            self._operation_index = 0
        except Exception:
            _debug.log_exception("cleanup")

    def startOperationIterator(self):
        try:
            self._operation_index = 0
            return True
        except Exception:
            _debug.log_exception("startOperationIterator")
            return False

    def renderOperation(self):
        try:
            return self._operations[self._operation_index]
        except Exception:
            _debug.log_exception("renderOperation")
            return None

    def nextRenderOperation(self):
        try:
            self._operation_index += 1
            return self._operation_index < len(self._operations)
        except Exception:
            _debug.log_exception("nextRenderOperation")
            return False
