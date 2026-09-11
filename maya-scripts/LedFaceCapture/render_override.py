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
import maya.cmds as cmds

from . import _debug
from . import texture_registry
from .node_led_face_material import NODE_NAME as MATERIAL_NODE_NAME

OVERRIDE_NAME = "ledFaceCaptureOverride"


def _apply_viewport_background(clear_op):
    """Mirrors Maya's own Viewport 2.0 background (Display > Viewport
    Background, or right-click panel > Change Background Color) onto
    `clear_op`. Called every setup() so a background color/gradient change
    made through Maya's own UI while this override is active takes effect
    on the next redraw -- this override replaces Maya's whole operation
    list, so nothing else reads that preference for us.

    displayRGBColor's query form returns [r, g, b] (0-1 floats); solid vs.
    gradient is whatever displayPref's displayGradient flag says, same as
    the stock viewport.
    """
    try:
        use_gradient = bool(cmds.displayPref(query=True, displayGradient=True))
    except Exception:
        _debug.log_exception("_apply_viewport_background displayPref")
        use_gradient = False
    try:
        if use_gradient:
            top = cmds.displayRGBColor("backgroundTop", query=True)
            bottom = cmds.displayRGBColor("backgroundBottom", query=True)
            clear_op.setClearColor((bottom[0], bottom[1], bottom[2], 1.0))
            clear_op.setClearColor2((top[0], top[1], top[2], 1.0))
            clear_op.setClearGradient(True)
            _debug.log(
                "LedFaceCapture: _apply_viewport_background -- gradient top=%s bottom=%s"
                % (top, bottom)
            )
        else:
            bg = cmds.displayRGBColor("background", query=True)
            clear_op.setClearColor((bg[0], bg[1], bg[2], 1.0))
            clear_op.setClearGradient(False)
            _debug.log("LedFaceCapture: _apply_viewport_background -- solid bg=%s" % (bg,))
    except Exception:
        _debug.log_exception("_apply_viewport_background")


def _find_capture_configs():
    """One MFnDependencyNode per distinct textureName among every
    ledFaceMaterial node in the scene -- there is no separate config node
    type any more (cameraName/captureSetName/resolutionX/Y now live directly
    on ledFaceMaterial, see node_led_face_material.py), and a scene can have
    any number of independent capture channels (e.g. one per eye) active at
    once. First node found for a given textureName wins if more than one
    shares that name -- they're expected to agree on how to capture it, so
    only one needs to actually describe it.

    cmds.ls(type=...) is natively type-indexed in C++ (same lesson as
    texture_registry.py's _mark_consumers_dirty()) instead of walking every
    plugin node in the scene by hand.
    """
    configs = {}
    for name in (cmds.ls(type=MATERIAL_NODE_NAME) or []):
        sel = om2.MSelectionList()
        try:
            sel.add(name)
        except RuntimeError:
            continue
        node_fn = om2.MFnDependencyNode(sel.getDependNode(0))
        # Atlas-composer nodes (atlasSources set, see _compose_atlases())
        # are display-only consumers of OTHER capture channels, not capture
        # sources themselves -- treating one as its own capture channel
        # would run a bogus, camera-less/unrestricted scene-render pass
        # under its textureName every frame, clobbering the atlas this
        # module just finished assembling moments earlier in the same
        # setup() call.
        try:
            if node_fn.findPlug("atlasSources", False).asString():
                continue
        except Exception:
            pass
        texture_name = node_fn.findPlug("textureName", False).asString()
        if texture_name and texture_name not in configs:
            configs[texture_name] = node_fn
    return configs


