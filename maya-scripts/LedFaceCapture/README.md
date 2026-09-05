# LedFaceCapture (prototype, v0)

RAM-only render-to-texture pipeline: an ortho camera captures a boolean LED
rig every viewport refresh, the pixels stay in memory (render target -> RAM
bytes -> `MTexture`), and a Viewport 2.0 shading override rebinds that texture
live on a real model's face. No `file` texture node, no image ever written to
disk, no bake step.

## Architecture change: `MPxShaderOverride` -> `MPxSurfaceShadingNodeOverride`

`node_led_face_material.py` was rewritten from scratch partway through this
prototype's debugging history. The original design made `ledFaceMaterial` a
full replacement surface shader (`MPxShaderOverride`, classification
`drawdb/shader/surface/...`, assigned straight to a shading engine's
`surfaceShader`). That was abandoned after fixing every discoverable issue
(`shaderInstance()` was never overridden -- the actual root cause of a long
chain of "no error anywhere, texture confirmed bound via
updateDevice()/setParameter(), still renders fully transparent" symptoms --
plus several stock-shader/parameter-binding details) and the render item
*still* refused to draw anything, not even a hardcoded solid color, while a
plain `lambert` on the same mesh rendered correctly in the same viewport.

The current design instead makes `ledFaceMaterial` a **utility node**
(`MPxSurfaceShadingNodeOverride`, classification
`drawdb/shader/operation/...`) that feeds a real `lambert`'s `.color`, rather
than replacing the whole shader. The lambert is what Maya already knows how
to draw correctly (confirmed directly: assigning a plain red lambert to the
same test mesh displayed immediately) -- `ledFaceMaterial` only has to
contribute one input to an otherwise-working shading network via a custom
draw *fragment* (`MFragmentManager`), a much smaller surface to get wrong
than being the entire shader.

**Everything below about `render_override.py`/`texture_registry.py` (the
capture pipeline: camera, object-set restriction, offscreen render target,
`ctypes` readback, `MTexture` creation) is unaffected by this change and
still accurate** -- confirmed working end to end via diagnostics before this
rewrite started. Only the shader-specific findings below (stock shader
parameter names, `shaderInstance()`, etc.) describe the abandoned
`MPxShaderOverride` design; kept for the record in case that path is ever
revisited, not because they still describe live code.

