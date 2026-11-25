from tmlib.core import Scene, Utility, File, SkinWeight, Controller, Transform,Selection
import os, json, tempfile
import maya.cmds as cmds
import maya.api.OpenMaya as om
import importlib.util
import tmlib

try:
    import ngSkinTools2
    from ngSkinTools2.api import import_export
    from ngSkinTools2.operations import removeLayerData
    from ngSkinTools2.api import transfer
    NGSKINTOOLS_AVAILABLE = True
except ImportError:
    NGSKINTOOLS_AVAILABLE = False


def create_quick_data_folder_template():
    """Make Sure the quick data path is exist, Create from current openning file."""
    current_file_path = cmds.file(q=True, sceneName=True)

    if not current_file_path:
        cmds.confirmDialog(m="Please save this file before create quick data.")
        return False

    dir_path = os.path.dirname(current_file_path)

    # Define the subfolder structure
    subfolders = [
        "QuickData/Python",
        "QuickData/Skin",
        "QuickData/Controller",
        "QuickData/SkinTransfer",
        "QuickData/SkinNG",
    ]

    # Create folders
    for folder in subfolders:
        full_path = os.path.join(dir_path, folder)
        os.makedirs(full_path, exist_ok=True)


def get_quick_data_dir():
    current_file_path = cmds.file(q=True, sceneName=True)

    # if file not save yet
    if not current_file_path:
        return False

    dir_path = os.path.dirname(current_file_path)
    quick_data_path = os.path.join(dir_path, "QuickData")

    # if dir exist
    if os.path.exists(quick_data_path):
        return quick_data_path

    # if dir not exist
    else:
        return False


def require_quick_data_dir():
    """Return quick data path, or warn and return None if file not saved / folder not created."""
    quick_data_path = get_quick_data_dir()

    if not quick_data_path:
        cmds.warning(
            "Quick Data folder not found. Save the file and press Create first."
        )
        return None

    return quick_data_path


def backup_controller_and_skin():
    """Backup both controller and skin data (Dont have to select mesh to backup skin)"""

    export_shape_quick()

    # select skin cluster node
    cmds.select(cmds.ls(typ="transform"))
    export_skin_quick()


def apply_controller_and_skin():
    """Apply both controller and skin data (Dont have to select mesh to apply skin)"""

    import_shape_quick()

    # select skin cluster node
    cmds.select(cmds.ls(typ="transform"))
    import_skin_quick()


def get_missing_joint_by_json_data(skin_dict, transfer_dict={}):
    """Return missing joint in scene by given json dictionary"""

    dict_weight = skin_dict["deformerWeight"]["weights"]

    list_missing_joints = []

    for weight in dict_weight:
        joint_name = weight["source"]
        if not cmds.objExists(joint_name):
            if joint_name in transfer_dict.keys():
                if not cmds.objExists(transfer_dict[joint_name]):
                    list_missing_joints.append(joint_name)

            else:
                list_missing_joints.append(joint_name)

    return list_missing_joints


def normalize_dict(data):
    return {k: v for k, v in data.items() if v != ""}


def get_bind_joints_by_json_data(skin_dict):
    """Return bind joint list by given json dictionary"""

    dict_weight = skin_dict["deformerWeight"]["weights"]

    list_bind_joints = []

    for weight in dict_weight:
        joint_name = weight["source"]
        list_bind_joints.append(joint_name)

    return list_bind_joints


# def create_joint_transfer(joint_main_name,joint_transfer_name):
#     dict_rename_to_restore = {}
#     dict_rename_to_transfer = {}

#     joint = cmds.createNode("joint", n=joint_transfer_name)
#     dict_rename_to_transfer[name] = dict_transfer[name]
#     cmds.rename(name,dict_transfer)

#     return joint,

