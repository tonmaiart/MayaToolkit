"""Throwaway test scene for LedFaceCapture: builds a fake boolean LED rig (a
grid of cubes with a per-cube shader color as the on/off bit), an ortho
capture camera, the ledFaceMaterial node (which also carries its own capture
config -- see node_led_face_material.py), and a plain preview plane to
display the result -- so the whole capture -> RAM texture -> viewport-material
pipeline can be smoke-tested without touching a real robot rig.

On/off was originally done via `.visibility`, toggling cubes in and out of
the render entirely. Ground truth from render_override.py's lit-pixel
bounding-box diagnostic proved this was the actual cause of an apparent
"Y stretch": with fewer cubes visible, the CAPTURED CONTENT's vertical pixel
footprint shrank by MORE than the horizontal one did for the same world-space
shrink (confirmed across two different on-patterns spanning different world
sizes) -- something in this render path re-derives the vertical extent from
the bounding box of what's actually being drawn, not from a fixed camera
frustum, while the horizontal extent stayed correctly locked to
orthographicWidth throughout. Whatever the exact mechanism, the fix that
doesn't depend on understanding it: keep every cube's geometry rendered at
all times (constant bounding box, `.visibility` untouched) and drive the
on/off bit through each cube's own shader color instead -- black for "off",
white for "on" -- same as how a real boolean LED wall would show a lit vs.
unlit LED without ever un-rendering the physical LED body itself.

Usage in the Script Editor (after `LedFaceCapture.load()` / plug-in already
force-loaded by maya_launcher):

    import LedFaceCapture.test_scene_setup as led_test
    led_test.build()          # creates everything, prints next steps
    led_test.set_pattern([...])   # optional: poke a specific on/off pattern
    led_test.cleanup()        # deletes everything this script created

Nothing here is meant to survive into a real scene -- every node this
creates is prefixed `ledTest_` so `cleanup()` can find and remove all of it
unambiguously.
"""
from __future__ import annotations

import maya.cmds as cmds

PREFIX = "ledTest_"
GRID_ROWS = 4
GRID_COLS = 4
CELL_SPACING = 1.5
TEXTURE_NAME = PREFIX + "texture"


def _name(*parts):
    return PREFIX + "_".join(parts)


def _cube_shader_name(row, col):
    return _name("ledShader", "r{}".format(row), "c{}".format(col))


def _build_rig_grid():
    """A rows x cols grid of small cubes standing in for individual LEDs.

    Each cube gets its OWN flat, unlit `surfaceShader` (not the default
    lambert, and not a single shared shader across all cubes) -- this is a
    boolean on/off rig, not a lit 3D object, and a shaded lambert depends on
    scene lighting that has no reason to exist here. surfaceShader is Maya's
    dedicated "just output this color, no lighting computation at all"
    utility material (the standard tool for ID/matte-style passes) -- normal
    opaque z-buffering during the capture pass already handles "whichever
    cube is nearest/unoccluded wins" for free, no per-pixel raycasting
    needed to get that same "closest mesh's color shows" result. A per-cube
    shader (rather than one shared shader for all 16) is what lets
    set_pattern() flip each cube's on/off state via outColor without ever
    touching `.visibility` -- see the module docstring for why that matters.
    """
    cubes = []
    half_w = (GRID_COLS - 1) * CELL_SPACING / 2.0
    half_h = (GRID_ROWS - 1) * CELL_SPACING / 2.0

    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            cube_name = _name("led", "r{}".format(row), "c{}".format(col))
            cube, _ = cmds.polyCube(name=cube_name, width=1.0, height=1.0, depth=0.2)
            cmds.setAttr(cube + ".translateX", col * CELL_SPACING - half_w)
            cmds.setAttr(cube + ".translateY", row * CELL_SPACING - half_h)
            cmds.setAttr(cube + ".translateZ", 0)

            shader = cmds.shadingNode("surfaceShader", asShader=True, name=_cube_shader_name(row, col))
            cmds.setAttr(shader + ".outColor", 0.0, 0.0, 0.0, type="double3")  # start "off"
            sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=shader + "SG")
            cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)
            cmds.sets(cube, edit=True, forceElement=sg)

            cubes.append(cube)
    return cubes


