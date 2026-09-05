# LedFaceCapture (prototype, v0)

RAM-only render-to-texture pipeline: an ortho camera captures a boolean LED
rig every viewport refresh, the pixels stay in memory (render target -> RAM
bytes -> `MTexture`), and a Viewport 2.0 shader override rebinds that texture
live on a real model's face. No `file` texture node, no image ever written to
disk, no bake step.

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

1. **`render_override.py`: `objectSetOverride`** -- some releases exposed
   this as `getObjectSetOverride` instead. If the capture pass renders the
   whole scene instead of just the boolean rig set, this is why.
2. **`node_led_face_material.py`: `k3dSolidTextureShader` / `"map"` param
   name** -- confirm the stock shader enum member exists
   (`dir(omr.MShaderManager.MStockShader)`) and that `"map"` is really its
   texture parameter (`shader_instance.parameterList()`).
3. **`MPxShaderOverride` method set** -- `handlesDraw`/`updateDevice`/
   `updateDG` signatures; run `help(maya.api.OpenMayaRender.MPxShaderOverride)`
   if the plug-in fails to load or the texture never updates.
4. **Main-pass fidelity** -- `LedFaceCaptureOverride`'s main scene
   reproduction is deliberately minimal (clear + one `MSceneRender` +
   present). Enabling it will visibly drop grid/manipulator/HUD overlays and
   transparency sorting versus stock Viewport 2.0. Treat this as a rig for
   validating the capture -> texture pipeline in isolation; expand the
   operation list against Maya devkit's `viewRenderOverrideTargets` /
   `viewRenderOverridePostColor` samples (under `devkit/plug-ins/` in the
   Maya SDK install) before using it as a daily-driver viewport renderer.
5. **`MTypeId` placeholders** (`0x0011D700`, `0x0011D701`) -- from the
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