def import_skin_quick(enable_transfer=False):
    grp_missing_joint = "missing_joint_grp"
    quick_data_path = require_quick_data_dir()

    if not quick_data_path:
        return

    quick_data_skin_path = os.path.join(quick_data_path, "Skin")
    quick_data_skin_transfer_path = os.path.join(quick_data_path, "SkinTransfer")

    selection = cmds.ls(sl=True, long=True)

    if not selection:
        cmds.warning("Selection required before import")
        return

    list_not_found = []

    for sel in selection:
        sel_name_cutted = Utility.cut(sel, hierarchy=True, namespace=True)

        json_file = os.path.join(quick_data_skin_path, "{}.json".format(sel_name_cutted))
        json_transfer_file = os.path.join(quick_data_skin_transfer_path, "{}.json".format(sel_name_cutted))

        if not cmds.objExists(sel):
            list_not_found.append(sel)
            continue

        if not os.path.exists(json_file):
            list_not_found.append(sel)
            continue

        # if shape selected, get transform parent
        if cmds.objectType(sel, isAType="shape"):
            sel = cmds.listRelatives(sel, parent=True, fullPath=True)[0]

        dict_data = File.load_json_file_to_dict(json_file)

        if not dict_data:
            list_not_found.append(sel)
            continue

        if enable_transfer and os.path.exists(json_transfer_file):
            dict_transfer = File.load_json_file_to_dict(json_transfer_file) or {}
        else:
            dict_transfer = {}

        dict_transfer = normalize_dict(dict_transfer)

        list_bind_joints = get_bind_joints_by_json_data(dict_data)

        # delete old skin cluster
        old_skin_cluster = SkinWeight.get_skin_cluster_node(sel)
        if old_skin_cluster:
            cmds.delete(old_skin_cluster)

        # transfer : temporary rename new joint to old name stored in file
        list_rename_restore = []
        for joint in list_bind_joints:
            if cmds.objExists(joint) or joint not in dict_transfer:
                continue

            joint_transfer = dict_transfer[joint]
            if not cmds.objExists(joint_transfer) or joint_transfer in list_bind_joints:
                continue

            renamed = cmds.rename(joint_transfer, joint)
            list_rename_restore.append((renamed, Utility.cut(joint_transfer, hierarchy=True)))

        # check missing joints and create placeholders
        for joint in list_bind_joints:
            if not cmds.objExists(joint):
                if not cmds.objExists(grp_missing_joint):
                    cmds.group(name=grp_missing_joint, empty=True)
                joint = cmds.createNode("joint", name=joint)
                cmds.parent(joint, grp_missing_joint)

        try:
            # create new skin cluster
            node_skin_cluster = cmds.skinCluster(
                sel,
                list_bind_joints,
                name=dict_data["deformerWeight"]["weights"][0]["deformer"],
                toSelectedBones=True,
                ignoreHierarchy=True,
                bindMethod=0,
            )[0]

            # import weights
            cmds.deformerWeights(
                os.path.basename(json_file),
                im=True,
                method="index",
                deformer=node_skin_cluster,
                path=os.path.dirname(json_file),
            )

        finally:
            # restore transfer joint name
            for renamed, original_name in list_rename_restore:
                cmds.rename(renamed, original_name)

        cmds.select(sel)
        cmds.skinPercent(node_skin_cluster, normalize=True)

    cmds.select(selection)

    cmds.inViewMessage(
        amg="<hl>Skin Apply!</hl>", pos="botCenter", fit=20, fts=16, fade=True
    )


def export_skin_quick():
    """
    Use for export selected skin cluster
    """

    quick_data_path = require_quick_data_dir()

    if not quick_data_path:
        return

    list_skin_cluster = []
    list_mesh_name = []

    selection = cmds.ls(sl=True, type="transform", long=True)

    if not selection:
        cmds.warning("Selection required before export")
        return

    for sel in selection:
        if (
            cmds.listRelatives(sel, children=True, type="mesh")
            or cmds.listRelatives(sel, children=True, type="nurbsSurface")
            or cmds.listRelatives(sel, children=True, type="nurbsCurve")
        ):
            skin_cluster_node = SkinWeight.get_skin_cluster_node(mesh_node=sel)

            if skin_cluster_node:
                list_skin_cluster.append(skin_cluster_node)
                list_mesh_name.append(Utility.cut(sel, hierarchy=True, namespace=True))

    if not list_skin_cluster:
        cmds.warning("Skin cluster node not found on selection")
        return

    # export maya skin weight .json
    file_path = os.path.normpath(os.path.join(quick_data_path, "Skin"))
    os.makedirs(file_path, exist_ok=True)

    for skin_cluster_node, mesh_name in zip(list_skin_cluster, list_mesh_name):

        save_name = "{}.json".format(mesh_name)

        cmds.deformerWeights(
            save_name,
            export=True,
            deformer=skin_cluster_node,
            format="JSON",
            path=file_path,
        )

    cmds.select(selection)

    print("Exported Skin Weight Complete!")

    cmds.inViewMessage(
        amg="<hl>Write Skin Weight!</hl>", pos="botCenter", fit=20, fts=16, fade=True
    )


def require_ngskintools():
    """Return True if ngSkinTools2 python module and plugin are ready"""
    if not NGSKINTOOLS_AVAILABLE:
        cmds.warning("ngSkinTools2 not installed.")
        return False

    if not cmds.pluginInfo("ngSkinTools2", query=True, loaded=True):
        try:
            cmds.loadPlugin("ngSkinTools2", quiet=True)
        except RuntimeError:
            cmds.warning("Cannot load ngSkinTools2 plugin.")
            return False

    return True


