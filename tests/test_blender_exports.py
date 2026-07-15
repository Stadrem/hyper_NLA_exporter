"""End-to-end FBX and GLB Quick Export regression test."""

from pathlib import Path
import shutil
import sys

import bpy


ADDONS_DIR = Path(__file__).resolve().parents[2]
if str(ADDONS_DIR) not in sys.path:
    sys.path.insert(0, str(ADDONS_DIR))

import hyper_NLA_exporter as addon


def build_animated_cube():
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.object
    cube.name = "ExportCube"
    cube.animation_data_create()

    action = bpy.data.actions.new("CubeAction")
    channelbag = addon._ensure_channelbag(action, cube)
    curve = channelbag.fcurves.new("location", index=0)
    for frame, value in ((1, 0), (2, 1), (3, 2), (4, 3)):
        curve.keyframe_points.insert(frame, value)
    cube.animation_data.action = action
    cube.animation_data.action_slot = channelbag.slot
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    return cube, action


def run_export_test():
    addon.register()
    scene = bpy.context.scene
    scene.timeline_markers.new("First", frame=2)
    scene.timeline_markers.new("Second", frame=4)
    scene.m2nla_selected_only = True
    scene.m2nla_open_folder = False
    scene.m2nla_auto_export = False
    cube, source_action = build_animated_cube()

    output_dir = Path(__file__).resolve().parents[1] / ".test_output"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    try:
        fbx_path = output_dir / "clips.fbx"
        glb_path = output_dir / "clips.glb"
        fbx_result = bpy.ops.markernla.quick_export_fbx(
            'EXEC_DEFAULT', filepath=str(fbx_path))
        glb_result = bpy.ops.markernla.quick_export_glb(
            'EXEC_DEFAULT', filepath=str(glb_path))

        assert fbx_result == {'FINISHED'}, fbx_result
        assert glb_result == {'FINISHED'}, glb_result
        assert fbx_path.stat().st_size > 0
        assert glb_path.stat().st_size > 0
        assert cube.animation_data.action == source_action
        assert len(cube.animation_data.nla_tracks) == 0
        assert not any(action.name.startswith("ExportCube_")
                       for action in bpy.data.actions)
    finally:
        addon.unregister()
        if output_dir.exists():
            shutil.rmtree(output_dir)


if __name__ == "__main__":
    run_export_test()
    print("HYPER_NLA_EXPORT_TESTS_OK")
