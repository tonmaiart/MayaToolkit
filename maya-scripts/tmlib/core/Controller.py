from tmlib.core import Scene, Utility, Transform, File
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin
from tmlib.module.PySide import QtWidgets, QtCore, QtGui
import os, importlib, webbrowser, inspect, configparser
import maya.mel as mel
import maya.cmds as cmds
import json
import tmlib


def _short_name(node):
    """Return the short (non-path) name of a node string."""
    return node.split("|")[-1]


def _node_only(attr_or_node):
    """Strip attribute suffix from a node.attr string."""
    return attr_or_node.split(".")[0]


def clone_style(list_target=None):
    """
    Use to clone style of given controllers (line width and color)

    Input list = [target1,target2,...,ref]

    Shapes are matched by index (target shape N gets ref shape N, extra
    target shapes get the ref's last one). Every override color attr is
    copied -- index AND RGB -- because AdvancedSkeleton's rebuild ("keep
    curve shapes") only restores ".overrideColor"; this way a rebuilt
    control still falls back to the ref's index color.
    """

    if list_target is None:
        list_target = cmds.ls(sl=1, typ="transform", l=1)

    if len(list_target) < 2:
        cmds.warning("Select target control(s), then the reference control last.")
        return

    selection = list_target

    # sort shape, reference is last one
    ref = list_target[-1]
    list_ref_shape = _curve_shapes(ref)
    if not list_ref_shape:
        cmds.warning("Reference '{}' has no curve shape.".format(ref))
        return

    list_target = list_target[0 : len(list_target) - 1]

    style_attrs = [
        "lineWidth",
        "overrideEnabled",
        "overrideRGBColors",
        "overrideColor",
        "overrideColorR",
        "overrideColorG",
        "overrideColorB",
    ]

    # apply
    for target in list_target:
        for i, shape in enumerate(_curve_shapes(target)):
            ref_shape = list_ref_shape[min(i, len(list_ref_shape) - 1)]
            for attr in style_attrs:
                plug = "{}.{}".format(shape, attr)
                # AS drives some override attrs (e.g. face ctrl visibility) -- leave those
                if cmds.getAttr(plug, lock=True) or cmds.listConnections(plug, s=1, d=0):
                    continue
                cmds.setAttr(plug, cmds.getAttr("{}.{}".format(ref_shape, attr)))

    cmds.select(selection, r=1)

    cmds.inViewMessage(amg="Clone Style Complete.", pos="botCenter", fade=True)


def get_official_curve_data(index):
    """Get curve shape list data of position from index"""

    dict_curve_data = File.load_json_file_to_dict(
        os.path.join(os.path.dirname(tmlib.__file__), "data", "Controllers.json")
    )

    return dict_curve_data["ctrl_{}".format(str(index).zfill(2))]


# ------------------------------------------------------------------
# AdvancedSkeleton controller gallery
# ------------------------------------------------------------------

# path -> (mtime, gallery dict); the .ma is parsed once per change
_AS_GALLERY_CACHE = {}


def get_advanced_skeleton_gallery_path():
    """asGallery.ma of the AdvancedSkeleton install, or None if not found.

    Looks at $ADVANCEDSKELETON_ROOT (set by the ukore_advanced_skeleton
    plugin) first, then at an already-sourced AdvancedSkeleton.mel.
    """
    candidates = []
    root = os.environ.get("ADVANCEDSKELETON_ROOT")
    if root:
        candidates.append(root)
    try:
        if mel.eval('exists "asGetScriptLocation"'):
            candidates.append(mel.eval("asGetScriptLocation"))
    except RuntimeError:
        pass

    for root in candidates:
        path = os.path.join(root, "AdvancedSkeletonFiles", "div", "asGallery.ma")
        if os.path.isfile(path):
            return path
    return None


def _parse_nurbs_curve_data(tokens):
    """Tokens of a `setAttr ".cc" -type "nurbsCurve" ...` value -> curve dict."""
    degree, spans, form = int(tokens[0]), int(tokens[1]), int(tokens[2])
    rational = tokens[3] == "yes"
    dimension = int(tokens[4])
    knot_count = int(tokens[5])
    knots = [float(value) for value in tokens[6 : 6 + knot_count]]

    index = 6 + knot_count
    cv_count = int(tokens[index])
    stride = dimension + (1 if rational else 0)
    cvs = []
    for i in range(cv_count):
        start = index + 1 + i * stride
        point = [float(value) for value in tokens[start : start + dimension]]
        cvs.append(tuple((point + [0.0, 0.0, 0.0])[:3]))

    return {"degree": degree, "spans": spans, "form": form, "knots": knots, "cvs": cvs}


def get_advanced_skeleton_gallery():
    """{shape_name: [curve dict, ...]} from AdvancedSkeleton's controller gallery.

    Read straight from asGallery.ma (no scene import), in the file's order --
    the same shapes AS's "import controller gallery" brings in. A shape can
    hold several curves (e.g. "Gear").
    """
    path = get_advanced_skeleton_gallery_path()
    if not path:
        raise RuntimeError(
            "AdvancedSkeleton asGallery.ma not found -- set ADVANCEDSKELETON_ROOT "
            "or source AdvancedSkeleton.mel first."
        )

    mtime = os.path.getmtime(path)
    cached = _AS_GALLERY_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]

    with open(path, "r") as file:
        statements = file.read().split(";")

    gallery = {}
    curve_parent = None
    for statement in statements:
        words = statement.split()
        if len(words) < 4:
            continue

        if words[0] == "createNode" and "-n" in words:
            name = words[words.index("-n") + 1].strip('"')
            parent = words[words.index("-p") + 1].strip('"') if "-p" in words else None
            if words[1] == "transform" and parent == "ControllerGallery":
                gallery[name] = []
            curve_parent = parent if words[1] == "nurbsCurve" else None

        elif words[:4] == ["setAttr", '".cc"', "-type", '"nurbsCurve"'] and curve_parent in gallery:
            gallery[curve_parent].append(_parse_nurbs_curve_data(words[4:]))

    gallery = {name: curves for name, curves in gallery.items() if curves}
    _AS_GALLERY_CACHE[path] = (mtime, gallery)
    return gallery


