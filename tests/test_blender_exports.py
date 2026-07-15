"""End-to-end FBX and GLB Quick Export regression test."""

from pathlib import Path
import json
import shutil
import struct
import sys

import bpy


ADDONS_DIR = Path(__file__).resolve().parents[2]
if str(ADDONS_DIR) not in sys.path:
    sys.path.insert(0, str(ADDONS_DIR))

import hyper_NLA_exporter as addon


def build_animated_cube(name, location_x):
    bpy.ops.mesh.primitive_cube_add(location=(location_x, 0, 0))
    cube = bpy.context.object
    cube.name = name
    cube.animation_data_create()

    action = bpy.data.actions.new(f"{name}Action")
    channelbag = addon._ensure_channelbag(action, cube)
    curve = channelbag.fcurves.new("location", index=0)
    for frame, value in ((1, 0), (2, 1), (3, 2), (4, 3)):
        curve.keyframe_points.insert(frame, value)
    cube.animation_data.action = action
    cube.animation_data.action_slot = channelbag.slot
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    return cube, action


def add_existing_nla_track(cube):
    action = bpy.data.actions.new("ExistingNLAAction")
    channelbag = addon._ensure_channelbag(action, cube)
    curve = channelbag.fcurves.new("rotation_euler", index=2)
    curve.keyframe_points.insert(1, 0)
    curve.keyframe_points.insert(4, 1)

    track = cube.animation_data.nla_tracks.new()
    track.name = "ExistingNLA"
    strip = track.strips.new("ExistingNLA", 1, action)
    strip.action_slot = channelbag.slot
    track.mute = False
    track.is_solo = True
    return track


_COMPONENT_FORMATS = {
    5120: 'b',   # BYTE
    5121: 'B',   # UNSIGNED_BYTE
    5122: 'h',   # SHORT
    5123: 'H',   # UNSIGNED_SHORT
    5125: 'I',   # UNSIGNED_INT
    5126: 'f',   # FLOAT
}

_TYPE_COMPONENT_COUNTS = {
    'SCALAR': 1,
    'VEC2': 2,
    'VEC3': 3,
    'VEC4': 4,
    'MAT2': 4,
    'MAT3': 9,
    'MAT4': 16,
}


def read_glb(filepath):
    with filepath.open('rb') as handle:
        magic, version, total_length = struct.unpack('<4sII', handle.read(12))
        assert magic == b'glTF'
        assert version == 2
        chunks = {}
        while handle.tell() < total_length:
            chunk_length, chunk_type = struct.unpack('<II', handle.read(8))
            chunks[chunk_type] = handle.read(chunk_length)

    document = json.loads(chunks[0x4E4F534A].decode('utf-8'))  # JSON
    binary = chunks.get(0x004E4942, b'')  # BIN
    return document, binary


def read_accessor(document, binary, accessor_index):
    accessor = document['accessors'][accessor_index]
    buffer_view = document['bufferViews'][accessor['bufferView']]
    component_format = _COMPONENT_FORMATS[accessor['componentType']]
    component_count = _TYPE_COMPONENT_COUNTS[accessor['type']]
    value_format = '<' + component_format * component_count
    value_size = struct.calcsize(value_format)
    byte_stride = buffer_view.get('byteStride', value_size)
    byte_offset = (buffer_view.get('byteOffset', 0)
                   + accessor.get('byteOffset', 0))

    return [
        struct.unpack_from(
            value_format,
            binary,
            byte_offset + index * byte_stride,
        )
        for index in range(accessor['count'])
    ]


def read_glb_animation_data(filepath):
    document, binary = read_glb(filepath)
    nodes = document.get('nodes', [])
    animations = document.get('animations', [])

    summary = [
        (
            animation.get('name'),
            len({channel['target'].get('node')
                 for channel in animation.get('channels', [])}),
        )
        for animation in animations
    ]

    samples = {}
    for animation in animations:
        clip_samples = {}
        for channel in animation.get('channels', []):
            target = channel['target']
            if target.get('path') != 'translation':
                continue
            sampler = animation['samplers'][channel['sampler']]
            node_name = nodes[target['node']]['name']
            times = [value[0] for value in read_accessor(
                document, binary, sampler['input'])]
            translations = read_accessor(
                document, binary, sampler['output'])
            clip_samples[node_name] = (times, translations)
        samples[animation.get('name')] = clip_samples

    return summary, samples


def assert_glb_sample_values(samples, fps):
    expected_x_values = {
        'First': (0.0, 1.0),
        'Second': (2.0, 3.0),
    }
    expected_times = (0.0, 1.0 / fps)

    for clip_name, expected_x in expected_x_values.items():
        clip_samples = samples[clip_name]
        assert set(clip_samples) == {'ExportCube', 'SecondCube'}
        for node_name, (times, translations) in clip_samples.items():
            assert len(times) == len(expected_times), (clip_name, node_name, times)
            assert len(translations) == len(expected_x), (
                clip_name, node_name, translations)
            for actual, expected in zip(times, expected_times):
                assert abs(actual - expected) < 1e-6, (
                    clip_name, node_name, times)
            for translation, expected_x_value in zip(
                    translations, expected_x):
                assert abs(translation[0] - expected_x_value) < 1e-6, (
                    clip_name, node_name, translations)
                assert abs(translation[1]) < 1e-6, (
                    clip_name, node_name, translations)
                assert abs(translation[2]) < 1e-6, (
                    clip_name, node_name, translations)


