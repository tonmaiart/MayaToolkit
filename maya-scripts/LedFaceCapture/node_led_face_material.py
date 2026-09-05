"""ledFaceMaterial: a utility node whose VP2 draw is supplied by a custom
shading *fragment* (via MPxSurfaceShadingNodeOverride), meant to feed its
`outColor` into a real, already-correctly-drawn surface shader (e.g. a
`lambert`) rather than replacing the whole material like the earlier
MPxShaderOverride attempt did.

Architecture change history: the first version of this file implemented
MPxShaderOverride directly (a from-scratch replacement shader for VP2). That
was abandoned after exhausting every discoverable fix (shaderInstance() was
missing, stock shader parameter binding all confirmed working via
diagnostics) with the render item still refusing to draw anything -- not
even a hardcoded solid color -- while a plain `lambert` on the same mesh
rendered correctly. MPxSurfaceShadingNodeOverride only has to supply ONE
utility node's contribution to an already-working shading network (the
lambert's own technique handles the rest), which is a much smaller surface
to get wrong.

Usage in-scene (note the new wiring -- through a real lambert, not straight
to the shading engine):
    cmds.shadingNode("ledFaceMaterial", asUtility=True, name="robotFaceLED")
    cmds.setAttr("robotFaceLED.textureName", "<same string as the config node's textureName>", type="string")
    lam = cmds.shadingNode("lambert", asShader=True, name="robotFaceLED_lambert")
    cmds.connectAttr("robotFaceLED.outColor", lam + ".color")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="robotFaceLEDSG")
    cmds.connectAttr(lam + ".outColor", sg + ".surfaceShader")
    cmds.sets("robotHeadFaceMesh", edit=True, forceElement=sg)

Phase 1 (current): the registered fragment ignores `textureName`/the capture
texture entirely and just outputs a hardcoded solid red, to validate that
MPxSurfaceShadingNodeOverride + a from-scratch fragment can draw *anything*
on this Maya version before reintroducing texture sampling. The fragment XML
schema below is reconstructed from memory/pattern, not looked up live --
expect to iterate on it against whatever error (if any) Maya reports on
first load.
"""
from __future__ import annotations

import maya.api.OpenMaya as om2
import maya.api.OpenMayaRender as omr

from . import _debug

NODE_NAME = "ledFaceMaterial"
# TODO: same caveat as node_led_capture_config.NODE_ID -- placeholder from the
# devkit example range, replace with a studio-issued id before shipping.
NODE_ID = om2.MTypeId(0x0011D701)
# "operation" (a utility node contributing a value into a larger shading
# network), not "surface" (a standalone, complete surface shader) -- matches
# how Maya's own utility nodes are classified for VP2 draw registration.
# The ":utility/general" suffix is required too -- confirmed via
# cmds.getClassification("multiplyDivide") / ("condition") on Maya 2026,
# both of which return a combined "drawdb/shader/operation/<node>:<hypershade
# category>" string, not the drawdb path alone. Without it, our
# classification never told Hypershade/the shading-graph builder this is a
# real utility node at all, which is a very plausible reason the fragment
# never got wired into lambert.color's fragment graph regardless of how
# outputForConnection/the base override class were fixed.
DRAW_REGISTRY_KEY = "drawdb/shader/operation/ledFaceMaterial"
# registerNode's classification param wants the FULL combined string
# (drawdb path + Hypershade category); MDrawRegistry's registration calls
# want just the "drawdb/..." key on its own -- keeping these as two
# constants instead of splitting DRAW_REGISTRY_KEY out of one combined
# string at every call site.
NODE_CLASSIFICATION = DRAW_REGISTRY_KEY + ":utility/general"
DRAW_REGISTRANT_ID = "ledFaceMaterialRegistrant"

FRAGMENT_NAME = "ledFaceCaptureFragment"