def create_advanced_skeleton_shape(shape_name, name="control"):
    """Transform holding the given AS gallery shape's curve(s), named like AS ("<name>Shape")."""
    transform = cmds.createNode("transform", name=name)

    for data in get_advanced_skeleton_gallery()[shape_name]:
        tmp_curve = cmds.curve(
            degree=data["degree"],
            point=data["cvs"],
            knot=data["knots"],
            periodic=data["form"] == 2,
        )
        for shape in cmds.listRelatives(tmp_curve, shapes=True, fullPath=True) or []:
            cmds.parent(shape, transform, shape=True, relative=True)
        cmds.delete(tmp_curve)

    set_proper_shape_name(transform)
    return transform


def create_curve_from_data(dict_curve_data, name="control"):
    """
    Create curve by given shape data list (list)
    """
    if not dict_curve_data:
        return None

    # get data from dict to list for each shape
    list_shape = []
    list_pos_cv = []
    list_width = []
    list_color = []

    list_spans = []
    list_degree = []
    list_form = []

    for shape_name in dict_curve_data.keys():
        list_shape.append(shape_name)
        list_pos_cv.append(dict_curve_data[shape_name]["cvPositions"])
        list_width.append(dict_curve_data[shape_name]["lineWidth"])
        list_color.append(dict_curve_data[shape_name]["colorData"])
        list_spans.append(dict_curve_data[shape_name]["spans"])
        list_degree.append(dict_curve_data[shape_name]["degree"])
        list_form.append(dict_curve_data[shape_name]["form"])

    temp_curves = []

    # Create each shape as a temporary curve
    for i, list_pos in enumerate(list_pos_cv):
        if len(list_pos) < 2:
            continue

        if list_form[i] in (0, 1):  # open / closed curve
            crv = cmds.curve(
                p=list_pos, d=list_degree[i]
            )  # degree 1 (linear), change to d=3 for cubic
        elif list_form[i] == 2 and list_degree[i] == 1:
            list_pos = list_pos + [list_pos[0]]
            crv = cmds.curve(
                p=list_pos, d=list_degree[i]
            )  # degree 1 (linear), change to d=3 for cubic
        elif list_form[i] == 2:  # circle
            crv = cmds.circle(s=list_spans[i], d=list_degree[i], ch=0)[0]
            crv_shape = cmds.listRelatives(crv, c=1, s=1)[0]

            # match position of cv
            for j, cv_pos in enumerate(list_pos_cv[i]):
                cmds.xform("{}.cv[{}]".format(crv_shape, j), t=cv_pos, os=1)

        else:
            continue

        temp_curves.append(crv)

    if not temp_curves:
        return None

    # Assign Style
    for i, curve_transform in enumerate(temp_curves):
        curve_shape = cmds.listRelatives(curve_transform, c=1, s=1, typ="nurbsCurve")[0]

        set_color(color_data=list_color[i], list_input_transform=[curve_shape])
        set_line_width(width=list_width[i], list_input_transform=[curve_shape])

    # Parent all shapes under the first curve transform
    main_curve = temp_curves[0]
    for crv in temp_curves[1:]:
        shapes = cmds.listRelatives(crv, shapes=True, fullPath=True)
        for s in shapes:
            cmds.parent(s, main_curve, shape=True, relative=True)
        cmds.delete(crv)

    # Rename main transform
    final_curve = cmds.rename(main_curve, name)

    return final_curve


def open_color_dialog():
    """
    Launch color dialog for set rgb color
    """

    # Open the QColorDialog to choose a color
    color = QtWidgets.QColorDialog.getColor()

    set_color(
        color_data=[
            False,
            [(color.red() / 255), (color.green() / 255), (color.blue() / 255)],
        ]
    )


def set_color(color_data, list_input_transform=None):
    """
    list_input_transform : support for both transform and shape.
    color_data(list) : [bool,integer index or list rgb] for example coloring index = [True,3] , coloring rgb = [False,(2.5,2.5,2.5)] and disable color = [None,None]

    """
    # get input control
    if list_input_transform:
        list_target = [str(obj) for obj in list_input_transform]
    else:
        # get selection
        list_target = cmds.ls(sl=1)

        # refine selection
        for sel in list_target:
            if "." in str(sel):
                isolate_clear()
                break

    list_shape = []

    # filter shape
    for sel in list_target:
        # sel shape
        if cmds.objectType(sel, isa="nurbsCurve"):
            list_shape.append(sel)

        # child shape
        list_child = cmds.listRelatives(sel, c=1, s=1, f=1)

        if list_child:
            for child in list_child:
                if cmds.objectType(child) == "nurbsCurve":
                    list_shape.append(child)

    # apply color
    is_index, color_value = color_data

    if list_shape:
        for shape in list_shape:
            shape = _node_only(str(shape))

            if color_data == [None, None]:
                cmds.setAttr(shape + ".overrideEnabled", False)

            elif is_index:
                cmds.setAttr(shape + ".overrideEnabled", True)
                cmds.setAttr(f"{shape}.overrideRGBColors", 0)
                cmds.setAttr(shape + ".overrideColor", color_value)

            elif not is_index:
                cmds.setAttr(shape + ".overrideEnabled", True)
                cmds.setAttr(f"{shape}.overrideRGBColors", 1)
                cmds.setAttr(
                    shape + ".overrideColorRGB",
                    color_value[0],
                    color_value[1],
                    color_value[2],
                    typ="double3",
                )


def create_control(index):
    dict_curve_data = get_official_curve_data(index=index)
    return _create_or_replace_control(lambda: create_curve_from_data(dict_curve_data=dict_curve_data))


