"""ledFaceMaterial: a surface-shader-classified node whose Viewport 2.0 draw is
hijacked by LedFaceShaderOverride to sample whatever MTexture texture_registry
currently holds -- never a real `file` texture, never anything on disk.

Usage in-scene:
    cmds.shadingNode("ledFaceMaterial", asShader=True, name="robotFaceLED")
    cmds.setAttr("robotFaceLED.textureName", "<same string as the config node's textureName>", type="string")
    cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="robotFaceLEDSG")
    cmds.connectAttr("robotFaceLED.outColor", "robotFaceLEDSG.surfaceShader")
    cmds.sets("robotHeadFaceMesh", edit=True, forceElement="robotFaceLEDSG")

`outColor` exists only so the node is a valid surfaceShader connection target
for Hypershade/legacy renderers -- Viewport 2.0 itself never reads it, it
reads whatever LedFaceShaderOverride binds instead.
"""
from __future__ import annotations

import maya.api.OpenMaya as om2
import maya.api.OpenMayaRender as omr

from . import texture_registry

NODE_NAME = "ledFaceMaterial"
# TODO: same caveat as node_led_capture_config.NODE_ID -- placeholder from the
# devkit example range, replace with a studio-issued id before shipping.
NODE_ID = om2.MTypeId(0x0011D701)
DRAW_CLASSIFICATION = "drawdb/shader/surface/ledFaceMaterial"
DRAW_REGISTRANT_ID = "ledFaceMaterialRegistrant"


class LedFaceMaterial(om2.MPxNode):
    id = NODE_ID

    textureName = None
    outColor = None

    @staticmethod
    def creator():
        return LedFaceMaterial()

    @staticmethod
    def initialize():
        str_fn = om2.MFnTypedAttribute()
        num_fn = om2.MFnNumericAttribute()

        default_string = om2.MFnStringData().create("")
        LedFaceMaterial.textureName = str_fn.create(
            "textureName", "texName", om2.MFnData.kString, default_string
        )
        str_fn.storable = True
        str_fn.keyable = False
        om2.MPxNode.addAttribute(LedFaceMaterial.textureName)

        LedFaceMaterial.outColor = num_fn.createColor("outColor", "oc")
        num_fn.storable = False
        num_fn.writable = False
        om2.MPxNode.addAttribute(LedFaceMaterial.outColor)


class LedFaceShaderOverride(omr.MPxShaderOverride):
    """Rebinds the live capture texture into this node's VP2 draw every refresh.

    NOTE (verify inside real Maya): the exact virtual method set/names for
    MPxShaderOverride have drifted slightly across Maya releases. If the
    plug-in fails to load or the override never seems to activate, run
    `help(maya.api.OpenMayaRender.MPxShaderOverride)` in the Script Editor
    and reconcile method names against what's below.
    """

    @staticmethod
    def creator(obj):
        return LedFaceShaderOverride(obj)

    def __init__(self, obj):
        omr.MPxShaderOverride.__init__(self, obj)
        self._shader_instance = None

    def initialize(self, obj):
        shader_mgr = omr.MRenderer.getShaderManager()
        if shader_mgr is None:
            return None
        # k3dSolidTextureShader = stock unlit textured shader. If this enum
        # member doesn't exist in your Maya version, run
        #   [s for s in dir(omr.MShaderManager.MStockShader) if "texture" in s.lower()]
        # in the Script Editor and swap in whatever it reports.
        self._shader_instance = shader_mgr.getStockShader(
            omr.MShaderManager.MStockShader.k3dSolidTextureShader
        )
        return self._shader_instance

    def updateDG(self, obj):
        pass

    def updateDevice(self):
        if self._shader_instance is None:
            return
        node_fn = om2.MFnDependencyNode(self.object())
        texture_name = node_fn.findPlug("textureName", False).asString()
        texture = texture_registry.get_texture(texture_name)
        if texture is None:
            return
        assignment = omr.MTextureAssignment()
        assignment.texture = texture
        # "map" is k3dSolidTextureShader's texture parameter name. If binding
        # silently has no visible effect, inspect
        # self._shader_instance.parameterList() to confirm the real name.
        self._shader_instance.setParameter("map", assignment)

    def handlesDraw(self, context):
        return False

    def isTransparent(self):
        return False

    def supportsAdvancedTransparency(self):
        return False


def register(plugin_fn):
    plugin_fn.registerNode(
        NODE_NAME,
        LedFaceMaterial.id,
        LedFaceMaterial.creator,
        LedFaceMaterial.initialize,
        om2.MPxNode.kDependNode,
        DRAW_CLASSIFICATION,
    )
    omr.MDrawRegistry.registerShaderOverrideCreator(
        DRAW_CLASSIFICATION, DRAW_REGISTRANT_ID, LedFaceShaderOverride.creator
    )


def deregister(plugin_fn):
    omr.MDrawRegistry.deregisterShaderOverrideCreator(DRAW_CLASSIFICATION, DRAW_REGISTRANT_ID)
    plugin_fn.deregisterNode(LedFaceMaterial.id)