def _build_camera(cubes):
    """An orthographic camera framing the whole grid from +Z, looking down -Z."""
    cam_transform, cam_shape = cmds.camera(name=_name("cam"), orthographic=True)
    bbox = cmds.exactWorldBoundingBox(cubes)
    center_x = (bbox[0] + bbox[3]) / 2.0
    center_y = (bbox[1] + bbox[4]) / 2.0
    # No padding: ground truth (render_override.py's lit-pixel bbox
    # diagnostic) showed the vertical extent in this render path isn't
    # actually driven by orthographicWidth/film aperture at all -- it
    # auto-fits to the bounding box of whatever geometry is actually
    # rendered. Now that every cube renders at all times (see
    # _build_rig_grid/set_pattern), that bbox is the constant full-grid
    # size, so matching orthographicWidth to the SAME bare size (no extra
    # padding) is what makes horizontal and vertical agree.
    width = max(bbox[3] - bbox[0], bbox[4] - bbox[1])

    cmds.setAttr(cam_transform + ".translateX", center_x)
    cmds.setAttr(cam_transform + ".translateY", center_y)
    cmds.setAttr(cam_transform + ".translateZ", 10)
    cmds.setAttr(cam_transform + ".rotate", 0, 0, 0, type="double3")
    cmds.setAttr(cam_shape + ".orthographicWidth", width)
    # The capture render target is square (see _build_material_and_preview's
    # resolutionX/resolutionY, now set directly on the ledFaceMaterial
    # node), but a Maya camera's default film aperture is
    # 1.5:1 -- with a non-matching device aspect ratio, Maya stretches the
    # vertical extent to fit, which is exactly the "slightly taller" rig seen
    # on the preview plane. Forcing equal horizontal/vertical film aperture
    # makes the camera's own aspect ratio 1:1 -- confirmed via
    # render_override.py's cameraOverride() diagnostic that this DOES take
    # effect (hFilmAperture=vFilmAperture=1.0 read back correctly) -- but it
    # turned out not to matter: ground truth from postSceneRender()'s
    # lit-pixel bounding-box measurement (rig cubes evenly spaced in X and Y,
    # so a square world span must produce a square pixel bbox) showed a real
    # 0.844 width/height ratio in the capture itself, with filmFit left at
    # its default 1 ("Horizontal") -- that fit mode derives the vertical
    # extent from something other than vertical film aperture, so the square
    # aperture had no effect on it. Fill (0) is documented to stretch the
    # frustum to match the device/render-target aspect exactly, no crop or
    # letterbox -- switching to it so the frustum's aspect is driven by the
    # actual capture resolution instead of whatever Horizontal mode was
    # deriving it from.
    cmds.setAttr(cam_shape + ".horizontalFilmAperture", 1.0)
    cmds.setAttr(cam_shape + ".verticalFilmAperture", 1.0)
    cmds.setAttr(cam_shape + ".filmFit", 0)
    return cam_transform


def _build_capture_set(cubes):
    set_name = _name("captureSet")
    if cmds.objExists(set_name):
        cmds.delete(set_name)
    return cmds.sets(cubes, name=set_name)


