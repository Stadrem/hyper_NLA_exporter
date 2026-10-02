"""Run with Blender --background --factory-startup --python this_file."""

from pathlib import Path
import sys
import tempfile

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hyper_NLA_exporter as addon
from hyper_NLA_exporter.nla_split import _iter_animation_datablocks
from test_blender_exports import read_glb, read_accessor


def make_action(owner, path, values, name):
    owner.animation_data_create()
    action = bpy.data.actions.new(name)
    bag = addon._ensure_channelbag(action, owner)
    curve = bag.fcurves.new(path, index=0)
    for frame, value in enumerate(values, 1):
        key = curve.keyframe_points.insert(frame, value)
        key.interpolation = 'LINEAR'
    owner.animation_data.action = action
    owner.animation_data.action_slot = bag.slot
    return action


def setup_scene(shape_only=False, parent_only=False, rig_parent=False):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action, do_unlink=True)
    scene = bpy.context.scene
    for marker in list(scene.timeline_markers):
        scene.timeline_markers.remove(marker)
    scene.m2nla_start_frame = 1
    scene.m2nla_boundary_keys = True
    scene.m2nla_selected_only = True
    scene.m2nla_auto_export = False
    scene.m2nla_open_folder = False
    scene.frame_start = 1
    scene.frame_end = 20
    scene.timeline_markers.new('Walk', frame=2)
    scene.timeline_markers.new('Run', frame=4)
    bpy.ops.mesh.primitive_cube_add()
    mesh = bpy.context.object
    mesh.name = 'Face'
    mesh.shape_key_add(name='Basis')
    smile = mesh.shape_key_add(name='Smile')
    smile.data[0].co.z += 1.0
    mesh.modifiers.new('Subdivision', 'SUBSURF').levels = 1
    keys = mesh.data.shape_keys
    source = make_action(keys, 'key_blocks["Smile"].value',
                         (0.0, 0.3, 0.7, 1.0), 'OriginalFace')
    slot = keys.animation_data.action_slot
    old_action = bpy.data.actions.new('OldFace')
    bag = addon._ensure_channelbag(old_action, keys)
    curve = bag.fcurves.new('key_blocks["Smile"].value')
    curve.keyframe_points.insert(1, 0.9)
    curve.keyframe_points.insert(4, 0.9)
    track = keys.animation_data.nla_tracks.new()
    track.name = 'ExistingFace'
    strip = track.strips.new('ExistingFace', 1, old_action)
    strip.action_slot = bag.slot
    track.is_solo = True
    if not shape_only:
        make_action(mesh, 'location', (0, 1, 2, 3), 'OriginalMove')
    selected = mesh
    if parent_only:
        if rig_parent:
            bpy.ops.object.armature_add()
            parent = bpy.context.object
            parent.name = 'Rig'
            group = mesh.vertex_groups.new(name='Bone')
            group.add(list(range(len(mesh.data.vertices))), 1.0, 'REPLACE')
            modifier = mesh.modifiers.new('Skin', 'ARMATURE')
            modifier.object = parent
            action_path = 'pose.bones["Bone"].location'
        else:
            parent = bpy.data.objects.new('Parent', None)
            scene.collection.objects.link(parent)
            action_path = 'location'
        mesh.parent = parent
        make_action(parent, action_path, (0, 1, 2, 3), 'ParentMove')
        mesh.select_set(False)
        parent.select_set(True)
        bpy.context.view_layer.objects.active = parent
        selected = parent
    scene.frame_set(3)
    return mesh, keys, source, slot, track, selected