def create_advanced_skeleton_control(shape_name):
    """Create mode: new control of an AS gallery shape. Replace mode
    (something selected): swap the selected controls' shapes for it, keeping
    each control's own color/width and AdvancedSkeleton set membership."""
    return _create_or_replace_control(lambda: create_advanced_skeleton_shape(shape_name))


def _create_or_replace_control(create_item):
    """create_item : function that create temp shape transform and return its name"""
    # get selection before create temp item (creating curve change selection)
    selection = cmds.ls(sl=1, typ="transform", l=1)
    replace = bool(cmds.ls(sl=1))

    if replace and not selection:
        raise Exception("Please Select Targets before replace shape")

    item_name = create_item()

    if replace:  # replace mode

        # each target keeps its own color / line width (clone_shape default)
        for sel in selection:
            clone_shape([sel, item_name], match_bounding_box=True)

        cmds.select(selection, r=1)

        cmds.inViewMessage(amg="Shape Updated.", pos="botCenter", fade=True)

        control = selection
    elif not replace:  # create mode
        cmds.select(cl=1)

        control = cmds.circle(ch=0)[0]
        clone_shape([control, item_name])

        cmds.select(control)

        cmds.inViewMessage(amg="Shape Created.", pos="botCenter", fade=True)

    # delete temp item
    cmds.delete(item_name)

    return control


def isolate_edit(snap=False, isolate=False):
    """Isolate panel , control vertex editing"""

    def get_curve_cv(shape_path):
        """return the list shape data (spans, degree, list_position) reference by input shape name

        shape_path : [str] shape name or path"""

        list_shape_data = []
        spans = cmds.getAttr("{}.spans".format(shape_path))
        degree = cmds.getAttr("{}.degree".format(shape_path))
        cv_amount = spans + degree
        list_position = []

        for i in range(cv_amount):
            local_translate = cmds.xform(
                "{}.cv[{}]".format(shape_path, i), os=1, t=1, q=1
            )
            local_translate = ["%.4f" % value for value in local_translate]
            list_position.append(local_translate)

        list_shape_data.append(spans)
        list_shape_data.append(degree)
        list_shape_data.append(list_position)

        return list_shape_data

    selection = cmds.ls(sl=1)
    cmds.select(cl=1)

    for sel in selection:
        if cmds.objectType(sel, isa="nurbsCurve"):
            cmds.select(sel, add=1)

        child_shape = cmds.listRelatives(sel, c=1, s=1, f=1)

        if child_shape:
            cmds.select(child_shape, add=1)

    current_select = cmds.ls(sl=1, typ="nurbsCurve")
    if current_select:
        if isolate:  # isolate
            currentPanel = cmds.getPanel(withFocus=True)
            cmds.isolateSelect(currentPanel, s=1)
            cmds.isolateSelect(currentPanel, addSelected=True)

        if snap:  # Frame the selected objects in the viewport
            cmds.viewFit()

    mel.eval("changeSelectMode -component;")

    # for shape in current_select:
    for shape in current_select:
        data = get_curve_cv(shape)
        cmds.select("{}.cv[0:{}]".format(shape, data[0] + data[1] - 1), add=1)


def isolate_clear():
    """Deselect and exist from isolate panel , control vertex editing"""

    # currentPanel = cmds.getPanel(withFocus=True)
    # cmds.isolateSelect(currentPanel, s=0)

    list_transform = []
    selection = cmds.ls(sl=1)

    if selection:
        for sel in selection:

            # if sel is cv
            if "." in str(sel):
                sel = sel.split(".")[0]
                list_transform.extend(cmds.listRelatives(sel, p=1))

            # transform case
            elif cmds.objectType(sel, isa="transform"):
                list_transform.append(sel)

    mel.eval("changeSelectMode -object;")
    cmds.select(list_transform)



def flip_shape(axis: str):
    """Mirror the selected controls' curve CVs across a local axis.

    Pure math on each CV's object-space (local) position -- the chosen
    component is negated, nothing else is touched: no temp duplicate, no
    freeze, no shape swap, so shape names, sets, colors and connections
    (everything AdvancedSkeleton relies on) stay as they are.

    axis: "x", "y" or "z". Works on selected transforms or curve shapes.
    """
    component = "xyz".index(axis.lower())

    shapes = []
    for sel in cmds.ls(sl=1, l=1, o=1) or []:
        if cmds.objectType(sel, isa="nurbsCurve"):
            candidates = [sel]
        else:
            candidates = _curve_shapes(sel)
        for shape in candidates:
            if shape not in shapes:
                shapes.append(shape)

    cmds.undoInfo(ock=1)
    try:
        for shape in shapes:
            cvs = cmds.ls(shape + ".cv[*]", fl=1)
            positions = cmds.xform(cvs, q=1, os=1, t=1)
            for i, cv in enumerate(cvs):
                position = positions[i * 3 : i * 3 + 3]
                position[component] = -position[component]
                cmds.xform(cv, os=1, t=position)
    finally:
        cmds.undoInfo(cck=1)


def set_line_width(width, list_input_transform=None):
    """
    Use to set line width of controller by given transform node (if don't have will detect via selection)
    """

    list_shape = []

    # prepare input list
    if list_input_transform is None:
        list_ctrl_target = cmds.ls(sl=1)
    else:
        list_ctrl_target = list_input_transform

    # filter shape
    for sel in list_ctrl_target:
        # sel shape
        if cmds.objectType(sel, isa="nurbsCurve"):
            list_shape.append(sel)

        # child shape
        list_child = cmds.listRelatives(sel, c=1, s=1, f=1)

        if list_child:
            for child in list_child:
                if cmds.objectType(child) == "nurbsCurve":
                    list_shape.append(child)

    # apply color
    if list_shape:
        for shape in list_shape:
            cmds.setAttr(shape + ".lineWidth", width)