def get_selected_skinned_mesh():
    """Return list of (mesh transform, file name) of selected mesh that have skin cluster"""
    list_return = []

    for sel in cmds.ls(sl=True, type="transform", long=True):
        if not cmds.listRelatives(sel, children=True, type="mesh"):
            continue

        if not SkinWeight.get_skin_cluster_node(mesh_node=sel):
            cmds.warning("Skin cluster node not found on : {}".format(sel))
            continue

        list_return.append((sel, Utility.cut(sel, hierarchy=True, namespace=True)))

    return list_return


def export_ng_quick():
    """
    Export ngSkinTools2 layers of selected mesh to QuickData/SkinNG,
    if mesh don't have ng layers yet, will init layers from current skin weight
    """

    quick_data_path = require_quick_data_dir()

    if not quick_data_path or not require_ngskintools():
        return

    selection = cmds.ls(sl=True, long=True)
    list_mesh = get_selected_skinned_mesh()

    if not list_mesh:
        cmds.warning("Select skinned mesh before export ng")
        return

    from ngSkinTools2.api import init_layers

    ng_file_path = os.path.normpath(os.path.join(quick_data_path, "SkinNG"))
    os.makedirs(ng_file_path, exist_ok=True)

    for mesh, mesh_name in list_mesh:
        # force init ng layers (first layer take current skin weight)
        layers = init_layers(mesh)
        if not layers.list():
            layers.add("base")

        json_ng_file = os.path.join(ng_file_path, "{}.json".format(mesh_name))
        import_export.export_json(mesh, file=json_ng_file)

        # store skin cluster name, so import can rebind with the same name
        skin_cluster = SkinWeight.get_skin_cluster_node(mesh)
        if skin_cluster:
            with open(json_ng_file, "r") as f:
                json_ng_data = json.load(f)

            json_ng_data["skinCluster"] = Utility.cut(skin_cluster, hierarchy=True, namespace=True)

            with open(json_ng_file, "w") as f:
                json.dump(json_ng_data, f)

    cmds.select(selection)

    cmds.inViewMessage(
        amg="<hl>Write NG Skin!</hl>", pos="botCenter", fit=20, fts=16, fade=True
    )


def resolve_ng_influence(influence_path):
    """
    Find scene node of influence path stored in ng json file
    order : full path > short name > same name in any namespace
    """
    short_name = Utility.cut(influence_path, hierarchy=True)
    base_name = Utility.cut(short_name, namespace=True)

    if cmds.objExists(influence_path) and len(cmds.ls(influence_path)) == 1:
        return cmds.ls(influence_path, long=True)[0]

    for pattern in [short_name, base_name, "*:{}".format(base_name)]:
        list_found = cmds.ls(pattern, type="transform", long=True) or []

        if list_found:
            if len(list_found) > 1:
                cmds.warning("Found multiple '{}', use : {}".format(pattern, list_found[0]))
            return list_found[0]

    return None


