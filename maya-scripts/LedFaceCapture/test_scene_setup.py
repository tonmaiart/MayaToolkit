"""Throwaway test scene for LedFaceCapture: builds a fake boolean LED rig (a
grid of cubes with visibility as the on/off bit), an ortho capture camera, the
config/material nodes, and a plain preview plane to display the result -- so
the whole capture -> RAM texture -> viewport-material pipeline can be
smoke-tested without touching a real robot rig.

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


def _build_rig_grid():
    """A rows x cols grid of small cubes standing in for individual LEDs."""
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
            cubes.append(cube)
    return cubes


def _build_camera(cubes):
    """An orthographic camera framing the whole grid from +Z, looking down -Z."""
    cam_transform, cam_shape = cmds.camera(name=_name("cam"), orthographic=True)
    bbox = cmds.exactWorldBoundingBox(cubes)
    center_x = (bbox[0] + bbox[3]) / 2.0
    center_y = (bbox[1] + bbox[4]) / 2.0
    width = max(bbox[3] - bbox[0], bbox[4] - bbox[1]) * 1.2  # 20% padding

    cmds.setAttr(cam_transform + ".translateX", center_x)
    cmds.setAttr(cam_transform + ".translateY", center_y)
    cmds.setAttr(cam_transform + ".translateZ", 10)
    cmds.setAttr(cam_transform + ".rotate", 0, 0, 0, type="double3")
    cmds.setAttr(cam_shape + ".orthographicWidth", width)
    return cam_transform


def _build_capture_set(cubes):
    set_name = _name("captureSet")
    if cmds.objExists(set_name):
        cmds.delete(set_name)
    return cmds.sets(cubes, name=set_name)


def _build_config(camera_transform, capture_set):
    config_name = _name("config")
    config = cmds.createNode("ledCaptureConfig", name=config_name)
    cmds.setAttr(config + ".cameraName", camera_transform, type="string")
    cmds.setAttr(config + ".captureSetName", capture_set, type="string")
    cmds.setAttr(config + ".textureName", TEXTURE_NAME, type="string")
    cmds.setAttr(config + ".resolutionX", 64)
    cmds.setAttr(config + ".resolutionY", 64)
    return config


def _build_material_and_preview():
    shader = cmds.shadingNode("ledFaceMaterial", asShader=True, name=_name("mat"))
    cmds.setAttr(shader + ".textureName", TEXTURE_NAME, type="string")

    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=shader + "SG")
    cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)

    preview_plane, _ = cmds.polyPlane(name=_name("previewPlane"), width=4, height=4, subdivisionsX=1, subdivisionsY=1)
    cmds.setAttr(preview_plane + ".rotateX", 90)  # face +Z, same side as the capture camera
    cmds.setAttr(preview_plane + ".translateX", (GRID_COLS - 1) * CELL_SPACING + 4)
    cmds.sets(preview_plane, edit=True, forceElement=sg)
    return shader, sg, preview_plane


def build():
    """Creates the full test rig and prints the manual steps still required."""
    if cmds.objExists(_name("config")):
        cmds.warning("LedFaceCapture test scene already exists -- run cleanup() first.")
        return None

    cubes = _build_rig_grid()
    camera_transform = _build_camera(cubes)
    capture_set = _build_capture_set(cubes)
    config = _build_config(camera_transform, capture_set)
    shader, sg, preview_plane = _build_material_and_preview()

    # Checkerboard pattern by default so it's visually obvious the capture
    # is actually reading rig state and not just showing a blank/solid frame.
    set_pattern([(r, c) for r in range(GRID_ROWS) for c in range(GRID_COLS) if (r + c) % 2 == 0])

    print(
        "LedFaceCapture test scene ready:\n"
        "  rig cubes:      {} ({}x{} grid)\n"
        "  capture camera: {}\n"
        "  capture set:    {}\n"
        "  config node:    {}\n"
        "  material:       {} (textureName='{}')\n"
        "  preview plane:  {}\n"
        "\n"
        "Next steps:\n"
        "  1. cmds.pluginInfo('led_face_capture', query=True, loaded=True) -- confirm the plug-in is loaded.\n"
        "  2. In the viewport: Renderer > LED Face Capture to enable the override.\n"
        "  3. led_test.set_pattern([(0,0), (1,1), ...]) to change which cubes are 'on' and watch the preview plane update.\n"
        "  4. led_test.cleanup() when done -- switch Renderer back to 'Viewport 2.0' first.".format(
            len(cubes), GRID_ROWS, GRID_COLS, camera_transform, capture_set, config, shader, TEXTURE_NAME, preview_plane
        )
    )
    return {
        "cubes": cubes,
        "camera": camera_transform,
        "capture_set": capture_set,
        "config": config,
        "shader": shader,
        "shading_group": sg,
        "preview_plane": preview_plane,
    }


def set_pattern(on_cells):
    """on_cells: iterable of (row, col) tuples to show; every other cube is hidden."""
    on_cells = set(on_cells)
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            cube = _name("led", "r{}".format(row), "c{}".format(col))
            if not cmds.objExists(cube):
                continue
            cmds.setAttr(cube + ".visibility", (row, col) in on_cells)


def cleanup():
    """Deletes every node this script created (anything prefixed `ledTest_`)."""
    nodes = cmds.ls(PREFIX + "*")
    if not nodes:
        print("LedFaceCapture test scene: nothing to clean up.")
        return
    cmds.delete(nodes)
    print("LedFaceCapture test scene: removed {} node(s).".format(len(nodes)))
