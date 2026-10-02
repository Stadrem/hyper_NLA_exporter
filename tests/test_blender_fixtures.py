"""Regression tests that run against the real rig .blend fixtures."""

from pathlib import Path
import json
import struct
import sys
import tempfile

import bpy


ADDONS_DIR = Path(__file__).resolve().parents[2]
if str(ADDONS_DIR) not in sys.path:
    sys.path.insert(0, str(ADDONS_DIR))

import hyper_NLA_exporter as addon


EXPECTED_CLIPS = {
    "Linage",
    "LtoS",
    "StoL",
    "StoU",
    "Straight",
    "UtoS",
    "Uturn",
}

SOURCE_MARKERS = [
    ("Linage", 9),
    ("LtoS", 18),
    ("StoL", 27),
    ("StoU", 37),
    ("Straight", 46),
    ("UtoS", 55),
    ("Uturn", 63),
]


def action_fcurve_count(action):
    return sum(
        len(channelbag.fcurves)
        for layer in action.layers
        for strip in layer.strips
        for channelbag in getattr(strip, "channelbags", [])
    )


def nla_signature(obj):
    anim = obj.animation_data
    if anim is None:
        return ()
    return tuple(
        (
            track.name,
            track.mute,
            getattr(track, "is_solo", False),
            tuple(
                (
                    strip.name,
                    getattr(strip.action, "name", None),
                    strip.mute,
                    float(strip.frame_start),
                    float(strip.frame_end),
                )
                for strip in track.strips
            ),
        )
        for track in anim.nla_tracks
    )


def select_only(*objects):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def read_glb_clip_names(filepath):
    with filepath.open('rb') as handle:
        magic, version, total_length = struct.unpack('<4sII', handle.read(12))
        assert magic == b'glTF'
        assert version == 2
        while handle.tell() < total_length:
            chunk_length, chunk_type = struct.unpack('<II', handle.read(8))
            chunk = handle.read(chunk_length)
            if chunk_type == 0x4E4F534A:  # JSON
                document = json.loads(chunk.decode('utf-8'))
                return {
                    animation['name']
                    for animation in document.get('animations', [])
                }
    raise AssertionError("GLB JSON chunk was not found")


def clear_scene_data(scene):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action, do_unlink=True)
    for marker in list(scene.timeline_markers):
        scene.timeline_markers.remove(marker)


def clip_name_from_imported_action(action_name):
    for clip_name in EXPECTED_CLIPS:
        if action_name == clip_name or action_name.endswith(f"|{clip_name}"):
            return clip_name
    return None


def assert_fbx_reimport(filepath, scene, expected_ends):
    clear_scene_data(scene)
    result = bpy.ops.import_scene.fbx(filepath=str(filepath), use_anim=True)
    assert result == {'FINISHED'}, result

    armatures = [obj for obj in scene.objects if obj.type == 'ARMATURE']
    assert len(armatures) == 1, [obj.name for obj in armatures]
    assert len(armatures[0].data.bones) == 18

    imported_actions = {
        action.name: clip_name_from_imported_action(action.name)
        for action in bpy.data.actions
    }
    assert None not in imported_actions.values(), imported_actions
    assert set(imported_actions.values()) == EXPECTED_CLIPS, imported_actions

    for action_name, clip_name in imported_actions.items():
        action = bpy.data.actions[action_name]
        expected_range = (1.0, float(expected_ends[clip_name]))
        assert tuple(action.frame_range) == expected_range, (
            action_name,
            tuple(action.frame_range),
            expected_range,
        )


def configure_export_scene(scene):
    scene.m2nla_selected_only = True
    scene.m2nla_open_folder = False
    scene.m2nla_auto_export = False