**Phase 1 of the new design** (current state of `node_led_face_material.py`)
registers a fragment that ignores `textureName`/the capture texture entirely
and outputs a hardcoded solid red -- to validate that
`MPxSurfaceShadingNodeOverride` + a from-scratch fragment can draw *anything*
on this Maya version before reintroducing texture sampling. The fragment XML
schema is reconstructed from memory/pattern, not looked up live via any
`help()`/`dir()` (there's no equivalent introspection for XML schema) --
expect to iterate against whatever Maya reports on first load, the same way
every fix above this point was found.

## Reload gotcha (read this if a fix "doesn't seem to take effect")

`maya-plug-ins/led_face_capture.py` now purges every `LedFaceCapture.*` entry
from `sys.modules` before importing, on every `loadPlugin` call. Without
that, `unloadPlugin(force=True)` + `loadPlugin(...)` only guarantees a fresh
re-exec of that one stub file -- Python's own import cache still hands back
whatever `LedFaceCapture.render_override` / `node_led_face_material` /
`texture_registry` were on the *first* load, no matter how many times the
.py files on disk change afterward or how many times the plug-in is
force-reloaded. Several fixes earlier in this prototype's history likely
never actually ran because of this. `LedFaceCapture.version()` (or the
"LedFaceCapture loaded -- build ..." line `initializePlugin` prints) reports
the latest mtime across the package's .py files as loaded *right now* --
compare it to your last edit time to confirm a reload really picked up new
code.

## What's here

- `texture_registry.py` -- module-level map of name -> current `MTexture`.
  `push_frame()` creates a fresh GPU texture straight from a raw byte buffer
  every call; nothing here ever touches disk.
- `node_led_capture_config.py` -- `ledCaptureConfig` node: pure config
  (`cameraName`, `captureSetName`, `resolutionX/Y`, `textureName`). The
  render override reads this every frame; it holds no logic of its own.
- `node_led_face_material.py` -- `ledFaceMaterial` node (assignable as a
  surface shader) + `LedFaceShaderOverride`, which rebinds whatever texture
  `texture_registry` holds for its `textureName` into VP2's draw every
  refresh.
- `render_override.py` -- `LedFaceCaptureOverride`, an `MRenderOverride` that
  adds one extra offscreen `MSceneRender` pass (camera + object-set override
  restricted to the boolean rig) ahead of a minimal main-scene reproduction.
- `led_face_capture_plugin.py` -- the actual Maya plug-in
  (`initializePlugin`/`uninitializePlugin`); load this file directly.
- `__init__.py` -- `load()`/`unload()` convenience wrapper.

## Scene setup

```python
import maya.cmds as cmds
import LedFaceCapture
LedFaceCapture.load()

# 1. Config node -- tells the capture pass what to render and where to publish it
config = cmds.createNode("ledCaptureConfig", name="robotFaceLED_config")
cmds.setAttr(config + ".cameraName", "ledCaptureCam", type="string")       # your ortho cam's transform
cmds.setAttr(config + ".captureSetName", "ledRigCaptureSet", type="string")  # object set containing the boolean rig geo
cmds.setAttr(config + ".textureName", "robotFaceLED", type="string")
cmds.setAttr(config + ".resolutionX", 64)
cmds.setAttr(config + ".resolutionY", 64)

# 2. Shader -- assign to the robot's face mesh
shader = cmds.shadingNode("ledFaceMaterial", asShader=True, name="robotFaceLED_mat")
cmds.setAttr(shader + ".textureName", "robotFaceLED", type="string")  # must match config's textureName
sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=shader + "SG")
cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader")
cmds.sets("robotHeadFaceMesh", edit=True, forceElement=sg)

# 3. Enable the override: Viewport menu > Renderer > LED Face Capture
```

## Known risk points -- verify inside a real Maya session before trusting this

VP2 override internals have drifted across Maya releases, and this was
written without a live Maya instance to test against. In order of how likely
each is to need a fix:

1. ~~**`node_led_face_material.py`: `MShaderManager.MStockShader` nesting**~~
   -- **confirmed wrong on Maya 2026**: `AttributeError: type object
   'OpenMayaRender.MShaderManager' has no attribute 'MStockShader'`. Fixed:
   the enum is flattened directly onto `MShaderManager`
   (`omr.MShaderManager.k3dSolidTextureShader`, no `.MStockShader` in
   between) -- the Python API doesn't mirror the C++ nested-enum path here.
2. ~~**`led_face_capture_plugin.py`: `MRenderer.unregisterOverride`**~~ --
   **confirmed wrong on Maya 2026**: `AttributeError: ... has no attribute
   'unregisterOverride'`. Fixed: the real name is `deregisterOverride`,
   matching every other Maya API teardown call (`deregisterNode`,
   `deregisterShaderOverrideCreator`). Also hardened `uninitializePlugin` so
   each teardown step is wrapped in its own try/except -- previously this one
   `AttributeError` aborted the function before the node deregister calls
   ran, which is exactly what produced the follow-up `Cannot find item of
   required type` on the next `loadPlugin` (the node types were still
   registered from the half-finished unload).
2b. ~~**`render_override.py`: `renderTargets` is not a real `MSceneRender`
   virtual**~~ -- **confirmed wrong on Maya 2026, and the actual root cause
   of the entire "preview plane stays blank/transparent, texture_registry
   never gets a frame, and an unattributable `string or unicode object
   expected` shows up intermittently once the override is active" saga.**
   The correct name, confirmed against `dir(maya.api.OpenMayaRender.
   MSceneRender)` (which never lists `renderTargets` at all), is
   **`targetOverrideList`**. Defining a method named `renderTargets` is not
   an error in Python -- it just silently creates an ordinary method Maya's
   C++ side never calls, so `self._target` stayed `None` forever, our target
   creation code never ran, and Maya fell back to whatever its *default*
   `targetOverrideList()` does instead -- which combined with our
   `cameraOverride`/`objectSetOverride` restrictions is the likely source of
   that generic, file/line-less error. Root cause found only by comparing
   every implemented method name against a live `dir()` of the base class --
   worth doing for `cameraOverride`/`objectSetOverride`/`postSceneRender`/
   `clearOperation` too if anything here still misbehaves, since none of
   those were cross-checked this rigorously up front.
2c. Diagnostics added while chasing the above are still in the code
   (unconditional `print()` at the top of `targetOverrideList`/
   `postSceneRender`/`cameraOverride`/`objectSetOverride`/`setup`, plus
   `_debug.log_exception` on every custom callback). Safe to leave in during
   further testing; strip them once the pipeline is confirmed stable end to
   end. `_debug.log_exception` deliberately uses `print()`, not
   `om2.MGlobal.displayError()` -- render callbacks can run off Maya's main
   thread, and calling MGlobal's UI/command-layer functions from the wrong
   thread can itself raise, silently swallowing the exception this module
   exists to surface.
2d. ~~**`render_override.py`: `MRasterFormat` doesn't exist in Python at
   all**~~ -- **confirmed on Maya 2026**: absent from `dir()` of the whole
   `maya.api.OpenMayaRender` module, `MRenderTargetDescription`,
   `MTextureDescription`, and the old-style `maya.OpenMayaRender` module.
   `help(MRenderTargetDescription.setRasterFormat)` shows it's just
   `setRasterFormat(int) -> self` -- a genuine Python-API gap, not a naming
   mismatch. Fixed: pass the plain int `0` directly
   (`texture_registry.RASTER_FORMAT_R8G8B8A8_UNORM`), matching the C++
   `MRasterFormat` enum's usual first-member value -- **unconfirmed as the
   right numeric value** until captured colors look correct (not
   channel-swapped/garbled); try 1, 2, 3... if they don't.
   `MRenderTargetDescription` also turned out to be setter-based
   (`setWidth`/`setHeight`/`setRasterFormat`/...), not the 7-positional-arg
   constructor used in an earlier draft. **Update:** brute-forced every
   `rasterFormat` 0-39 against `acquireRenderTarget` on Maya 2026 -- 0/1/2
   and 22-39 all return a real target, 3-21 silently return `None`. 0 is
   assumed to be `kR8G8B8A8_UNORM` (first-member convention) but this only
   confirms *a* target gets created, not which byte order the GPU actually
   writes -- if colors come out R/B-swapped later (only detectable once
   testing with non-grey/black/white LED colors, since a monochrome
   checkerboard is channel-symmetric), try 1 or 2 instead.
   **Update: no longer a guess.** The named constants live as flat
   attributes directly on `MRenderer` (confirmed via `dir(omr.MRenderer)`:
   `kR8G8B8A8_UNORM`, `kB8G8R8A8`, `kR8G8B8X8`, every DXGI-style format name
   is there). `RASTER_FORMAT_R8G8B8A8_UNORM` now reads
   `omr.MRenderer.kR8G8B8A8_UNORM` directly instead of a hardcoded `0` --
   channel order is settled, not just empirically plausible.
2d-2. ~~**`render_override.py`: `setArraySliceCount(1)`**~~ -- **confirmed
   wrong on Maya 2026, and the actual reason `acquireRenderTarget` silently
   returned `None` on every call, regardless of rasterFormat.** The
   brute-force probe above only started succeeding once
   `setArraySliceCount(0)` replaced `setArraySliceCount(1)` -- `0` means "not
   an array", `1` apparently means "an array of one slice" and needs setup
   this plain 2D target doesn't provide. Fixed.
2d-3. ~~**`render_override.py`: fixed target name `"ledFaceCaptureTarget"`
   collides with itself across plugin reloads**~~ -- **confirmed on Maya
   2026, and the reason `acquireRenderTarget` still returned `None` even
   after the format/arraySliceCount fixes above, on a scene that had just
   been through File > New.** VP2 render targets are process-level GPU
   resources, not scene state -- `File > New` does not release one that
   leaked under a fixed name during an earlier crash/force-unload in the
   same Maya session (and this prototype's debugging history had plenty of
   those). Confirmed by direct reproduction:
   `acquireRenderTarget` with name `"ledFaceCaptureTarget"` returned `None`,
   the exact same call with a never-used name succeeded immediately. Fixed:
   `_CaptureSceneRender` now suffixes the target name with `id(self)` so a
   stale leak from a previous plugin load can never collide with the
   current one again. A full Maya restart (not just File > New) is still
   the only way to actually release a target leaked under the *old* fixed
   name -- it just can no longer block anything going forward.
2e. ~~**`render_override.py`: `MRenderTarget.rawData()` return shape**~~ --
   **confirmed wrong on Maya 2026**: `ValueError: too many values to unpack
   (expected 2)`. Per `help()`, it's `[long, rowPitch, slicePitch]` where the
   first element is a **raw memory address (an int)**, not a bytes-like
   object -- needs `ctypes.string_at(ptr, slicePitch)` to actually get
   readable bytes out of it. Fixed in `postSceneRender`. (Sanity check: for
   a 64x64 target, `rowPitch` came back as 256 = 64 * 4 bytes/pixel with no
   row padding, and `slicePitch` as 16384 = 256 * 64 -- consistent with a
   tightly-packed 32-bit-per-pixel format, supporting rasterFormat `0` being
   a real 4-byte RGBA/BGRA-family format rather than something exotic.)
2e-2. ~~**`render_override.py`: `MRenderTarget.width()`/`.height()`**~~ --
   **confirmed wrong on Maya 2026**: `AttributeError: 'MRenderTarget' object
   has no attribute 'width'`. `MRenderTarget` doesn't expose its own
   dimensions at all. Fixed: `_CaptureSceneRender` now caches the
   width/height it requested (as `self._target_width`/`_target_height`) when
   it creates the target, instead of trying to query the target object for
   them again in `postSceneRender`.
2f. ~~**`render_override.py`: `LedFaceCaptureOverride.setup()` rebuilt
   `_CaptureSceneRender` from scratch every call**~~ -- **confirmed wrong on
   Maya 2026**: `setup()` runs on every redraw, not once per override
   activation. Discarding and recreating `_CaptureSceneRender` each time
   threw away its live `self._target` without releasing it, so the next
   `acquireRenderTarget("ledFaceCaptureTarget", ...)` collided with the
   still-held, now-orphaned previous target and silently returned `None`
   forever after the first frame (`targetOverrideList -- acquired target:
   None` on every call after the first). Fixed: `setup()` now reuses the
   existing `_CaptureSceneRender` instance across calls and only refreshes
   its `_config_node_fn` reference.
2g. **`texture_registry.py`: `updateDevice()` only ever fires once, before
   any frame is ever pushed -- EXPERIMENTAL FIX, untested at time of
   writing.** Confirmed on Maya 2026: with the capture pipeline fully
   working end to end (`postSceneRender` pushing a fresh frame every redraw,
   no exceptions anywhere), `LedFaceShaderOverride.updateDevice()` still only
   printed once, right as the override first activated (with
   `texture_registry` still empty), and never again despite dozens of
   subsequent `postSceneRender` calls. Root cause: nothing about
   `push_frame()` touches Maya's own dependency graph, so VP2 has no signal
   that `ledFaceMaterial` needs re-evaluating -- the shader's own attributes
   never change, only an external Python dict does. `push_frame()` now calls
   `_mark_consumers_dirty()`, which finds every `ledFaceMaterial` node whose
   `textureName` matches and calls `cmds.dgdirty()` on it. **This is
   unverified** -- `cmds.dgdirty()` from inside a render callback that may
   run off Maya's main thread is exactly the class of call that ruled out
   `MGlobal.displayError` elsewhere in this package (see `_debug.py`). If it
   introduces a new unattributable error (watch for the "string or unicode
   object expected" pattern), the fix is to drive the dirty-marking from a
   main-thread idle callback (`om2.MEventMessage.addEventCallback("idle",
   ...)` or similar) instead of calling it directly from `postSceneRender`.
2h. ~~**`node_led_face_material.py`: never overrode `shaderInstance()`**~~ --
   **THE root cause of the entire "no error anywhere, capture pipeline
   fully confirmed working end to end, texture successfully bound via
   updateDevice()/setParameter(), yet the preview plane stays completely
   transparent under both the custom override AND stock Viewport 2.0"
   saga.** Confirmed via `help(omr.MPxShaderOverride.shaderInstance)`: *"The
   default implementation returns None indicating that no shader instance
   will be used. Override this method if a shader instance is to be used
   for drawing."* This class only ever implemented `initialize()`, on the
   (reasonable-looking, completely wrong) assumption that whatever it
   returned became the shader Maya draws with. `help()` on `initialize` also
   showed its real signature is `initialize(shader) -> string` or
   `initialize(initContext, initFeedback) -> string` -- returning an
   `MShaderInstance` from an `initialize(self, obj)` matching neither
   overload meant it was never doing what it looked like it was doing
   either. Every prior confirmation that `updateDevice()`/`setParameter()`
   "worked" was real -- they were just configuring a shader instance Maya
   was never told to actually draw with. Fixed: shader instance construction
   moved to `__init__`/`_build_shader_instance()`, `shaderInstance()` now
   returns it, and `initialize()` just forwards to the base implementation.
   **Diagnosis method worth reusing for anything that still misbehaves**:
   `dir()` the base class, cross-check every name against what's
   implemented, then `help()` the specific method for its *real* signature
   and semantics -- this is exactly how `targetOverrideList` (vs the
   nonexistent `renderTargets`) was found earlier too.
3. ~~**`render_override.py`: `objectSetOverride`**~~ -- **confirmed wrong on
   Maya 2026**: `Error: MSelectionList expected` as soon as the override was
   enabled. It wants an `MSelectionList`, not the set's bare `MObject`.
   Fixed: `_resolve_selection_list()` now returns an `MSelectionList` with
   the set node added to it. Still open on other releases: this virtual may
   be named `getObjectSetOverride` instead -- if the capture pass renders
   the whole scene instead of just the boolean rig set, that's why.
4. ~~**`node_led_face_material.py`: `"map"` param name**~~ -- **confirmed
   correct** via `shader_instance.parameterList()` on Maya 2026: `'map'` is
   present alongside `samp`, `defaultColor`, `outputMode`, etc. Binding it
   was never actually the problem -- `texture_registry` simply never had a
   frame to bind (see `targetOverrideList` above), so `updateDevice`'s
   `if texture is None: return` was silently no-op'ing every time.
4. ~~**`MPxShaderOverride` method set**~~ -- **confirmed wrong on Maya
   2026**: `AttributeError: 'LedFaceShaderOverride' object has no attribute
   'object'`. `MPxShaderOverride` has no `.object()` accessor (that's an
   `MPxNode` thing) -- the node's `MObject` only ever arrives as a parameter,
   via `creator(obj)`/`updateDG(obj)`. Fixed: `updateDevice` now reads
   `self._node_obj`, refreshed every `updateDG` call rather than trusting
   the value captured once at construction (which can go stale across an
   undo/redo). Still open: confirm `handlesDraw`/`updateDG`/`updateDevice`
   are still being called with the signatures used here -- if the texture
   still never updates, run
   `help(maya.api.OpenMayaRender.MPxShaderOverride)`.
   A separate `// Error: string or unicode object expected` was also seen
   when opening Hypershade's material swatch/shade preview on
   `ledFaceMaterial` -- likely Maya's swatch renderer probing something on
   the node that expects a `compute()` we never implemented. Cosmetic unless
   it turns out to also block the main viewport draw; report back if it
   does.
5. ~~**`render_override.py`: uncleared capture target**~~ -- **confirmed on
   Maya 2026**: the preview plane rendered fully transparent instead of the
   checkerboard pattern. `_CaptureSceneRender` never cleared its own
   offscreen render target, so its alpha channel was whatever was already in
   that memory (effectively 0) -- and `k3dSolidTextureShader` samples the
   texture's alpha too, so a transparent-everywhere capture makes the whole
   plane disappear regardless of its RGB content. Fixed: added a
   `clearOperation()` override returning an opaque black `MClearOperation`
   for this pass specifically (separate from the main pipeline's own clear
   op).
6. **Main-pass fidelity** -- `LedFaceCaptureOverride`'s main scene
   reproduction is deliberately minimal (clear + one `MSceneRender` +
   present). Enabling it will visibly drop grid/manipulator/HUD overlays and
   transparency sorting versus stock Viewport 2.0. Treat this as a rig for
   validating the capture -> texture pipeline in isolation; expand the
   operation list against Maya devkit's `viewRenderOverrideTargets` /
   `viewRenderOverridePostColor` samples (under `devkit/plug-ins/` in the
   Maya SDK install) before using it as a daily-driver viewport renderer.
7. **`MTypeId` placeholders** (`0x0011D700`, `0x0011D701`) -- from the
   devkit's example-only range. Replace with a studio-issued ID block before
   this goes anywhere shared with other in-house plug-ins.

## Fallback if the boolean rig turns out to be simple on/off states

If the "boolean rig" is really just per-LED on/off flags (no 3D
shading/overlap that needs an actual camera render), skip
`render_override.py`/`node_led_capture_config.py` entirely: write the RGBA
buffer straight from the rig's attribute values into
`texture_registry.push_frame()` on an attribute-changed callback, and keep
only `node_led_face_material.py` + `texture_registry.py`. Same shader
override, same RAM-only guarantee, no camera/render-target code at all.