def assert_export(path, shape_only=False, parent_only=False, rig_parent=False):
    mesh, keys, source, slot, track, selected = setup_scene(
        shape_only, parent_only, rig_parent)
    before_actions = set(bpy.data.actions.keys())
    before_value = keys.key_blocks['Smile'].value
    for allow_multiple in (False, True):
        fbx_issues = addon.collect_export_issues(
            bpy.context, 'FBX', allow_multiple_fbx_targets=allow_multiple)
        assert any(severity == 'ERROR' and 'Shape Key' in message
                   and 'GLB' in message
                   for severity, message in fbx_issues), fbx_issues
    result = bpy.ops.markernla.quick_export_glb(
        'EXEC_DEFAULT', filepath=str(path))
    assert result == {'FINISHED'}, result
    document, binary = read_glb(path)
    assert all(len(primitive.get('targets', [])) == 1
               for exported_mesh in document['meshes']
               for primitive in exported_mesh['primitives']), document['meshes']
    animations = {item['name']: item for item in document['animations']}
    if rig_parent:
        assert len(document.get('skins', [])) == 1, document
    assert set(animations) == {'Walk', 'Run'}, list(animations)
    fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    for clip_name, expected in [('Walk', (0.0, 0.3)), ('Run', (0.7, 1.0))]:
        animation = animations[clip_name]
        channels = animation['channels']
        weight_channels = [channel for channel in channels
                           if channel['target']['path'] == 'weights']
        assert len(weight_channels) == 1, channels
        sampler = animation['samplers'][weight_channels[0]['sampler']]
        values = [row[0] for row in read_accessor(document, binary, sampler['output'])]
        times = [row[0] for row in read_accessor(document, binary, sampler['input'])]
        assert len(values) == 2, values
        assert all(abs(value - target) < 1e-5
                   for value, target in zip(values, expected)), (clip_name, values)
        assert len(times) == 2 and abs(times[0]) < 1e-6
        assert abs(times[-1] - 1 / fps) < 1e-6, times
        if not shape_only or parent_only:
            assert any(channel['target']['path'] == 'translation'
                       for channel in channels), channels
    assert keys.animation_data.action == source
    assert keys.animation_data.action_slot == slot
    assert list(keys.animation_data.nla_tracks) == [track]
    assert track.is_solo and not track.mute and not track.strips[0].mute
    assert set(bpy.data.actions.keys()) == before_actions
    assert bpy.context.scene.frame_current == 3
    assert bpy.context.scene.frame_end == 20
    assert abs(keys.key_blocks['Smile'].value - before_value) < 1e-6
    assert set(bpy.context.selected_objects) == {selected}


def test_modifier_without_shape_keys(path):
    mesh, _keys, _source, _slot, _track, _selected = setup_scene()
    mesh.shape_key_clear()
    assert mesh.data.shape_keys is None
    result = bpy.ops.markernla.quick_export_glb(
        'EXEC_DEFAULT', filepath=str(path))
    assert result == {'FINISHED'}, result
    document, binary = read_glb(path)
    positions = set()
    for exported_mesh in document['meshes']:
        for primitive in exported_mesh['primitives']:
            positions.update(read_accessor(
                document, binary, primitive['attributes']['POSITION']))
    # A plain cube can have 24 exported vertices because of split normals;
    # count unique positions so this proves Subdivision really was applied.
    assert len(positions) > 8, positions
    assert {animation['name'] for animation in document['animations']} == {
        'Walk', 'Run'}


def test_failure_and_shared_data():
    mesh, keys, source, slot, track, _selected = setup_scene()
    other = mesh.copy()
    other.data = mesh.data
    bpy.context.scene.collection.objects.link(other)
    owners = list(_iter_animation_datablocks([mesh, other, keys]))
    assert owners.count(keys) == 1, owners
    action_names = set(bpy.data.actions.keys())
    try:
        with addon._temporary_nla_split([mesh, other, keys], bpy.context.scene):
            assert len(keys.animation_data.nla_tracks) == 3
            assert track.mute and not track.is_solo and track.strips[0].mute
            raise RuntimeError('Simulated exporter failure')
    except RuntimeError as exc:
        assert str(exc) == 'Simulated exporter failure'
    assert keys.animation_data.action == source
    assert keys.animation_data.action_slot == slot
    assert list(keys.animation_data.nla_tracks) == [track]
    assert not track.mute and track.is_solo and not track.strips[0].mute
    assert set(bpy.data.actions.keys()) == action_names


if __name__ == '__main__':
    addon.register()
    try:
        with tempfile.TemporaryDirectory(prefix='hyper_nla_shape_') as directory:
            assert_export(Path(directory) / 'combined.glb')
            assert_export(Path(directory) / 'shape_only.glb', shape_only=True)
            assert_export(Path(directory) / 'child.glb', shape_only=True, parent_only=True)
            assert_export(Path(directory) / 'skinned.glb', shape_only=True,
                          parent_only=True, rig_parent=True)
            test_modifier_without_shape_keys(Path(directory) / 'subdivided.glb')
        test_failure_and_shared_data()
        print('HYPER_NLA_SHAPE_KEY_TESTS_OK')
    finally:
        addon.unregister()
