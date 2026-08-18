import maya.cmds as cmds

def fix_sound_offset():
    sound_nodes = cmds.ls(type="audio")
    sound_node_name = sound_nodes[0] if sound_nodes else ""

    if sound_node_name:
        current_source_start = cmds.getAttr("{}.sourceStart".format(sound_node_name))
        current_offset = cmds.getAttr("{}.offset".format(sound_node_name))

        if current_source_start != 0:
            cmds.setAttr("{}.sourceStart".format(sound_node_name), 0)
            cmds.setAttr(
                "{}.offset".format(sound_node_name),
                current_offset - current_source_start,
            )

    cmds.inViewMessage( amg='<hl>Sound Offset has been fixed</hl>.', pos='midCenter', fade=True )