def set_always_draw_on_top(state, list_input_transform=None):
    """
    Set alwaysDrawOnTop of controller curve shapes (transform or shape input, use selection if None)
    """

    if list_input_transform is None:
        list_input_transform = cmds.ls(sl=1)

    list_shape = []

    for sel in list_input_transform:
        if cmds.objectType(sel, isa="nurbsCurve"):
            list_shape.append(sel)
        else:
            list_shape += _curve_shapes(sel)

    if not list_shape:
        cmds.warning("Select controller(s) to set always draw on top")
        return

    for shape in list_shape:
        plug = shape + ".alwaysDrawOnTop"
        # leave locked / driven attr
        if cmds.getAttr(plug, lock=True) or cmds.listConnections(plug, s=1, d=0):
            continue
        cmds.setAttr(plug, bool(state))

    cmds.inViewMessage(
        amg="Draw On Top : {}".format("On" if state else "Off"), pos="botCenter", fade=True
    )


def get_curve_color_data(shape):
    """
    Return curve color info based on override settings.

    Returns:
        [None, None]              -> override not enabled
        [True, index]             -> using color index
        [False, (r, g, b)]        -> using RGB color
    """
    if cmds.objectType(shape) != "nurbsCurve":
        raise ValueError(f"{shape} is not a nurbsCurve")

    if not cmds.getAttr(shape + ".overrideEnabled"):
        return [None, None]

    if cmds.getAttr(shape + ".overrideRGBColors"):
        r = cmds.getAttr(shape + ".overrideColorR")
        g = cmds.getAttr(shape + ".overrideColorG")
        b = cmds.getAttr(shape + ".overrideColorB")
        return [False, (r, g, b)]
    else:
        index = cmds.getAttr(shape + ".overrideColor")
        return [True, index]


def match_controller_cv():
    selection = cmds.ls(sl=1)

    ref = selection[-1]
    sources = selection[0 : len(selection) - 1]

    for source in sources:
        Transform.match_cvs(source, ref)


def _curve_shapes(node):
    """Non-intermediate nurbsCurve shapes of node (full paths), in hierarchy order."""
    return [
        shape
        for shape in cmds.listRelatives(node, c=1, s=1, typ="nurbsCurve", f=1) or []
        if not cmds.getAttr(shape + ".intermediateObject")
    ]


def _incoming_shape_connections(shape):
    """[(source_plug, attr)] driving shape, minus history (".create") and set membership.

    AdvancedSkeleton drives control-shape visibility through these (".v",
    and ".drawOverride.overrideVisibility" on face controls -- the latter is
    what AS's own asSwapCurve loses, see its TODO).
    """
    connections = []
    pairs = cmds.listConnections(shape, s=1, d=0, p=1, c=1) or []
    for dst_plug, src_plug in zip(pairs[::2], pairs[1::2]):
        attr = dst_plug.split(".", 1)[1]
        if attr == "create" or cmds.objectType(_node_only(src_plug), isa="objectSet"):
            continue
        connections.append((src_plug, attr))
    return connections


def clone_shape(
    list_input_transform=None,
    line_width=None,
    color_data=None,
    match_bounding_box=False,
):
    """
    Input list = [target1,target2,...,ctrl_ref]

    if line width or color index not have input will use it's ctrl_target color (not clone style)

    color_data = [bool,color_value] , [is_index,color_value]

    AdvancedSkeleton compatible: new shapes are named "<ctrl>Shape" (+N),
    join every set the old shapes were in (AllSet / FaceAllSet / ...), and
    get the old shape's incoming connections (visibility drivers) back.
    """

    if list_input_transform is None:
        list_input_transform = cmds.ls(sl=1, typ="transform", l=1)

    if len(list_input_transform) < 2:
        cmds.warning("Select target control(s), then the reference control last.")
        return

    # sort shape
    ctrl_ref = list_input_transform[-1]
    list_ctrl_target = list_input_transform[0 : len(list_input_transform) - 1]

    # check is ref control have shape
    if not _curve_shapes(ctrl_ref):
        cmds.warning("Reference '{}' has no curve shape.".format(ctrl_ref))
        return

    # apply for each ctrl_target
    for ctrl_target in list_ctrl_target:
        old_shapes = _curve_shapes(ctrl_target)

        # style: given value, else this target's own first shape
        target_width = line_width
        target_color = color_data
        if old_shapes:
            if target_width is None:
                target_width = cmds.getAttr(old_shapes[0] + ".lineWidth")
            if target_color is None:
                target_color = get_curve_color_data(old_shapes[0])
        else:
            if target_width is None:
                target_width = 1
            if target_color is None:
                target_color = [None, None]

        # keep target's own draw on top (None = no old shape, keep ref value)
        target_draw_on_top = cmds.getAttr(old_shapes[0] + ".alwaysDrawOnTop") if old_shapes else None

        # what AS needs preserved
        connections = _incoming_shape_connections(old_shapes[0]) if old_shapes else []
        member_sets = []
        for shape in old_shapes:
            for object_set in cmds.listSets(object=shape) or []:
                if object_set not in member_sets:
                    member_sets.append(object_set)

        target_bb_size = None
        if match_bounding_box and old_shapes:
            target_bb_size = Transform.get_bounding_box_max(old_shapes)

        # clear old shapes
        if old_shapes:
            cmds.delete(old_shapes)

        # duplicate shape and transfer shape to target
        dup_transform = cmds.duplicate(ctrl_ref, rc=1)[0]
        dup_shapes = _curve_shapes(dup_transform)

        if target_bb_size:
            dup_bb_size = Transform.get_bounding_box_max(dup_shapes)
            if dup_bb_size:
                scale_size = target_bb_size / dup_bb_size
                cmds.xform(
                    dup_transform, scale=(scale_size, scale_size, scale_size), ws=1, r=1
                )
                cmds.makeIdentity(dup_transform, a=1, s=1)

        for shape in dup_shapes:
            cmds.parent(shape, ctrl_target, r=1, s=1)

        cmds.delete(dup_transform)

        # rename shape to proper name ("<ctrl>Shape" like AdvancedSkeleton)
        set_proper_shape_name(ctrl_target)
        new_shapes = _curve_shapes(ctrl_target)

        set_color(color_data=target_color, list_input_transform=new_shapes)
        set_line_width(list_input_transform=new_shapes, width=target_width)

        if target_draw_on_top is not None:
            for shape in new_shapes:
                cmds.setAttr(shape + ".alwaysDrawOnTop", target_draw_on_top)

        for shape in new_shapes:
            for src_plug, attr in connections:
                try:
                    cmds.connectAttr(src_plug, "{}.{}".format(shape, attr), f=1)
                except RuntimeError as error:
                    cmds.warning("Reconnect failed {} -> {}.{}: {}".format(src_plug, shape, attr, error))
            for object_set in member_sets:
                cmds.sets(shape, add=object_set)

    cmds.select(list_input_transform, r=1)

    cmds.inViewMessage(amg="Clone Shape Complete", pos="botCenter", fade=True)