def _compose_atlases():
    """Runs texture_registry.compose_horizontal_atlas() for every
    ledFaceMaterial node that has atlasSources set, once per redraw.

    Reads whatever's currently in texture_registry for each source name --
    i.e. last frame's captures, since this runs at the START of setup(),
    before this frame's own capture passes execute. One frame of lag on the
    composed result is an acceptable, unnoticeable trade for not needing
    any new render-operation type to hook "after all captures, before the
    main scene render" instead.
    """
    try:
        for name in (cmds.ls(type=MATERIAL_NODE_NAME) or []):
            sources = cmds.getAttr(name + ".atlasSources")
            if not sources:
                continue
            source_names = [s.strip() for s in sources.split(",") if s.strip()]
            output_name = cmds.getAttr(name + ".textureName")
            texture_registry.compose_horizontal_atlas(output_name, source_names)
    except Exception:
        _debug.log_exception("_compose_atlases")


def _connected_camera_dag_path(config_node_fn):
    """Resolves the camera via the `cameraMsg` message-attribute connection
    (see node_led_face_material.py's initialize()). This replaced a legacy
    `cameraName` string attribute (removed) -- connections survive
    `file -reference` (Maya remaps them through the reference's namespace
    automatically), which is exactly what a plain string attribute never
    did. Returns None (not an exception) when nothing's wired up, e.g. an
    unset config node.
    """
    try:
        plug = config_node_fn.findPlug("cameraMsg", False)
        source_plug = plug.source()
        if source_plug.isNull:
            return None
        node = source_plug.node()
        if node.isNull():
            return None
        dag_path = om2.MDagPath.getAPathTo(node)
        try:
            dag_path.extendToShape()
        except RuntimeError:
            pass
        return dag_path
    except Exception:
        _debug.log_exception("_connected_camera_dag_path")
        return None


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


def _connected_capture_set_members(config_node_fn):
    """Resolves the capture set via the `captureSetMsg` message-attribute
    connection (see node_led_face_material.py's initialize()). This replaced
    a legacy `captureSetName` string attribute (removed) -- same referencing
    rationale as _connected_camera_dag_path(): a set's name never survived
    `file -reference` either. objectSetOverride wants an MSelectionList
    (confirmed: passing a bare MObject raised `MSelectionList expected` on
    Maya 2026) containing the set's flattened membership, not the set node
    itself -- a set node has no shape to draw, so restricting the scene to
    "just this one non-renderable node" is indistinguishable from
    restricting it to nothing (confirmed via ground-truth raw-pixel
    diagnostics: 0 lit pixels until this was fixed to expand via
    MFnSet.getMembers()). Returns None (not an exception) when nothing's
    wired up.
    """
    try:
        plug = config_node_fn.findPlug("captureSetMsg", False)
        source_plug = plug.source()
        if source_plug.isNull:
            return None
        node = source_plug.node()
        if node.isNull():
            return None
        set_fn = om2.MFnSet(node)
        return set_fn.getMembers(True)
    except Exception:
        _debug.log_exception("_connected_capture_set_members")
        return None


class _CaptureSceneRender(omr.MSceneRender):
    """Offscreen ortho-camera pass restricted to one capture set -- one
    instance per distinct textureName (see _find_capture_configs()), so a
    scene with several independent capture channels (e.g. left/right eye)
    runs one of these each, concurrently, inside the same override.
    """

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
            dag_path = _connected_camera_dag_path(self._config_node_fn)
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
            sel = _connected_capture_set_members(self._config_node_fn)
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
                    "LedFaceCapture: _CaptureSceneRender.objectSetOverride() called, sel=%r members=%s"
                    % (sel, member_names)
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
                    # on the ledFaceMaterial node), equal bbox_w/bbox_h no longer
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

    def release(self):
        """Releases the GPU render target, if any. Called by
        LedFaceCaptureOverride.setup() when this instance's textureName no
        longer shows up on any ledFaceMaterial in the scene (node deleted,
        renamed, or its texName cleared) -- without this, a dropped capture
        channel's render target leaks for the rest of the Maya session (see
        __init__'s note on why a fixed target name bit us hard previously).
        """
        try:
            if self._target is not None:
                target_mgr = omr.MRenderer.getRenderTargetManager()
                if target_mgr is not None:
                    target_mgr.releaseRenderTarget(self._target)
                self._target = None
                self._target_width = 0
                self._target_height = 0
        except Exception:
            _debug.log_exception("_CaptureSceneRender.release")