def import_ng_quick():
    """
    Import ngSkinTools2 layers from QuickData/SkinNG to selected mesh,
    old skin cluster will be deleted and rebind to influences stored in ng file
    """
    grp_missing_joint = "missing_joint_grp"
    quick_data_path = require_quick_data_dir()

    if not quick_data_path or not require_ngskintools():
        return

    selection = cmds.ls(sl=True, long=True)
    list_mesh = [
        (sel, Utility.cut(sel, hierarchy=True, namespace=True))
        for sel in cmds.ls(sl=True, type="transform", long=True)
        if cmds.listRelatives(sel, children=True, type="mesh")
    ]

    if not list_mesh:
        cmds.warning("Select mesh before import ng")
        return

    ng_file_path = os.path.join(quick_data_path, "SkinNG")
    list_not_found = []
    list_missing_influence = []

    for mesh, mesh_name in list_mesh:
        json_ng_file = os.path.join(ng_file_path, "{}.json".format(mesh_name))

        json_ng_data = File.load_json_file_to_dict(json_ng_file) if os.path.exists(json_ng_file) else None
        list_layers = (json_ng_data or {}).get("layers") or []

        if not list_layers:
            list_not_found.append(mesh_name)
            continue

        # vertPositions is flat list [x, y, z, x, y, z, ...]
        vertex_count_ng = len(json_ng_data.get("mesh", {}).get("vertPositions", [])) // 3
        mesh_shape = cmds.listRelatives(mesh, shapes=True, noIntermediate=True, fullPath=True, type="mesh")[0]
        vertex_count_mesh = cmds.polyEvaluate(mesh_shape, v=True)

        if vertex_count_mesh != vertex_count_ng:
            result = cmds.confirmDialog(
                title="Confirm",
                message="{} is have diffrent vertex count , what method do you prefer?".format(mesh_name),
                button=["Index", "Distance", "Skip"],
                defaultButton="Distance",
                cancelButton="Skip",
                dismissString="Skip",
            )
        else:
            result = "Index"

        if result == "Index":
            vertex_transfer_mode = transfer.VertexTransferMode.vertexId
        elif result == "Distance":
            vertex_transfer_mode = transfer.VertexTransferMode.closestPoint
        else:
            continue

        # find scene influence of each influence in file, create placeholder if missing
        list_bind_joints = []
        for influence in json_ng_data.get("influences", []):
            joint = resolve_ng_influence(influence["path"])

            if not joint:
                joint_name = Utility.cut(influence["path"], hierarchy=True, namespace=True)
                list_missing_influence.append(joint_name)

                if not cmds.objExists(grp_missing_joint):
                    cmds.group(name=grp_missing_joint, empty=True)
                joint = cmds.createNode("joint", name=joint_name, parent=grp_missing_joint)
                joint = cmds.ls(joint, long=True)[0]

            # store scene path, so ng will map influence by exact name
            influence["path"] = joint

            if joint not in list_bind_joints:
                list_bind_joints.append(joint)

        # delete old skin cluster (with ng layer data)
        old_skin_cluster = SkinWeight.get_skin_cluster_node(mesh)

        # name priority : name stored in ng file > old skin cluster name > default
        skin_cluster_name = json_ng_data.get("skinCluster")
        if not skin_cluster_name and old_skin_cluster:
            skin_cluster_name = Utility.cut(old_skin_cluster, hierarchy=True)
        if not skin_cluster_name:
            skin_cluster_name = "{}_skinCluster".format(mesh_name)

        if old_skin_cluster:
            cmds.select(mesh)
            removeLayerData.remove_custom_nodes_from_selection()
            cmds.delete(old_skin_cluster)

        # rebind
        new_skin_cluster = cmds.skinCluster(
            mesh,
            list_bind_joints,
            name=skin_cluster_name,
            toSelectedBones=True,
            ignoreHierarchy=True,
            bindMethod=0,
        )[0]

        if new_skin_cluster != skin_cluster_name:
            cmds.warning(
                "'{}' already exists in scene, skin cluster of {} named : {}".format(
                    skin_cluster_name, mesh_name, new_skin_cluster
                )
            )

        # import from remapped copy of ng file
        remap_file = os.path.join(tempfile.gettempdir(), "quickdata_ng_{}.json".format(mesh_name))
        with open(remap_file, "w") as f:
            json.dump(json_ng_data, f)

        try:
            import_export.import_json(mesh, vertex_transfer_mode=vertex_transfer_mode, file=remap_file)
        finally:
            os.remove(remap_file)

    if list_missing_influence:
        cmds.warning(
            "Influence not found, created placeholder in '{}' : {}".format(grp_missing_joint, list_missing_influence)
        )

    if list_not_found:
        cmds.warning("NG data not found : {}".format(list_not_found))

    cmds.select([sel for sel in selection if cmds.objExists(sel)])

    cmds.inViewMessage(
        amg="<hl>NG Skin Apply!</hl>", pos="botCenter", fit=20, fts=16, fade=True
    )


def import_shape_quick():
    quick_data_path = require_quick_data_dir()

    if not quick_data_path:
        return

    key_name = get_current_file_keyword()
    read_path = os.path.join(quick_data_path, "Controller", "{}.json".format(key_name))

    # old version save file without underscore as "Name.ma.json"
    if not os.path.exists(read_path):
        current_file_name = os.path.basename(cmds.file(q=True, sceneName=True))
        legacy_path = os.path.join(quick_data_path, "Controller", "{}.json".format(current_file_name.split("_")[0]))

        if os.path.exists(legacy_path):
            read_path = legacy_path

    if os.path.exists(read_path):
        import_shape_custom(file_path=read_path)
        cmds.inViewMessage(
            amg="<hl> Controller Apply!</hl>",
            pos="botCenter",
            fit=20,
            fts=16,
            fade=True,
        )

    else:
        cmds.warning("{} not found".format(read_path))


def build_and_read():
    build_current()
    apply_controller_and_skin()


def build_current():
    selection = [str(node) for node in cmds.ls(sl=1)]

    if not cmds.objExists("guide"):
        cmds.error()
        return

    from mgear import shifter

    cmds.select(cl=1)

    if cmds.objExists("rig"):
        cmds.delete("rig")

    Help.reload_scripts()

    shifter.reloadComponents()

    from mgear.shifter import guide_manager

    guide_manager.build_from_selection()

    if cmds.objExists("guide"):
        cmds.setAttr("guide.v", False)

    cmds.select(cl=True)

    for sel in selection:
        if cmds.objExists(sel):
            cmds.select(sel, add=True)

    cmds.inViewMessage(
        amg="<hl> Build Complete!</hl>", pos="botCenter", fit=20, fts=16, fade=True
    )