def mirror_shape(source_side, target_side):
    """Mirror shape from detect side"""

    def mirror_nurbs_curve_cvs(source_curve, target_curve):
        # Validate curve types
        if not all(
            cmds.objectType(shape) == "nurbsCurve"
            for shape in [source_curve, target_curve]
        ):
            raise ValueError("Both source and target must be of type nurbsCurve")

        # Get shape nodes if transform nodes are passed
        def get_shape_node(curve):
            if cmds.objectType(curve) == "transform":
                shapes = cmds.listRelatives(curve, shapes=True, fullPath=True) or []
                for s in shapes:
                    if cmds.objectType(s) == "nurbsCurve":
                        return s
                raise ValueError(f"No nurbsCurve shape found under {curve}")
            return curve

        source_shape = get_shape_node(source_curve)
        target_shape = get_shape_node(target_curve)

        # Get number of CVs
        source_cvs = cmds.getAttr(source_shape + ".cp", size=True)
        target_cvs = cmds.getAttr(target_shape + ".cp", size=True)

        if source_cvs != target_cvs:
            raise ValueError(
                "Source and target curves do not have the same number of CVs"
            )

        # Snap and mirror CVs
        for i in range(source_cvs):
            pos = cmds.xform(
                f"{source_shape}.cv[{i}]", query=True, worldSpace=True, translation=True
            )
            mirrored_pos = [-pos[0], pos[1], pos[2]]
            cmds.xform(
                f"{target_shape}.cv[{i}]", worldSpace=True, translation=mirrored_pos
            )

    def replace_name_part(original_string, new_character, position):
        if position not in ["start", "end"]:
            return "Error: Position must be 'start' or 'end'."

        if position == "start":
            return new_character + original_string[1:]

        elif position == "end":
            return original_string[:-1] + new_character

    if cmds.ls(sl=True):
        mirror_selected = True
    else:
        mirror_selected = False

    # get raw side
    source_side_raw = source_side.replace("*", "")
    target_side_raw = target_side.replace("*", "")

    if source_side.startswith("*") and source_side.endswith("*"):
        replace_typ = "in"
    elif source_side.startswith("*"):
        replace_typ = "end"
    elif source_side.endswith("*"):
        replace_typ = "start"
    else:
        replace_typ = "in"

    # get all controller in scene — use plain cmds, work with string names directly
    list_controller_name = [
        _short_name(ctrl)
        for ctrl in cmds.ls(sl=1, typ="transform") or []
        if cmds.listRelatives(ctrl, c=1, s=1, typ="nurbsCurve")
    ]

    # force exclude advance box control
    list_exclude = [
        # Left (L)
        "EyeRegion_L",
        "ctrlCheek_L",
        "ctrlMouthCorner_L",
        "ctrlEye_L",
        "ctrlNose_L",
        "EyeBrowRegion_L",
        "ctrlBrow_L",
        "ctrlBoxMouthCorner_L",
        "ctrlBoxNose_L",
        "ctrlBoxCheek_L",
        "ctrlBoxEye_L",
        "ctrlBoxBrow_L",
        # Middle/Center (M)
        "ctrlLips_M",
        "ctrlEmotions_M",
        "ctrlMouth_M",
        "ctrlPhonemes_M",
        "NoseRegion_M",
        "LipRegion_M",
        "ctrlBoxMouth_M",
        "ctrlBoxLips_M",
        "ctrlBoxPhonemes_M",
        "ctrlBoxEmotions_M",
        # Right (R) - Transformed from Left (L)
        "EyeRegion_R",
        "ctrlCheek_R",
        "ctrlMouthCorner_R",
        "ctrlEye_R",
        "ctrlNose_R",
        "EyeBrowRegion_R",
        "ctrlBrow_R",
        "ctrlBoxMouthCorner_R",
        "ctrlBoxNose_R",
        "ctrlBoxCheek_R",
        "ctrlBoxEye_R",
        "ctrlBoxBrow_R",
    ]

    list_controller_name = [n for n in list_controller_name if n not in list_exclude]

    # Create Dict Mirror
    dict_mirror = {}

    for control_name in list_controller_name:
        if source_side_raw in control_name and replace_typ == "in":
            dict_mirror[control_name] = control_name.replace(
                source_side_raw, target_side_raw
            )
        elif control_name.startswith(source_side_raw) and replace_typ == "start":
            dict_mirror[control_name] = replace_name_part(
                control_name, target_side_raw, position="start"
            )
        elif control_name.endswith(source_side_raw) and replace_typ == "end":
            dict_mirror[control_name] = replace_name_part(
                control_name, target_side_raw, position="end"
            )

    for source_ctrl, target_ctrl in dict_mirror.items():
        print("- {} > {}".format(source_ctrl, target_ctrl))

    # clone shape and snap  control vertex position
    for source_ctrl, target_ctrl in dict_mirror.items():
        list_shape_source = cmds.listRelatives(source_ctrl, c=1, s=1, typ="nurbsCurve")

        # skip if source control have no shape
        if list_shape_source is None:
            continue
        # match shape in mirror position
        else:
            Transform.match_cvs(target_ctrl, source_ctrl)

            list_shape_target = cmds.listRelatives(
                target_ctrl, c=1, s=1, typ="nurbsCurve"
            )

            # mirror shape of target side
            for i in range(len(list_shape_source)):
                mirror_nurbs_curve_cvs(list_shape_source[i], list_shape_target[i])

    if mirror_selected:
        cmds.inViewMessage(
            amg="Mirror Selected : {} control.".format(len(dict_mirror)),
            pos="botCenter",
            fade=True,
        )
    else:
        cmds.inViewMessage(
            amg="Mirror All : {} control.".format(len(dict_mirror)),
            pos="botCenter",
            fade=True,
        )


