"""ledCaptureConfig: a config-only DG node the render override reads every frame.

Holds no draw logic of its own -- it just tells LedFaceCaptureOverride which
camera to render the capture pass from, which object set to isolate (the
boolean-rig geometry), the offscreen resolution, and which texture_registry
key to publish the captured pixels under. Create one with:

    cmds.createNode("ledCaptureConfig")

and set its string attributes to real scene node names via the Attribute
Editor or setAttr.
"""
from __future__ import annotations

import maya.api.OpenMaya as om2

NODE_NAME = "ledCaptureConfig"
# TODO: this is a placeholder from the devkit's example-only ID block
# (0x00080000-0x000fffff). Request/use the studio's own registered ID block
# before this ships anywhere shared, to avoid colliding with another
# in-house plug-in that picked the same placeholder.
NODE_ID = om2.MTypeId(0x0011D700)


class LedCaptureConfig(om2.MPxNode):
    id = NODE_ID

    cameraName = None
    captureSetName = None
    textureName = None
    resolutionX = None
    resolutionY = None

    @staticmethod
    def creator():
        return LedCaptureConfig()

    @staticmethod
    def initialize():
        str_fn = om2.MFnTypedAttribute()
        num_fn = om2.MFnNumericAttribute()
        default_string = om2.MFnStringData().create("")

        LedCaptureConfig.cameraName = str_fn.create(
            "cameraName", "cam", om2.MFnData.kString, default_string
        )
        str_fn.storable = True
        str_fn.keyable = False
        om2.MPxNode.addAttribute(LedCaptureConfig.cameraName)

        LedCaptureConfig.captureSetName = str_fn.create(
            "captureSetName", "capSet", om2.MFnData.kString, default_string
        )
        str_fn.storable = True
        str_fn.keyable = False
        om2.MPxNode.addAttribute(LedCaptureConfig.captureSetName)

        LedCaptureConfig.textureName = str_fn.create(
            "textureName", "texName", om2.MFnData.kString, default_string
        )
        str_fn.storable = True
        str_fn.keyable = False
        om2.MPxNode.addAttribute(LedCaptureConfig.textureName)

        LedCaptureConfig.resolutionX = num_fn.create(
            "resolutionX", "resX", om2.MFnNumericData.kInt, 64
        )
        num_fn.storable = True
        om2.MPxNode.addAttribute(LedCaptureConfig.resolutionX)

        LedCaptureConfig.resolutionY = num_fn.create(
            "resolutionY", "resY", om2.MFnNumericData.kInt, 64
        )
        num_fn.storable = True
        om2.MPxNode.addAttribute(LedCaptureConfig.resolutionY)


def register(plugin_fn):
    plugin_fn.registerNode(
        NODE_NAME,
        LedCaptureConfig.id,
        LedCaptureConfig.creator,
        LedCaptureConfig.initialize,
        om2.MPxNode.kDependNode,
    )


def deregister(plugin_fn):
    plugin_fn.deregisterNode(LedCaptureConfig.id)