def remove_rig():
    if cmds.objExists("rig"):
        cmds.delete("rig")

    if cmds.objExists("guide"):
        cmds.setAttr("guide.v", True)

    cmds.inViewMessage(
        amg="<hl> Rig Removed!</hl>", pos="botCenter", fit=20, fts=16, fade=True
    )


def remove_all_shaders_pm():
    # Get all shading engines
    shading_engines = cmds.ls(type="shadingEngine")

    # Exclude defaults
    default_sg = {"initialShadingGroup", "initialParticleSE"}
    shading_engines = [sg for sg in shading_engines if sg not in default_sg]

    for sg in shading_engines:
        # Find connected materials
        materials = []
        for attr in ["surfaceShader", "volumeShader", "displacementShader"]:
            mats = cmds.listConnections("{}.{}".format(sg, attr), s=1, d=0) or []
            materials.extend(mats)

        # Delete shading engine + connected materials
        try:
            cmds.delete(list(set(materials + [sg])))
            print("Deleted:", sg, "with:", materials)
        except:
            print("Could not delete:", sg)

    print("✅ Removed all non-default shaders (pymel).")


def cleanup_scene():
    # --- Remove Grease Pencil nodes ---
    grease_pencils = cmds.ls(type="greasePencil")
    if grease_pencils:
        cmds.delete(grease_pencils)
        print("Removed grease pencil nodes:", grease_pencils)
    else:
        print("No grease pencil nodes found.")

    grease_pencils = cmds.ls(type="greasePlane")
    if grease_pencils:
        cmds.delete(grease_pencils)
        print("Removed grease pencil nodes:", grease_pencils)
    else:
        print("No grease pencil nodes found.")

    # --- Remove Display Layers (except defaultLayer) ---
    display_layers = cmds.ls(type="displayLayer")
    for layer in display_layers:
        if layer != "defaultLayer":
            try:
                cmds.delete(layer)
                print("Removed display layer:", layer)
            except:
                print("Could not delete display layer:", layer)

    print("Scene cleanup completed!")


def reload_all_references():
    # list all references
    refs = cmds.file(query=True, reference=True)

    if not refs:
        cmds.warning("No references found in the scene.")
        return

    for ref in refs:
        try:
            # reload reference
            cmds.file(ref, loadReference=True)
            print("Reloaded reference:", ref)
        except Exception as e:
            cmds.warning("Failed to reload reference: {} | {}".format(ref, e))


def hero_ctrl():
    if not cmds.objExists("guide"):
        raise Exception("not found Guide")

    # create folder
    quick_data_path = get_quick_data_dir()

    if not quick_data_path:
        raise (Exception("Create Quick Data First"))

    hero_ctrl_path = os.path.join(quick_data_path, "Hero")
    os.makedirs(hero_ctrl_path, exist_ok=True)

    # run mgear
    build_and_read()

    if cmds.objExists("Delete_Grp"):
        cmds.delete("Delete_Grp")

    if cmds.objExists("guide"):
        cmds.delete("guide")

    cmds.rename("rig", "Rig_Grp")

    remove_all_shaders_pm()
    cleanup_scene()

    # save to new path // force overwrite
    current_name = get_current_file_keyword()
    save_name = "{}_HeroCtrl.ma".format(current_name)
    new_file_path = os.path.join(hero_ctrl_path, save_name)

    print("hero ctrl path : ", hero_ctrl_path)
    om.MGlobal.displayInfo("Save name : {}".format(save_name))
    om.MGlobal.displayInfo("Hero Ctrl to path : {}".format(new_file_path))

    # Rename the current scene to the new path
    cmds.file(rename=new_file_path)
    # Save the file with the specified type and force overwrite
    cmds.file(save=True, type="mayaAscii", force=True)

    cmds.inViewMessage(
        amg="<hl> Hero Ctrl Complete!</hl>", pos="botCenter", fit=20, fts=16, fade=True
    )