def _build_material_and_preview(camera_transform, capture_set):
    # ledFaceMaterial is a utility node now (MPxSurfaceShadingNodeOverride),
    # feeding a real lambert's color rather than acting as the surfaceShader
    # itself -- the lambert is what Maya actually knows how to draw
    # correctly; ledFaceMaterial only needs to contribute one input to it.
    #
    # cameraMsg/captureSetMsg/resolutionX/Y used to live on a separate
    # ledCaptureConfig node -- they're now attributes directly on
    # ledFaceMaterial itself, so one node fully describes both "how to
    # capture" and "how to display" this texture channel (see
    # node_led_face_material.py). cameraMsg/captureSetMsg are message
    # attributes, connected (not set as strings) -- a string doesn't survive
    # `file -reference`, a DG connection does. Wiring them is what makes this
    # channel show up in render_override.py's per-frame scan for capture
    # channels at all.
    shader = cmds.shadingNode("ledFaceMaterial", asUtility=True, name=_name("mat"))
    cmds.setAttr(shader + ".textureName", TEXTURE_NAME, type="string")
    cmds.connectAttr(camera_transform + ".message", shader + ".cameraMsg", force=True)
    cmds.connectAttr(capture_set + ".message", shader + ".captureSetMsg", force=True)
    cmds.setAttr(shader + ".resolutionX", 64)
    cmds.setAttr(shader + ".resolutionY", 64)

    lambert = cmds.shadingNode("lambert", asShader=True, name=_name("lambert"))
    cmds.connectAttr(shader + ".outColor", lambert + ".color", force=True)

    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=lambert + "SG")
    cmds.connectAttr(lambert + ".outColor", sg + ".surfaceShader", force=True)

    preview_plane, _ = cmds.polyPlane(name=_name("previewPlane"), width=4, height=4, subdivisionsX=1, subdivisionsY=1)
    cmds.setAttr(preview_plane + ".rotateX", 90)  # face +Z, same side as the capture camera
    cmds.setAttr(preview_plane + ".translateX", (GRID_COLS - 1) * CELL_SPACING + 4)
    cmds.sets(preview_plane, edit=True, forceElement=sg)
    return shader, sg, preview_plane


def build():
    """Creates the full test rig and prints the manual steps still required."""
    if cmds.objExists(_name("mat")):
        cmds.warning("LedFaceCapture test scene already exists -- run cleanup() first.")
        return None

    cubes = _build_rig_grid()
    camera_transform = _build_camera(cubes)
    capture_set = _build_capture_set(cubes)
    shader, sg, preview_plane = _build_material_and_preview(camera_transform, capture_set)

    # Checkerboard pattern by default so it's visually obvious the capture
    # is actually reading rig state and not just showing a blank/solid frame.
    set_pattern([(r, c) for r in range(GRID_ROWS) for c in range(GRID_COLS) if (r + c) % 2 == 0])

    print(
        "LedFaceCapture test scene ready:\n"
        "  rig cubes:      {} ({}x{} grid)\n"
        "  capture camera: {}\n"
        "  capture set:    {}\n"
        "  material:       {} (textureName='{}', carries its own capture config)\n"
        "  preview plane:  {}\n"
        "\n"
        "Next steps:\n"
        "  1. cmds.pluginInfo('led_face_capture', query=True, loaded=True) -- confirm the plug-in is loaded.\n"
        "  2. In the viewport: Renderer > LED Face Capture to enable the override.\n"
        "  3. led_test.set_pattern([(0,0), (1,1), ...]) to change which cubes are 'on' and watch the preview plane update.\n"
        "  4. led_test.cleanup() when done -- switch Renderer back to 'Viewport 2.0' first.".format(
            len(cubes), GRID_ROWS, GRID_COLS, camera_transform, capture_set, shader, TEXTURE_NAME, preview_plane
        )
    )
    return {
        "cubes": cubes,
        "camera": camera_transform,
        "capture_set": capture_set,
        "shader": shader,
        "shading_group": sg,
        "preview_plane": preview_plane,
    }


def set_pattern(on_cells):
    """on_cells: iterable of (row, col) tuples to light up white; every other
    cube's shader goes black. Every cube stays visible/rendered at all times
    -- see the module docstring for why this no longer uses `.visibility`.
    """
    on_cells = set(on_cells)
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            shader = _cube_shader_name(row, col)
            if not cmds.objExists(shader):
                continue
            color = 1.0 if (row, col) in on_cells else 0.0
            cmds.setAttr(shader + ".outColor", color, color, color, type="double3")


def cleanup():
    """Deletes every node this script created (anything prefixed `ledTest_`)."""
    nodes = cmds.ls(PREFIX + "*")
    if not nodes:
        print("LedFaceCapture test scene: nothing to clean up.")
        return
    cmds.delete(nodes)
    print("LedFaceCapture test scene: removed {} node(s).".format(len(nodes)))