def backup_recall(backup_name="backup_control"):
    """Recall backup control"""

    selection = cmds.ls(sl=1)

    list_child_backup = None
    if cmds.objExists(backup_name):
        list_child_backup = cmds.listRelatives(backup_name, c=1)

    if list_child_backup:
        for ctrl_backup in list_child_backup:
            ctrl_target = ctrl_backup.replace("ctrlBck_", "")

            if cmds.objExists(ctrl_target):
                # clear shape in control target
                list_clear_shape = cmds.listRelatives(ctrl_target, c=1, s=1, f=1)

                if list_clear_shape:
                    for shape in list_clear_shape:
                        cmds.delete(shape)

                # duplicate control backup and parent shape to control target
                ctrl_tmp = cmds.duplicate(ctrl_backup)
                ctrl_tmp_shape = cmds.listRelatives(ctrl_tmp, c=1, s=1, f=1)
                if ctrl_tmp_shape:
                    for shape in ctrl_tmp_shape:
                        cmds.parent(shape, ctrl_target, s=1, r=1)
                    cmds.delete(ctrl_tmp)

                # rename proper
                list_shape = cmds.listRelatives(
                    ctrl_target, c=1, s=1, typ="nurbsCurve", f=1
                )
                for i, shape in enumerate(list_shape):
                    cmds.rename(shape, "{}Shape".format(_short_name(ctrl_target)))

    # re-selection
    cmds.select(selection)


def backup_delete():
    """Delete backup control group"""

    try:
        cmds.delete("backup_control")
    except:
        pass


def backup_update(backup_name="backup_control", keyword=["ctl", "ctrl"]):
    """Create backup controller groups"""

    def is_mgear_guide(ctl):
        if cmds.attributeQuery("isGearGuide", node=ctl, exists=True):
            if cmds.getAttr("{}.isGearGuide".format(ctl)):
                return True

        return False

    selection = cmds.ls(sl=1)

    if not selection:
        raise Exception("Must be selection")

    # create backup group if not exist
    if not cmds.objExists(backup_name):
        cmds.group(em=1, n=backup_name)
        cmds.setAttr(backup_name + ".v", 0)

    # auto search for control
    list_anim_ctrl = []

    # ignore some crucial child
    for ctl in selection:
        if (
            not is_mgear_guide(ctl)
            and not Utility.is_child_of(ctl, "GRP_SHAPE")
            and not Utility.is_child_of(ctl, "controllers_org")
            and not Utility.is_child_of(ctl, backup_name)
            and not Utility.is_child_of(ctl, "guide")
            and cmds.listRelatives(ctl, c=1, s=1, typ="nurbsCurve")
        ):
            list_anim_ctrl.append(str(ctl))

    # create backup control
    for ctl in list_anim_ctrl:
        ctl_short = _short_name(ctl)

        if cmds.objExists("ctrlBck_" + ctl_short):
            cmds.delete("ctrlBck_" + ctl_short)

        ctl_bck = cmds.group(em=1, n="ctrlBck_" + ctl_short)
        cmds.parent(ctl_bck, backup_name)

        # duplicate control and parent new shape then delete it
        ctl_dup = cmds.duplicate(ctl)

        cmds.parent(
            cmds.listRelatives(ctl_dup, c=1, s=1, typ="nurbsCurve"), ctl_bck, s=1, r=1
        )
        cmds.delete(ctl_dup)

        set_proper_shape_name(ctl_bck)

    # re-selection
    cmds.select(selection)


def set_proper_shape_name(control):
    """Set shape in given transform node name to proper name"""

    list_shape = cmds.listRelatives(control, c=1, s=1, typ="nurbsCurve", f=1)

    if not list_shape:
        return

    # rename proper
    for i, shape in enumerate(list_shape):
        cmds.rename(shape, "{}Shape".format(_short_name(str(control))))


def _swap_side(name, left_to_right):
    """FKArm_L -> FKArm_R (first occurrence only, like MEL `substitute`)."""
    source, target = ("_L", "_R") if left_to_right else ("_R", "_L")
    return name.replace(source, target, 1)


def _mirror_shapes(node):
    """Non-intermediate nurbsCurve / nurbsSurface shapes of node, in hierarchy order."""
    return [
        shape
        for shape in cmds.listRelatives(node, s=1, f=1) or []
        if cmds.objectType(shape) in ("nurbsCurve", "nurbsSurface")
        and not cmds.getAttr(shape + ".intermediateObject")
    ]


def _mirror_topology(shapes):
    """Per shape: (type, spans, degree, form) -- equal lists mean CVs pair up 1:1."""
    topology = []
    for shape in shapes:
        if cmds.objectType(shape) == "nurbsCurve":
            topology.append(
                (
                    "nurbsCurve",
                    cmds.getAttr(shape + ".spans"),
                    cmds.getAttr(shape + ".degree"),
                    cmds.getAttr(shape + ".form"),
                )
            )
        else:
            topology.append((cmds.objectType(shape), None, None, None))
    return topology