def hero_hi():
    # create folder
    quick_data_path = get_quick_data_dir()

    if not quick_data_path:
        raise (Exception("Create Quick Data First"))

    heor_hi_path = os.path.join(quick_data_path, "Hero")
    os.makedirs(heor_hi_path, exist_ok=True)

    # run mgear
    if cmds.objExists("Delete_Grp"):
        cmds.delete("Delete_Grp")

    # remove_all_shaders_pm()
    General.sort_by_type(typ="anim_curve")
    controllers = cmds.ls(sl=1)

    for ctrl in controllers:
        Transform.reset_transform(ctrl)

    Scene.clear_controller_animation()
    Scene.import_all_references()
    Scene.remove_all_namespaces()
    cleanup_scene()

    cmds.setAttr("Rig_Grp.jnt_vis", False)
    cmds.setAttr("Rig_Grp.ctl_vis_on_playback", True)

    # # save to new path // force overwrite
    # current_name = get_current_file_keyword()
    # save_name = "{}_HeroHi.ma".format(current_name)
    # new_file_path = os.path.join(heor_hi_path, save_name)

    # cmds.file(rename=new_file_path)
    # cmds.file(save=True, type="mayaAscii", force=True)

    # cmds.inViewMessage(
    #     amg="<hl> Hero Hi Complete!</hl>", pos="botCenter", fit=20, fts=16, fade=True
    # )


def open_quick_data_folder():
    quick_data_path = get_quick_data_dir()

    if os.path.exists(quick_data_path):
        os.startfile(quick_data_path)


def open_controller_folder():
    quick_data_path = get_quick_data_dir()
    path = os.path.join(quick_data_path, "Controller")

    if os.path.exists(path):
        os.startfile(path)


def open_local_rig_config_folder():
    quick_data_path = get_quick_data_dir()
    path = os.path.join(quick_data_path, "LocalRigConfig")

    os.makedirs(path, exist_ok=True)

    os.startfile(path)


def open_skin_folder():
    quick_data_path = get_quick_data_dir()
    path = os.path.join(quick_data_path, "Skin")

    if os.path.exists(path):
        os.startfile(path)


def get_current_file_keyword():
    current_file_path = cmds.file(q=True, sceneName=True)
    current_file_name = os.path.basename(current_file_path)
    current_file_name_only = os.path.splitext(current_file_name)[0]
    key_name = current_file_name_only.split("_")[0]

    return key_name


def export_shape_quick():
    quick_data_path = require_quick_data_dir()

    if not quick_data_path:
        return

    key_name = get_current_file_keyword()
    path = os.path.join(quick_data_path, "Controller", "{}.json".format(key_name))
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if not export_shape_custom(file_path=path):
        return

    cmds.inViewMessage(
        amg="<hl>Controller Backup!</hl>", pos="botCenter", fit=20, fts=16, fade=True
    )

def export_shape_advanced_skeleton_quick():
    quick_data_path = require_quick_data_dir()

    if not quick_data_path:
        return

    key_name = get_current_file_keyword()
    path = os.path.join(quick_data_path, "Controller", "{}.json".format(key_name))
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if not export_shape_custom(file_path=path):
        return

    cmds.inViewMessage(
        amg="<hl>Controller Backup!</hl>", pos="botCenter", fit=20, fts=16, fade=True
    )