class _MainSceneRender(omr.MSceneRender):
    """The visible main-scene pass. A plain, un-subclassed MSceneRender used
    here previously has its OWN internal default clearOperation() (confirmed
    live: with the standalone MClearOperation set to grey and this pass left
    as a bare MSceneRender, the viewport still rendered pure black) that
    runs when this operation's turn comes up and clobbers whatever the
    earlier standalone MClearOperation already painted -- both defaulted to
    black, which is why this went unnoticed until the clear color was
    changed away from black. Overriding clearOperation() to hand back the
    override's own (viewport-background-synced) clear op, same pattern as
    _CaptureSceneRender below, makes this pass's own clear agree with it
    instead of silently overriding it back to black.
    """

    def __init__(self, name, clear_op):
        omr.MSceneRender.__init__(self, name)
        self._clear_op = clear_op

    def clearOperation(self):
        return self._clear_op


class LedFaceCaptureOverride(omr.MRenderOverride):
    def __init__(self):
        omr.MRenderOverride.__init__(self, OVERRIDE_NAME)
        self._clear_op = omr.MClearOperation("ledFaceClear")
        # Actual color/gradient is synced from Maya's own Viewport 2.0
        # background preference in setup() -> _apply_viewport_background();
        # this is just a safe initial value before the first setup() call.
        self._clear_op.setClearColor((0.0, 0.0, 0.0, 1.0))
        self._clear_op.setClearGradient(False)
        self._main_scene_op = _MainSceneRender("ledFaceMainScene", self._clear_op)
        self._present_op = omr.MPresentTarget("ledFacePresent")
        # One _CaptureSceneRender per distinct textureName, keyed by that
        # name -- an arbitrary number of independent capture channels (e.g.
        # left eye + right eye, each its own camera/capture set) can be
        # active at once, each running as its own operation ahead of the
        # shared main-scene pass.
        self._capture_ops = {}
        # self._clear_op is not listed as its own operation here any more --
        # _MainSceneRender.clearOperation() above ties it directly to the
        # main-scene pass instead, which is what Maya's render loop actually
        # honors (see _MainSceneRender's docstring).
        self._operations = [self._main_scene_op, self._present_op]
        self._operation_index = 0

    def uiName(self):
        return "LED Face Capture"

    def supportedDrawAPIs(self):
        return omr.MRenderer.kAllDevices

    def setup(self, destination):
        try:
            _apply_viewport_background(self._clear_op)
            _compose_atlases()

            configs = _find_capture_configs()
            _debug.log(
                "LedFaceCapture: setup() -- destination=%r capture channels found: %s"
                % (destination, sorted(configs.keys()))
            )

            # Drop capture ops for channels that disappeared (node deleted,
            # renamed, or texName cleared) -- release their GPU render
            # targets first, or they leak for the rest of the session (see
            # _CaptureSceneRender.release()'s docstring).
            for texture_name in list(self._capture_ops.keys()):
                if texture_name not in configs:
                    self._capture_ops.pop(texture_name).release()

            # setup() runs on every redraw, not once -- building a brand new
            # _CaptureSceneRender for a channel that already has one throws
            # away its live self._target without ever releasing it, so every
            # subsequent acquireRenderTarget(...) collides with the
            # still-held-but-orphaned previous target and silently returns
            # None. Reuse the same instance across calls per channel; only
            # its config reference needs refreshing (the underlying scene
            # node could have been deleted/recreated under the same name).
            for texture_name, config_fn in configs.items():
                existing = self._capture_ops.get(texture_name)
                if existing is None:
                    self._capture_ops[texture_name] = _CaptureSceneRender(
                        "ledFaceCapture_" + texture_name, config_fn
                    )
                else:
                    existing._config_node_fn = config_fn

            self._operations = (
                list(self._capture_ops.values())
                + [self._main_scene_op, self._present_op]
            )
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