def clear_scene_for_fbx_import(scene):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action, do_unlink=True)
    for marker in list(scene.timeline_markers):
        scene.timeline_markers.remove(marker)


def assert_fbx_reimport(filepath, scene):
    clear_scene_for_fbx_import(scene)
    import_result = bpy.ops.import_scene.fbx(
        filepath=str(filepath),
        use_anim=True,
    )
    assert import_result == {'FINISHED'}, import_result

    imported_objects = list(scene.objects)
    assert [(obj.name, obj.type) for obj in imported_objects] == [
        ('ExportCube', 'MESH'),
    ]
    imported_object = imported_objects[0]

    expected_actions = {
        'ExportCube|First': (0.0, 1.0),
        'ExportCube|Second': (2.0, 3.0),
    }
    imported_action_names = {action.name for action in bpy.data.actions}
    assert imported_action_names == set(expected_actions), imported_action_names
    assert all('ExistingNLA' not in name for name in imported_action_names)

    anim = imported_object.animation_data
    assert anim is not None
    for action_name, expected_x_values in expected_actions.items():
        action = bpy.data.actions[action_name]
        assert tuple(action.frame_range) == (1.0, 2.0)
        anim.action = action
        assert action.slots
        anim.action_slot = action.slots[0]

        samples = []
        for frame in (1, 2):
            scene.frame_set(frame)
            samples.append(tuple(imported_object.location))

        for translation, expected_x in zip(samples, expected_x_values):
            assert abs(translation[0] - expected_x) < 1e-5, (
                action_name, samples)
            assert abs(translation[1]) < 1e-5, (action_name, samples)
            assert abs(translation[2]) < 1e-5, (action_name, samples)


def run_export_test():
    addon.register()
    scene = bpy.context.scene
    scene.timeline_markers.new("First", frame=2)
    scene.timeline_markers.new("Second", frame=4)
    scene.m2nla_selected_only = True
    scene.m2nla_open_folder = False
    scene.m2nla_auto_export = False
    cube, source_action = build_animated_cube("ExportCube", 0)
    second_cube, second_source_action = build_animated_cube("SecondCube", 2)
    cube.select_set(True)
    second_cube.select_set(False)
    bpy.context.view_layer.objects.active = cube
    existing_track = add_existing_nla_track(cube)

    second_cube.select_set(True)
    multiple_target_issues = addon.collect_export_issues(
        bpy.context, 'FBX')
    assert any(
        severity == 'ERROR' and 'one animated object' in message
        for severity, message in multiple_target_issues
    ), multiple_target_issues
    second_cube.select_set(False)

    output_dir = Path(__file__).resolve().parents[1] / ".test_output"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    try:
        fbx_path = output_dir / "clips.fbx"
        glb_path = output_dir / "clips.glb"
        fbx_result = bpy.ops.markernla.quick_export_fbx(
            'EXEC_DEFAULT', filepath=str(fbx_path))

        second_cube.select_set(True)
        glb_result = bpy.ops.markernla.quick_export_glb(
            'EXEC_DEFAULT', filepath=str(glb_path))

        assert fbx_result == {'FINISHED'}, fbx_result
        assert glb_result == {'FINISHED'}, glb_result
        assert fbx_path.stat().st_size > 0
        assert glb_path.stat().st_size > 0
        fbx_data = fbx_path.read_bytes()
        assert b"First" in fbx_data
        assert b"Second" in fbx_data
        assert b"ExistingNLA" not in fbx_data
        animation_summary, animation_samples = read_glb_animation_data(glb_path)
        assert animation_summary == [
            ("First", 2),
            ("Second", 2),
        ], animation_summary
        assert_glb_sample_values(
            animation_samples,
            scene.render.fps / scene.render.fps_base,
        )
        assert cube.animation_data.action == source_action
        assert second_cube.animation_data.action == second_source_action
        assert len(cube.animation_data.nla_tracks) == 1
        assert len(second_cube.animation_data.nla_tracks) == 0
        assert cube.animation_data.nla_tracks[0] == existing_track
        assert not existing_track.mute
        assert existing_track.is_solo
        assert not existing_track.strips[0].mute
        assert not any(action.name.startswith("ExportCube_")
                       for action in bpy.data.actions)
        assert_fbx_reimport(fbx_path, scene)
    finally:
        addon.unregister()
        if output_dir.exists():
            shutil.rmtree(output_dir)


if __name__ == "__main__":
    run_export_test()
    print("HYPER_NLA_EXPORT_TESTS_OK")