def export_shape_custom(file_path=""):
    """
    Export curve shape data of one or more NURBS controllers to a JSON file.

    The exported JSON structure:
    {
        "controllerName": {
            "shapeNodeName": {
                "colorData": [
                    None, None                    -> override disabled
                    [True, colorIndex]            -> override enabled with index color
                    [False, (r, g, b)]            -> override enabled with RGB color
                ],
                "cvPositions": [[x, y, z], ...],  # World-space positions of each CV
                "lineWidth": float               # Line width of the curve
            }
        }
    }

    Args:
        controllers (str or list of str): One or more controller transform names.

    A file dialog will appear for the user to choose the save location for the JSON file.
    """

    # if selection will export selection

    controllers = Selection.sort_by_type(list_target=cmds.ls(), typ="anim_curve")
    if isinstance(controllers, str):
        controllers = [controllers]

    controllers = list(controllers or [])

    # append advance skeleton shape
    if cmds.objExists("ControlSet"):
        advance_ctrls = cmds.sets("ControlSet", q=True) or []

        for ctrl in advance_ctrls:
            if ctrl not in controllers and cmds.listRelatives(ctrl, c=1, s=1, typ="nurbsCurve"):
                controllers.append(ctrl)

    data = {}

    for ctrl_name in controllers:
        if not cmds.objExists(ctrl_name):
            cmds.warning(f"Controller '{ctrl_name}' does not exist.")
            continue

        ctrl = cmds.ls(ctrl_name)[0]
        list_shape = cmds.listRelatives(ctrl, c=1, s=1, f=1) or []

        if not list_shape:
            cmds.warning(f"'{ctrl}' has no shapes.")
            continue

        # Write Data
        for shape in list_shape:
            if cmds.getAttr(shape + ".intermediateObject"):
                continue

            if cmds.nodeType(shape) == "nurbsCurve":
                shape_data = {}

                # Color data
                if not cmds.getAttr(shape + ".overrideEnabled"):
                    shape_data["colorData"] = [None, None]
                else:
                    if cmds.getAttr(shape + ".overrideRGBColors"):
                        rgb = (
                            round(cmds.getAttr(shape + ".overrideColorR"), 3),
                            round(cmds.getAttr(shape + ".overrideColorG"), 3),
                            round(cmds.getAttr(shape + ".overrideColorB"), 3),
                        )
                        shape_data["colorData"] = [False, rgb]
                    else:
                        shape_data["colorData"] = [
                            True,
                            cmds.getAttr(shape + ".overrideColor"),
                        ]

                # CV positions
                shape_data["cvPositions"] = [
                    [round(p[0], 4), round(p[1], 4), round(p[2], 4)]
                    for p in [
                        cmds.pointPosition(cv, local=True)
                        for cv in cmds.ls(shape + ".cv[*]", fl=1)
                    ]
                ]

                # Line width
                shape_data["lineWidth"] = cmds.getAttr(shape + ".lineWidth")

                # Degree
                shape_data["degree"] = cmds.getAttr("{}.degree".format(shape))

                # Spans
                shape_data["spans"] = cmds.getAttr("{}.spans".format(shape))

                # Form
                shape_data["form"] = cmds.getAttr("{}.form".format(shape))

                data.setdefault(ctrl, {})[cmds.ls(shape)[0]] = shape_data

    if not data:
        cmds.warning("No valid controllers found. Nothing to export.")
        return

    # Determine default path
    if not file_path:
        scene_path = cmds.file(q=True, sceneName=True)
        default_dir = (
            os.path.dirname(scene_path)
            if scene_path
            else cmds.workspace(q=True, rootDirectory=True)
        )

        file_path = cmds.fileDialog2(
            fileMode=0,
            dialogStyle=2,
            startingDirectory=default_dir,
            fileFilter="JSON Files (*.json)",
        )

        if not file_path:
            return
        else:
            file_path = file_path[0]

    # Save JSON
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)

    om.MGlobal.displayInfo("Exported Controller to : {}".format(file_path))

    return file_path


def _curve_shapes(node):
    """Non-intermediate nurbsCurve shapes of node, in the order export writes them."""
    return [
        shape
        for shape in cmds.listRelatives(node, shapes=True, fullPath=True, typ="nurbsCurve") or []
        if not cmds.getAttr(shape + ".intermediateObject")
    ]


def _curve_topology(node):
    """(degree, spans, form) per curve shape -- equal means CVs can be matched 1:1."""
    return [
        (
            cmds.getAttr(shape + ".degree"),
            cmds.getAttr(shape + ".spans"),
            cmds.getAttr(shape + ".form"),
        )
        for shape in _curve_shapes(node)
    ]


def _replace_control_shapes(ctrl, tmp_ctrl):
    """Swap ctrl's curve shapes for tmp_ctrl's when shape count / topology differ.

    AdvancedSkeleton (re)builds every control with a single default shape and
    its "keep curve shapes" only restores shapes whose name still matches --
    so a saved multi-shape or re-drawn control can't be restored by moving
    CVs; the shapes themselves must be replaced. Incoming connections on the
    old first shape (e.g. AS-driven visibility) are re-made on every new one,
    except construction history (".create"), which would overwrite the curve.
    """
    old_shapes = _curve_shapes(ctrl)

    connections = []
    if old_shapes:
        pairs = cmds.listConnections(old_shapes[0], source=True, destination=False, plugs=True, connections=True) or []
        for dst_plug, src_plug in zip(pairs[::2], pairs[1::2]):
            attr = dst_plug.split(".", 1)[1]
            if attr != "create":
                connections.append((src_plug, attr))
        cmds.delete(old_shapes)

    for shape in _curve_shapes(tmp_ctrl):
        cmds.parent(shape, ctrl, shape=True, relative=True)
    Controller.set_proper_shape_name(ctrl)

    for shape in _curve_shapes(ctrl):
        for src_plug, attr in connections:
            try:
                cmds.connectAttr(src_plug, "{}.{}".format(shape, attr), force=True)
            except RuntimeError as error:
                cmds.warning("Could not reconnect {} -> {}.{}: {}".format(src_plug, shape, attr, error))