# Phase 1: no inputs at all, just a hardcoded color, to isolate "can this
# mechanism draw anything" from "can it sample our texture". Providing all
# three of HLSL/GLSL/Cg so MFragmentManager can pick whichever matches
# omr.MRenderer.drawAPI() -- unconfirmed whether all three blocks are
# actually required for that selection to succeed, or whether an unused one
# is silently ignored, or whether a missing one for the active API is a hard
# error. First thing to try trimming if this fails to register at all.
# Schema below is copied structurally from Maya's own built-in
# "mayaRedFromColor4" fragment (dumped via
# frag_mgr.getFragmentXML("mayaRedFromColor4") on Maya 2026) -- a genuine
# `type="plumbing"` UTILITY fragment (feeds a value into another node's
# input, same role ledFaceMaterial needs), unlike the earlier
# "mayaSolidColor" template this was first copied from, which is
# `type="surface"` (a complete, standalone shading result) -- registering a
# surface-typed fragment worked (hasFragment() came back True even after
# borrowing it directly for a live test), but it still rendered solid black
# once connected into lambert.color, suggesting Maya may not treat a
# surface-typed fragment's output as valid for feeding a plain color slot on
# another shader the way a plumbing-typed one is meant to. Also matched here
# vs. the surface-typed attempt: `feature_level="20"`, a `uiName` attribute,
# and a `<keyword value="plumbing" />` element, none of which the earlier
# draft had -- still no help()/dir() equivalent for XML schema, so these are
# copied structurally rather than individually confirmed necessary.
_FRAGMENT_XML = """<fragment uiName="{name}" name="{name}" type="plumbing" class="ShadeFragment" version="1.0" feature_level="20">
  <description><![CDATA[Solid-color test fragment for ledFaceMaterial (phase 1, no texture sampling yet).]]></description>
  <keyword value="plumbing" />
  <properties>
  </properties>
  <values>
  </values>
  <outputs>
    <float4 name="{name}" />
  </outputs>
  <implementation>
    <implementation render="OGSRenderer" language="HLSL" lang_version="11.0">
      <function_name val="ledFaceCaptureFragmentImpl" />
      <source>
        <![CDATA[
float4 ledFaceCaptureFragmentImpl()
{{
    return float4(1.0, 0.0, 0.0, 1.0);
}}
]]>
      </source>
    </implementation>
    <implementation render="OGSRenderer" language="Cg" lang_version="2.1">
      <function_name val="ledFaceCaptureFragmentImpl" />
      <source>
        <![CDATA[
float4 ledFaceCaptureFragmentImpl()
{{
    return float4(1.0, 0.0, 0.0, 1.0);
}}
]]>
      </source>
    </implementation>
    <implementation render="OGSRenderer" language="GLSL" lang_version="3.0">
      <function_name val="ledFaceCaptureFragmentImpl" />
      <source>
        <![CDATA[
vec4 ledFaceCaptureFragmentImpl()
{{
    return vec4(1.0, 0.0, 0.0, 1.0);
}}
]]>
      </source>
    </implementation>
  </implementation>
</fragment>""".format(name=FRAGMENT_NAME)


def _ensure_fragment_registered():
    try:
        frag_mgr = omr.MRenderer.getFragmentManager()
        if frag_mgr is None:
            return False
        if frag_mgr.hasFragment(FRAGMENT_NAME):
            return True
        registered_name = frag_mgr.addShadeFragmentFromBuffer(_FRAGMENT_XML.encode("utf-8"), False)
        print("LedFaceCapture: fragment registration returned", repr(registered_name))
        return bool(registered_name)
    except Exception:
        _debug.log_exception("_ensure_fragment_registered")
        return False


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


class LedFaceShadingNodeOverride(omr.MPxShadingNodeOverride):
    """Phase 1: supplies the hardcoded-red fragment for ledFaceMaterial's
    VP2 draw. No texture_registry involvement yet -- that comes back once
    this mechanism is confirmed to draw anything at all.

    Base class fixed from MPxSurfaceShadingNodeOverride to plain
    MPxShadingNodeOverride: per Autodesk's own docs (Shading Node Overrides
    devhelp page), MPxSurfaceShadingNodeOverride is specifically for a node
    "connected directly to a Maya shading engine" -- i.e. a complete,
    standalone surface shader, which is exactly the design this file moved
    away from. ledFaceMaterial is a utility node feeding one input
    (lambert.color) on another shader, which is what the plain
    MPxShadingNodeOverride + MDrawRegistry.registerShadingNodeOverrideCreator
    pairing is for (confirmed as a genuinely separate registration function
    from registerSurfaceShadingNodeOverrideCreator via dir(MDrawRegistry)).
    The Surface subclass's extra methods (primaryColorParameter,
    transparencyParameter, bumpAttribute) don't exist on this base at all --
    confirmed via dir(MPxShadingNodeOverride) -- so this was never going to
    connect correctly no matter how outputForConnection/the fragment XML
    were fixed.
    """

    @staticmethod
    def creator(obj):
        return LedFaceShadingNodeOverride(obj)

    def __init__(self, obj):
        omr.MPxShadingNodeOverride.__init__(self, obj)

    def fragmentName(self):
        return FRAGMENT_NAME

    def outputForConnection(self, source_plug, destination_plug):
        # Default implementation returns the name of our node's own output
        # ATTRIBUTE ("outColor"), not the fragment's output PARAMETER name --
        # confirmed via help() that a mismatch here means "the fragment will
        # not be connected to the overall shading effect" at all, which
        # produces exactly a solid-black render item with no error anywhere.
        return FRAGMENT_NAME


def register(plugin_fn):
    plugin_fn.registerNode(
        NODE_NAME,
        LedFaceMaterial.id,
        LedFaceMaterial.creator,
        LedFaceMaterial.initialize,
        om2.MPxNode.kDependNode,
        NODE_CLASSIFICATION,
    )
    _ensure_fragment_registered()
    omr.MDrawRegistry.registerShadingNodeOverrideCreator(
        DRAW_REGISTRY_KEY, DRAW_REGISTRANT_ID, LedFaceShadingNodeOverride.creator
    )


def deregister(plugin_fn):
    omr.MDrawRegistry.deregisterShadingNodeOverrideCreator(DRAW_REGISTRY_KEY, DRAW_REGISTRANT_ID)
    plugin_fn.deregisterNode(LedFaceMaterial.id)
