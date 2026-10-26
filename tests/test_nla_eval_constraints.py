"""NLA evaluation and cross-object constraint regressions; run in Blender.

Quick FBX samples the temporary NLA tracks, so an owner with NLA evaluation
turned off used to export every take as a still pose. Quick GLB samples each
object's clip separately, so constraints that follow another animated object
export wrong motion; preflight has to say so.
"""

from pathlib import Path
import sys
import tempfile

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import hyper_NLA_exporter as addon


def reset():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for data in (bpy.data.actions, bpy.data.armatures):
        for block in list(data):
            data.remove(block)
    scene = bpy.context.scene
    scene.timeline_markers.clear()
    scene.timeline_markers.new('First', frame=10)
    scene.timeline_markers.new('Second', frame=20)
    scene.m2nla_open_folder = False
    scene.m2nla_auto_export = False
    scene.m2nla_selected_only = True
    scene.m2nla_start_frame = 1
    scene.m2nla_boundary_keys = True
    return scene


def key_x(owner, keyed_object):
    """First moves 0→9, Second 100→109 on location.x."""
    for frame, value in ((1, 0), (10, 9), (11, 100), (20, 109)):
        owner.location.x = value
        owner.keyframe_insert('location', index=0, frame=frame)
    for curve in addon._get_fcurves(keyed_object.animation_data.action):
        for point in curve.keyframe_points:
            point.interpolation = 'LINEAR'


def empty(name, keyed=True):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if keyed:
        key_x(obj, obj)
    return obj


def rig(name='Rig'):
    obj = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    for bone_name in ('Bone', 'Target'):
        bone = obj.data.edit_bones.new(bone_name)
        bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode='OBJECT')
    key_x(obj.pose.bones['Bone'], obj)
    return obj


def reimported_takes(path):
    """Return ``{take: (first x, last x)}`` for every location.x curve."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action, do_unlink=True)
    bpy.ops.import_scene.fbx(filepath=str(path))
    takes = {}
    for action in bpy.data.actions:
        for curve in addon._get_fcurves(action):
            if (curve.data_path.endswith('location')
                    and curve.array_index == 0 and curve.keyframe_points):
                points = curve.keyframe_points
                takes[(action.name, curve.data_path)] = (
                    round(points[0].co[1], 4), round(points[-1].co[1], 4))
    return takes


def assert_moving_takes(takes, data_path):
    """Both takes carry the real motion, not a still pose."""
    found = {name.split('|')[-1]: values
             for (name, path), values in takes.items() if path == data_path}
    assert found == {'First': (0.0, 9.0), 'Second': (100.0, 109.0)}, takes


def test_fbx_exports_motion_with_nla_evaluation_off():
    with tempfile.TemporaryDirectory(prefix='hyper_nla_use_nla_') as tmp:
        reset()
        obj = empty('Mover')
        obj.animation_data.use_nla = False
        path = Path(tmp) / 'object.fbx'
        assert bpy.ops.markernla.quick_export_fbx(
            filepath=str(path)) == {'FINISHED'}
        assert obj.animation_data.use_nla is False  # Restored.
        assert_moving_takes(reimported_takes(path), 'location')

        reset()
        armature = rig()
        armature.animation_data.use_nla = False
        path = Path(tmp) / 'rig.fbx'
        assert bpy.ops.markernla.quick_export_fbx(
            filepath=str(path)) == {'FINISHED'}
        assert armature.animation_data.use_nla is False
        assert_moving_takes(reimported_takes(path),
                            'pose.bones["Bone"].location')


def constraint_warnings(export_format='GLB'):
    return [text for level, text
            in addon.collect_export_issues(bpy.context, export_format)
            if level == 'WARNING' and 'Constraints following' in text]


def test_preflight_warns_about_cross_object_constraints():
    for keyed in (True, False):
        reset()
        target = empty('Target')
        follower = empty('Follower', keyed=keyed)
        constraint = follower.constraints.new('COPY_LOCATION')
        constraint.target = target
        warnings = constraint_warnings()
        assert len(warnings) == 1 and 'Follower → Target' in warnings[0], (
            keyed, warnings)
        assert not constraint_warnings('FBX')

        constraint.enabled = False
        assert not constraint_warnings(), keyed


def test_constraints_without_an_animated_other_object_are_quiet():
    reset()
    # A static target is sampled the same in every clip.
    still = empty('Still', keyed=False)
    follower = empty('Follower')
    follower.constraints.new('COPY_ROTATION').target = still
    assert not constraint_warnings()

    # A bone following a bone of its own armature stays inside one object.
    reset()
    armature = rig()
    ik = armature.pose.bones['Bone'].constraints.new('IK')
    ik.target = armature
    ik.subtarget = 'Target'
    assert not constraint_warnings()

    # A bone following another animated object is the same GLB problem.
    handle = empty('Handle')
    armature.select_set(True)
    ik.target = handle
    warnings = constraint_warnings()
    assert len(warnings) == 1 and 'Rig → Handle' in warnings[0], warnings


def run_all():
    addon.register()
    try:
        for name, test in list(globals().items()):
            if name.startswith('test_') and callable(test):
                test()
                print('PASS', name)
    finally:
        addon.unregister()
    print('HYPER_NLA_EVAL_CONSTRAINT_TESTS_OK')


if __name__ == '__main__':
    run_all()