def _mirror_cvs(source_cvs, target_cvs):
    """target CV i = source CV i mirrored across world X (AS: xform -ws -t -x y z)."""
    positions = cmds.xform(source_cvs, q=1, ws=1, t=1)
    for i, cv in enumerate(target_cvs[: len(source_cvs)]):
        x, y, z = positions[i * 3 : i * 3 + 3]
        cmds.xform(cv, ws=1, t=(-x, y, z))


def _mirror_skin_cage_curve(ctrl, opposite_ctrl, shape, opposite_shape, left_to_right):
    """SkinCageCurvesSet: AS's own CV remap + slide joints, ported 1:1."""
    pos = cmds.xform(ctrl, q=True, ws=True, t=True)
    sca = cmds.getAttr(ctrl + ".s")[0]
    cmds.xform(opposite_ctrl, ws=True, t=[-pos[0], pos[1], pos[2]])
    cmds.setAttr(opposite_ctrl + ".s", sca[0], sca[1], sca[2], type="float3")

    remap = {0: 2, 1: 3, 2: 0, 3: 1, 4: 2}
    for y in range(len(cmds.ls(shape + ".cv[*]", fl=1))):
        pos = cmds.xform(f"{shape}.cv[{y}]", q=True, ws=True, t=True)
        z = remap.get(y, y)
        cmds.xform(f"{opposite_shape}.cv[{z}]", ws=True, t=[-pos[0], pos[1], pos[2]])
        if y == 2:
            cmds.xform(f"{opposite_shape}.cv[4]", ws=True, t=[-pos[0], pos[1], pos[2]])

    skin_info = mel.eval(f'asSkinCurveSliderInfo "{ctrl}"')
    have_slider = [cmds.objExists(f"{skin_info[0]}_{skin_info[1]}Slider{y}") for y in range(4)]

    if any(have_slider):
        cmds.select(opposite_ctrl, r=True)
        mel.eval("asCreateSliders")

        slider_remap = {0: 2, 1: 3, 2: 0, 3: 1}
        for y in range(4):
            slider = f"{skin_info[0]}_{skin_info[1]}Slider{y}"
            opposite_slider = _swap_side(slider, left_to_right)
            opposite_slider = opposite_slider.replace(str(y), str(slider_remap[y]), 1)
            if cmds.objExists(slider) and cmds.objExists(opposite_slider):
                cmds.setAttr(opposite_slider + ".slide", cmds.getAttr(slider + ".slide"))
    else:
        opposite_info = mel.eval(f'asSkinCurveSliderInfo "{opposite_ctrl}"')
        if any(cmds.objExists(f"{opposite_info[0]}_{opposite_info[1]}Slider{i}") for i in range(4)):
            cmds.select(opposite_ctrl, r=True)
            mel.eval("asDeleteSliders")


def _as_mirror_control_set(left_to_right, set_name):
    if not cmds.objExists(set_name):
        return 0

    side = "_L" if left_to_right else "_R"
    mirrored = 0

    for ctrl in cmds.sets(set_name, q=True) or []:
        short = _short_name(ctrl)
        if side not in short:
            continue

        # AS: never mirror the face joystick ctrls (ctrlBox side panels)
        if set_name == "FaceControlSet" and short.split(":")[-1].startswith("ctrl"):
            continue

        opposite_ctrl = _swap_side(ctrl, left_to_right)
        if not cmds.objExists(opposite_ctrl):
            continue

        shapes = _mirror_shapes(ctrl)
        opposite_shapes = _mirror_shapes(opposite_ctrl)
        if not shapes or not opposite_shapes:
            continue

        if set_name == "SkinCageCurvesSet":
            _mirror_skin_cage_curve(ctrl, opposite_ctrl, shapes[0], opposite_shapes[0], left_to_right)
            mirrored += 1
            continue

        # One side swapped to another / multi-shape curve: copy the shapes over
        # first -- clone_shape keeps the opposite's color, sets and AS connections.
        source_topology = _mirror_topology(shapes)
        if source_topology != _mirror_topology(opposite_shapes):
            if all(t[0] == "nurbsCurve" for t in source_topology):
                clone_shape([opposite_ctrl, ctrl])
                opposite_shapes = _mirror_shapes(opposite_ctrl)
            else:
                cmds.warning("Mirror skipped, shapes differ: {} -> {}".format(ctrl, opposite_ctrl))
                continue

        for shape, opposite_shape in zip(shapes, opposite_shapes):
            if cmds.objectType(shape) == "nurbsSurface":
                _mirror_cvs(cmds.ls(shape + ".cv[*][*]", fl=1), cmds.ls(opposite_shape + ".cv[*][*]", fl=1))
                # AS: softMod / cluster surfaces get their direction reversed
                if cmds.attributeQuery("softModControl", node=ctrl, exists=True) or cmds.attributeQuery(
                    "clusterControl", node=ctrl, exists=True
                ):
                    cmds.reverseSurface(opposite_shape, d=0, ch=0, rpo=True)
            else:
                _mirror_cvs(cmds.ls(shape + ".cv[*]", fl=1), cmds.ls(opposite_shape + ".cv[*]", fl=1))
        mirrored += 1

    return mirrored