def test_source_fixture():
    scene = bpy.context.scene
    armature = bpy.data.objects['Scene']
    mesh = bpy.data.objects['NextStep_Arrow']
    action = bpy.data.actions['Scene_Merged']

    assert armature.type == 'ARMATURE'
    assert len(armature.data.bones) == 18
    assert mesh.type == 'MESH'
    assert mesh.parent == armature
    assert any(
        modifier.type == 'ARMATURE' and modifier.object == armature
        for modifier in mesh.modifiers
    )
    assert [(marker.name, marker.frame)
            for marker in scene.timeline_markers] == SOURCE_MARKERS
    assert armature.animation_data.action == action
    assert tuple(action.frame_range) == (1.0, 63.0)
    assert action_fcurve_count(action) == 180

    configure_export_scene(scene)
    select_only(armature, mesh)
    anim = armature.animation_data
    original_action = anim.action
    original_slot = anim.action_slot
    original_nla = nla_signature(armature)
    original_frame_range = (scene.frame_start, scene.frame_end)
    original_selection = {obj.name for obj in bpy.context.selected_objects}
    original_action_names = set(bpy.data.actions.keys())

    expected_ends = {}
    segment_start = 1
    for clip_name, marker_frame in SOURCE_MARKERS:
        expected_ends[clip_name] = marker_frame - segment_start + 1
        segment_start = marker_frame + 1

    with tempfile.TemporaryDirectory(prefix="hyper_nla_source_") as temp_dir:
        output_dir = Path(temp_dir)
        fbx_path = output_dir / "NextStep_Arrow.fbx"
        glb_path = output_dir / "NextStep_Arrow.glb"

        fbx_result = bpy.ops.markernla.quick_export_fbx(
            'EXEC_DEFAULT', filepath=str(fbx_path))
        glb_result = bpy.ops.markernla.quick_export_glb(
            'EXEC_DEFAULT', filepath=str(glb_path))

        assert fbx_result == {'FINISHED'}, fbx_result
        assert glb_result == {'FINISHED'}, glb_result
        assert fbx_path.stat().st_size > 0
        assert glb_path.stat().st_size > 0
        assert read_glb_clip_names(glb_path) == EXPECTED_CLIPS

        assert anim.action == original_action
        assert anim.action_slot == original_slot
        assert nla_signature(armature) == original_nla
        assert (scene.frame_start, scene.frame_end) == original_frame_range
        assert {obj.name for obj in bpy.context.selected_objects} == original_selection
        assert set(bpy.data.actions.keys()) == original_action_names

        assert_fbx_reimport(fbx_path, scene, expected_ends)


def test_nla_fixture():
    scene = bpy.context.scene
    armature = bpy.data.objects['Scene']
    mesh = bpy.data.objects['NextStep_Arrow']

    assert armature.type == 'ARMATURE'
    assert len(armature.data.bones) == 18
    assert mesh.parent == armature
    assert any(
        modifier.type == 'ARMATURE' and modifier.object == armature
        for modifier in mesh.modifiers
    )

    original_nla = nla_signature(armature)
    assert {track[0] for track in original_nla} == EXPECTED_CLIPS
    assert all(len(track[3]) == 1 for track in original_nla)
    assert all(track[0] == track[3][0][0] == track[3][0][1]
               for track in original_nla)
    expected_ends = {
        track_name: int(round(strips[0][4]))
        for track_name, _mute, _solo, strips in original_nla
    }

    configure_export_scene(scene)
    select_only(armature, mesh)
    original_action = getattr(armature.animation_data, 'action', None)
    original_action_names = set(bpy.data.actions.keys())
    original_track_states = {
        track.name: (track.mute, getattr(track, 'is_solo', False))
        for track in armature.animation_data.nla_tracks
    }

    # This fixture is intentionally saved with every track muted. Enable the
    # clips only for the test so the source .blend remains untouched on disk.
    for track in armature.animation_data.nla_tracks:
        track.mute = False
        track.is_solo = False
    export_nla = nla_signature(armature)
    assert all(not track[1] and not track[2] for track in export_nla)

    with tempfile.TemporaryDirectory(prefix="hyper_nla_tracks_") as temp_dir:
        output_dir = Path(temp_dir)
        fbx_path = output_dir / "NextStep_Arrow_NLA.fbx"
        glb_path = output_dir / "NextStep_Arrow_NLA.glb"

        fbx_result = bpy.ops.markernla.export_fbx(
            'EXEC_DEFAULT', filepath=str(fbx_path))
        glb_result = bpy.ops.markernla.export_glb(
            'EXEC_DEFAULT', filepath=str(glb_path))

        assert fbx_result == {'FINISHED'}, fbx_result
        assert glb_result == {'FINISHED'}, glb_result
        assert fbx_path.stat().st_size > 0
        assert glb_path.stat().st_size > 0
        assert read_glb_clip_names(glb_path) == EXPECTED_CLIPS

        assert armature.animation_data.action == original_action
        assert nla_signature(armature) == export_nla
        assert set(bpy.data.actions.keys()) == original_action_names

        scene.m2nla_clear_nla = False
        merge_result = bpy.ops.markernla.merge('EXEC_DEFAULT')
        assert merge_result == {'FINISHED'}, merge_result
        merged = armature.animation_data.action
        assert merged is not None
        assert merged.name.startswith("Scene_Merged")
        assert action_fcurve_count(merged) > 0
        assert nla_signature(armature) == export_nla

        for track in armature.animation_data.nla_tracks:
            track.mute, track.is_solo = original_track_states[track.name]
        assert nla_signature(armature) == original_nla

        assert_fbx_reimport(fbx_path, scene, expected_ends)


def main():
    fixture_name = Path(bpy.data.filepath).name
    addon.register()
    try:
        if fixture_name == "NextStep_Arrow.blend":
            test_source_fixture()
        elif fixture_name == "NextStep_Arrow_NLA.blend":
            test_nla_fixture()
        else:
            raise AssertionError(f"Unsupported fixture: {fixture_name}")
    finally:
        addon.unregister()
    print(f"HYPER_NLA_FIXTURE_TESTS_OK: {fixture_name}")


if __name__ == "__main__":
    main()