def import_shape_custom(file_path=""):
    if not file_path:
        file_path = cmds.fileDialog2(
            fileFilter="JSON Files (*.json)",
            dialogStyle=2,
            caption="Load JSON File",
            fileMode=1,  # Open file
        )

        if not file_path:
            print("Load canceled.")
            return None
        else:
            file_path = file_path[0]

    dict_json = File.load_json_file_to_dict(file_path=file_path)
    list_not_exist = []
    # iterate to set up shape
    for ctrl_name in dict_json.keys():
        if cmds.objExists(ctrl_name):
            dict_curve_data = dict_json[ctrl_name]

            # create new controller shape
            tmp_ctrl = Controller.create_curve_from_data(dict_curve_data)

            if not tmp_ctrl:
                continue

            if _curve_topology(ctrl_name) == _curve_topology(tmp_ctrl):
                Transform.match_cvs(ctrl_name, tmp_ctrl)
            else:
                _replace_control_shapes(ctrl_name, tmp_ctrl)

            # apply style per shape (same order as export)
            list_ctrl_shape = _curve_shapes(ctrl_name)
            for shape, shape_data in zip(list_ctrl_shape, dict_curve_data.values()):
                if cmds.nodeType(shape) != "nurbsCurve":
                    continue

                Controller.set_color(color_data=shape_data["colorData"], list_input_transform=[shape])
                Controller.set_line_width(width=shape_data["lineWidth"], list_input_transform=[shape])

            cmds.delete(tmp_ctrl)

        else:
            list_not_exist.append(ctrl_name)

    if list_not_exist:
        cmds.warning("Does not exist control : {}".format(list_not_exist))


def create_script(name=None):
    quick_data_path = get_quick_data_dir()

    if not quick_data_path:
        raise Exception(
            "Quick Data Path not found. make sure you have save current file and create quick data."
        )

    script_path = os.path.join(quick_data_path, "Python")
    scene_path = cmds.file(q=True, sceneName=True)
    scene_name = os.path.basename(scene_path)
    scene_name_raw = os.path.splitext(scene_name)[0]
    scene_name_keyword = scene_name_raw.split("_")[0]

    local_script_main_path = os.path.join(script_path, scene_name_keyword)
    # make sure path exist
    os.makedirs(local_script_main_path, exist_ok=True)

    if name:
        python_file_name = name
    else:
        python_file_name = scene_name_keyword
    # check is scene raw name.py exist
    python_path = os.path.join(local_script_main_path, "{}.py".format(python_file_name))

    # if python path not exist, create the new one
    if os.path.exists(python_path):
        pass
    else:
        script_content = """
from tmlib.core import Selection, Attribute,,BlendShape,Connection,Create,Misc,Transform,Utility,SkinWeight,File,Controller,QuickData,System,Geometry,Visualized

import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMaya as om
import maya.mel as mel

System.reload_scripts()

def run():
    return
        """

        with open(python_path, "w") as f:
            f.write(script_content)

        print("Created new script : {}".format(python_path))

    # make sure .env is created
    env_path = os.path.join(script_path, ".env")
    tonmai_toolkit_dir = os.path.dirname(tmlib.__file__)
    path_level_1 = os.path.dirname(tonmai_toolkit_dir)
    path_level_2 = os.path.dirname(path_level_1)

    env_content = "PYTHONPATH={}".format(path_level_1)

    with open(env_path, "w") as f:
        f.write(env_content)

    print("env : path", env_path)
    # open the script
    try:
        os.startfile(python_path)
    except:
        cmds.warning("Cannot Start File (Only Support in Windows Os)")


def open_script_folder():
    quick_data_path = get_quick_data_dir()
    path = os.path.join(quick_data_path, "Python")

    os.makedirs(path, exist_ok=True)

    os.startfile(path)


def run_script_file(script_path, order=None):
    if not os.path.exists(script_path):
        cmds.warning(f"Directory not found: {script_path}")
        return

    execution_list = []

    if order and isinstance(order, list):
        for name in order:
            file_name = name if name.endswith(".py") else f"{name}.py"
            full_path = os.path.join(script_path, file_name)
            if os.path.exists(full_path):
                execution_list.append(full_path)
    else:
        files = [f for f in os.listdir(script_path) if f.endswith(".py")]
        files.sort()
        execution_list = [os.path.join(script_path, f) for f in files]

    if not execution_list:
        return

    cmds.undoInfo(openChunk=True, chunkName="RunScriptFileOrdered")

    try:
        for python_path in execution_list:
            file_name = os.path.basename(python_path)
            module_name = os.path.splitext(file_name)[0]

            spec = importlib.util.spec_from_file_location(module_name, python_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, "run"):
                module.run()

        cmds.inViewMessage(
            amg=f"<hl>Run Scripts : {order} , {len(execution_list)} files</hl>",
            pos="midCenter",
            fade=True,
        )

    except Exception as e:
        cmds.warning(f"Execution failed: {str(e)}")

    finally:
        cmds.undoInfo(closeChunk=True)

    return