def as_mirror_control_curves(left_to_right, setName="ControlSet"):
    """Mirror control curves L->R (or R->L) for a whole AdvancedSkeleton set.

    Same rules as AS's asMirrorControlCurves (its Left>Right / Right>Left
    buttons): build pose required, world-X mirror of every CV, face joystick
    "ctrl*" skipped, SkinCageCurvesSet remap + slide joints, and -- like AS --
    mirroring "ControlSet" also mirrors "FaceControlSet" (facial controls).
    Beyond AS: every shape of a multi-shape control is mirrored (AS only does
    the first), and a side whose shapes differ gets them copied first.
    """
    # confirm build pose
    if mel.eval('exists "asConfirmIfNotInBuildPose"') and not mel.eval("asConfirmIfNotInBuildPose"):
        return

    sel = cmds.ls(sl=True) or []
    try:
        mirrored = _as_mirror_control_set(left_to_right, setName)
        if setName == "ControlSet":
            mirrored += _as_mirror_control_set(left_to_right, "FaceControlSet")
    finally:
        if sel:
            cmds.select(sel, r=True)
        else:
            cmds.select(cl=True)

    cmds.inViewMessage(
        amg="Mirror {}: {} controls".format("L > R" if left_to_right else "R > L", mirrored),
        pos="botCenter",
        fade=True,
    )


def as_swap_curve():
    sel = cmds.ls(sl=True)
    if len(sel) < 2:
        cmds.error("Selected both controls to replace, and the new curve to use")

    ctrl_from_edges = False
    sel_shapes = []

    for i, item in enumerate(sel):
        shapes = cmds.listRelatives(item, s=True, f=True) or []
        sel_shapes.append(shapes[0] if shapes else None)

        if "Extra" in item:
            continue

        if ".e[" in item:
            ctrl_from_edges = True
            break

        if not shapes or not cmds.objExists(shapes[0]):
            cmds.error(f'selected object: "{item}" is not a nurbsCurve')

        obj_type = cmds.objectType(shapes[0])
        if obj_type != "nurbsCurve" and obj_type != "nurbsSurface":
            cmds.error(f'selected object: "{item}" is not a nurbsCurve')

    if ctrl_from_edges:
        if cmds.objExists("combinedEdgesAsCurve"):
            cmds.delete("combinedEdgesAsCurve")

        ctrls = []
        cmds.select(cl=True)

        for item in sel:
            if ".e[" in item:
                cmds.select(item, add=True)
            elif cmds.objectType(item) == "transform":
                ctrls.append(item)

        if not ctrls:
            cmds.error("No Controller found in the selection")

        temp_curves = cmds.duplicateCurve(ch=False)
        cmds.delete(temp_curves, ch=True)

        if len(temp_curves) == 1:
            cmds.duplicate(temp_curves[0], n="combinedEdgesAsCurve")
        else:
            cmds.attachCurve(
                temp_curves,
                n="combinedEdgesAsCurve",
                ch=False,
                rpo=False,
                kmk=True,
                m=1,
                bb=0.5,
                bki=False,
                p=0.1,
            )

        cmds.delete(temp_curves)

        temp_xform = cmds.createNode("transform", n="tempXform", p=ctrls[0])
        cmds.parent(temp_xform, w=True)
        cmds.parent("combinedEdgesAsCurve", temp_xform)
        cmds.xform(temp_xform, os=True, t=(0, 0, 0), ro=(0, 0, 0))
        cmds.parent("combinedEdgesAsCurve", w=True)

        cmds.makeIdentity("combinedEdgesAsCurve", apply=True, t=True, r=True, s=True)
        cmds.xform("combinedEdgesAsCurve", ws=True, piv=(0, 0, 0))
        cmds.scale(1.3, 1.3, 1.3, "combinedEdgesAsCurve.cv[*]", r=True, p=(0, 0, 0))

        target_shape = "combinedEdgesAsCurveShape"
        cmds.setAttr(f"{target_shape}.overrideEnabled", 1)
        orig_shapes = cmds.listRelatives(ctrls[0], s=True)
        color = cmds.getAttr(f"{orig_shapes[0]}.overrideColor")
        cmds.setAttr(f"{target_shape}.overrideColor", color)

        cmds.delete(temp_xform)

        cmds.select(ctrls, r=True)
        cmds.select("combinedEdgesAsCurve", add=True)
        as_swap_curve()

        if cmds.objExists("combinedEdgesAsCurve"):
            cmds.delete("combinedEdgesAsCurve")
        cmds.select(ctrls)
        return

    last_item = sel[-1]
    cmds.delete(last_item, ch=True)

    for i in range(len(sel) - 1):
        target_ctrl = sel[i]
        old_shapes = cmds.listRelatives(target_ctrl, s=True, f=True) or []

        shape_was_in_allset = False
        shape_was_in_face_allset = False
        connections = []

        if old_shapes:
            shape = old_shapes[0]
            if cmds.objExists("AllSet"):
                shape_was_in_allset = cmds.sets(shape, im="AllSet")
            if cmds.objExists("FaceAllSet"):
                shape_was_in_face_allset = cmds.sets(shape, im="FaceAllSet")

            connections = cmds.listConnections(shape, s=True, d=False, p=True) or []
            cmds.delete(old_shapes)

        temp_grp = cmds.duplicate(last_item, n="tempXform")[0]
        new_shapes = cmds.listRelatives(temp_grp, s=True, f=True) or []

        all_set_name = "AllSet"
        if cmds.objExists("FaceAllSet"):
            if cmds.sets(target_ctrl, im="FaceAllSet"):
                all_set_name = "FaceAllSet"

        for shape in new_shapes:
            new_shape_name = cmds.rename(shape, f"{target_ctrl}Shape")
            added_shape = cmds.parent(new_shape_name, target_ctrl, add=True, s=True)[0]

            rot = cmds.xform(target_ctrl, q=True, ws=True, ro=True)
            if any(abs(v) > 0.001 for v in rot):
                if not cmds.objExists("combinedEdgesAsCurve"):
                    cmds.rotate(-90, -90, 0, f"{added_shape}.cv[*]", r=True, os=True)

            if shape_was_in_allset or shape_was_in_face_allset:
                cmds.sets(added_shape, add=all_set_name)

            if connections:
                try:
                    cmds.connectAttr(connections[0], f"{added_shape}.v", f=True)
                except:
                    pass

        cmds.delete(temp_grp)

    cmds.dgdirty(a=True)