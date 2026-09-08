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


def _orthographic_projection_matrix(half_width, half_height, near_clip, far_clip):
    """Row-vector (v' = v * M) orthographic projection, centered on the view
    axis, built directly from explicit half-extents.

    Ground truth from months of pixel-bbox measurements (see git history)
    ruled out every camera-attribute/filmFit/render-target-aspect/
    destination-viewport-panel-aspect lever as the source of the capture's
    aspect distortion -- none of them reliably controlled the actual
    rendered aspect of this custom MSceneRender's orthographic camera.
    Handing MCameraOverride a fully explicit projection matrix sidesteps
    whatever implicit aspect Maya was reconciling to and makes the capture's
    aspect exactly what half_width/half_height say, every time.
    """
    depth = far_clip - near_clip
    return om2.MMatrix([
        1.0 / half_width, 0.0, 0.0, 0.0,
        0.0, 1.0 / half_height, 0.0, 0.0,
        0.0, 0.0, -2.0 / depth, 0.0,
        0.0, 0.0, -(far_clip + near_clip) / depth, 1.0,
    ])


def _resolve_selection_list(name):
    """objectSetOverride wants an MSelectionList (confirmed: passing a bare
    MObject raised `MSelectionList expected` on Maya 2026) -- but ground
    truth from raw-pixel diagnostics shows the capture pass rendering
    literally nothing (0 lit pixels) no matter what shader/lighting the rig
    cubes use, which is exactly what "the list contains the *set node*
    itself" would produce: a set node has no shape to draw, so restricting
    the scene to "just this one non-renderable node" is indistinguishable
    from restricting it to nothing. "the set of objects to view" in the docs
    reads as the flattened membership, not a set-node reference -- expand it
    via MFnSet.getMembers() instead of handing back the bare set node.
    """
    if not name:
        return None
    sel = om2.MSelectionList()
    try:
        sel.add(name)
    except RuntimeError:
        return None
    try:
        set_fn = om2.MFnSet(sel.getDependNode(0))
        return set_fn.getMembers(True)
    except Exception:
        _debug.log_exception("_resolve_selection_list")
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
        try:
            camera_name = self._config_node_fn.findPlug("cameraName", False).asString()
            dag_path = _resolve_dag_path(camera_name)
            if dag_path is None:
                return None
            # MFnCamera on this Maya build exposes neither the attribute nor
            # a same-named method for orthographicWidth (confirmed:
            # AttributeError even called as a method) -- read the camera
            # shape's plugs directly instead, the same findPlug() pattern
            # used everywhere else in this codebase.
            cam_node_fn = om2.MFnDependencyNode(dag_path.node())
            ortho_width = cam_node_fn.findPlug("orthographicWidth", False).asDouble()
            h_aperture = cam_node_fn.findPlug("horizontalFilmAperture", False).asDouble()
            v_aperture = cam_node_fn.findPlug("verticalFilmAperture", False).asDouble()
            near_clip = cam_node_fn.findPlug("nearClipPlane", False).asDouble()
            far_clip = cam_node_fn.findPlug("farClipPlane", False).asDouble()

            half_width = ortho_width / 2.0
            aspect = (h_aperture / v_aperture) if v_aperture else 1.0
            half_height = half_width / aspect

            override = omr.MCameraOverride()
            override.mCameraPath = dag_path
            # An explicit projection matrix, not just mCameraPath: letting
            # Maya derive this custom MSceneRender's orthographic aspect on
            # its own (from the camera's film aperture/filmFit, the render
            # target's own pixel dimensions, or the destination viewport
            # panel -- all tried and ruled out by ground-truth pixel-bbox
            # measurements) never reliably matched what the camera was
            # actually configured for. Building the projection ourselves
            # from the camera's own orthographicWidth/aperture-ratio removes
            # that guesswork -- see _orthographic_projection_matrix().
            override.mUseProjectionMatrix = True
            override.mProjectionMatrix = _orthographic_projection_matrix(
                half_width, half_height, near_clip, far_clip
            )
            return override
        except Exception:
            _debug.log_exception("cameraOverride")
            return None

    def objectSetOverride(self):
        try:
            set_name = self._config_node_fn.findPlug("captureSetName", False).asString()
            sel = _resolve_selection_list(set_name)
            # This runs every redraw -- during Play that's every frame, so
            # the member-listing walk below (only useful for confirming a
            # wrong/empty capture set) is gated the same as its print,
            # not just the print itself.
            if _debug.DEBUG_ENABLED:
                member_names = []
                if sel is not None:
                    try:
                        it = om2.MItSelectionList(sel)
                        while not it.isDone():
                            try:
                                member_names.append(it.getDagPath().fullPathName())
                            except Exception:
                                member_names.append(repr(it.getDependNode()))
                            it.next()
                    except Exception:
                        member_names = ["<MItSelectionList failed>"]
                _debug.log(
                    "LedFaceCapture: _CaptureSceneRender.objectSetOverride() called, set_name=%r sel=%r members=%s"
                    % (set_name, sel, member_names)
                )
            return sel
        except Exception:
            _debug.log_exception("objectSetOverride")
            return None

    def renderFilterOverride(self):
        # objectSetOverride() only restricts which SCENE geometry gets
        # rendered -- it has no effect on manipulator/HUD/UI overlay draw
        # items, which MSceneRender includes by default (kRenderAllItems) as
        # a completely separate concern. That's the likely explanation for
        # the capture picking up the move manipulator/gizmo the moment
        # something is selected, unrelated to the boolean rig entirely.
        # Restricting to just shaded scene geometry (opaque + transparent,
        # no UI items) should exclude it. Unverified on first write -- exact
        # constant names reconstructed from the general MSceneFilterOption
        # pattern, not confirmed live; if this errors, run
        # help(omr.MSceneRender) and check the real enum member names/the
        # real method name (may be named differently, e.g. a property
        # instead of a method).
        try:
            filter_flags = (
                omr.MSceneRender.kRenderOpaqueShadedItems
                | omr.MSceneRender.kRenderTransparentShadedItems
            )
            _debug.log("LedFaceCapture: renderFilterOverride() called, returning", filter_flags)
            return filter_flags
        except Exception:
            _debug.log_exception("renderFilterOverride")
            return omr.MSceneRender.kRenderAllItems

    def targetOverrideList(self):
        # NOTE: this virtual is named `targetOverrideList` on MSceneRender in
        # the Python API, not `renderTargets` (the name used by earlier
        # drafts of this file) -- confirmed by `dir(omr.MSceneRender)` never
        # listing `renderTargets` at all. That earlier name silently defined
        # an ordinary, never-invoked Python method: Maya kept calling the
        # *default* targetOverrideList() instead, which is why self._target
        # stayed None forever and texture_registry never received a frame.
        _debug.log("LedFaceCapture: _CaptureSceneRender.targetOverrideList() called")
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
        _debug.log("LedFaceCapture: _CaptureSceneRender.postSceneRender() called, target =", self._target)
        try:
            if self._target is None:
                return
            # rawData() -> [long, rowPitch, slicePitch] per
            # help(omr.MRenderTarget.rawData) -- the first element is a raw
            # memory address (an int), not a bytes-like object, so it has to
            # be read out via ctypes before it means anything in Python.
            raw_ptr, row_pitch, slice_pitch = self._target.rawData()
            _debug.log("LedFaceCapture: postSceneRender -- rawData ptr =", raw_ptr, "rowPitch", row_pitch, "slicePitch", slice_pitch)
            if not raw_ptr:
                return
            raw_bytes = ctypes.string_at(raw_ptr, slice_pitch)
            # The pixel-bbox/aspect diagnostics below are pure-Python loops
            # over the entire capture buffer -- measurable per-frame cost on
            # the animation timeline, not just print() overhead, so the
            # whole block (not only its prints) is gated behind
            # DEBUG_ENABLED rather than running unconditionally every frame.
            if _debug.DEBUG_ENABLED:
                # Bypass the entire shading/UV/material pipeline for this
                # check -- ground truth on whether the capture itself
                # (camera + object set + filter) contains the expected
                # content, independent of anything downstream in
                # node_led_face_material.py. RGBA8 tightly packed: every
                # 4th byte starting at 0 is R.
                red_channel = raw_bytes[0::4]
                lit_count = sum(1 for v in red_channel if v > 128)
                dark_count = len(red_channel) - lit_count
                _debug.log(
                    "LedFaceCapture: postSceneRender -- raw pixel stats: min=%d max=%d lit(R>128)=%d dark=%d of %d"
                    % (min(raw_bytes), max(raw_bytes), lit_count, dark_count, len(red_channel))
                )
                # Ground truth for the Y-stretch question, no camera-API
                # guessing involved: the rig is a 4x4 grid with EQUAL
                # spacing in X and Y, so a diagonal on-pattern
                # (dev_smoke_test's default: (0,0),(1,1),(2,2),(3,3)) spans
                # the SAME world-space distance horizontally and vertically.
                # Measure the lit-pixel bounding box directly from the raw
                # buffer -- if width_px != height_px, the distortion is
                # confirmed to be happening in the capture itself
                # (camera/target), not anywhere in the display/UV/shader
                # pipeline, and the ratio is the exact correction factor
                # needed.
                stride = row_pitch // 4
                lit_rows = []
                lit_cols = []
                for idx, v in enumerate(red_channel):
                    if v > 128:
                        lit_rows.append(idx // stride)
                        lit_cols.append(idx % stride)
                if lit_rows:
                    bbox_w = max(lit_cols) - min(lit_cols) + 1
                    bbox_h = max(lit_rows) - min(lit_rows) + 1
                    # With a non-square target (resolutionX != resolutionY
                    # on the config node), equal bbox_w/bbox_h no longer
                    # means "no distortion" -- what matters is equal
                    # FRACTIONAL coverage per axis, since the world content
                    # is square but the target pixel grid itself might not
                    # be.
                    frac_w = bbox_w / float(self._target_width)
                    frac_h = bbox_h / float(self._target_height)
                    _debug.log(
                        "LedFaceCapture: postSceneRender -- lit-pixel bbox width=%d/%d (%.3f) "
                        "height=%d/%d (%.3f) -- fractional ratio=%.3f (1.0 means no distortion)"
                        % (
                            bbox_w, self._target_width, frac_w,
                            bbox_h, self._target_height, frac_h,
                            frac_w / frac_h,
                        )
                    )
            texture_name = self._config_node_fn.findPlug("textureName", False).asString()
            texture_registry.push_frame(texture_name, self._target_width, self._target_height, raw_bytes, row_pitch)
            _debug.log("LedFaceCapture: postSceneRender -- pushed frame for", repr(texture_name))
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
            _debug.log(
                "LedFaceCapture: setup() -- destination=%r config node found: %s"
                % (destination, config_fn.name() if config_fn else None)
            )
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
