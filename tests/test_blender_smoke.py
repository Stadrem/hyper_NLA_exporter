"""Blender background smoke tests for the refactored addon package."""

from pathlib import Path
import sys

import bpy


ADDONS_DIR = Path(__file__).resolve().parents[2]
if str(ADDONS_DIR) not in sys.path:
    sys.path.insert(0, str(ADDONS_DIR))

import hyper_NLA_exporter as addon


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for marker in list(bpy.context.scene.timeline_markers):
        bpy.context.scene.timeline_markers.remove(marker)


def test_registration():
    addon.register()
    assert hasattr(bpy.types.Scene, "m2nla_export_path")
    assert hasattr(bpy.types.TimelineMarker, "m2nla_muted")
    assert hasattr(bpy.types, "MARKERNLA_PT_panel")
    addon.unregister()
    assert not hasattr(bpy.types.Scene, "m2nla_export_path")
    assert not hasattr(bpy.types.TimelineMarker, "m2nla_muted")


def test_marker_segments():
    scene = bpy.context.scene
    scene.timeline_markers.new("Walk", frame=2)
    scene.timeline_markers.new("Run", frame=4)
    segments = addon.get_marker_segments(scene)
    assert [(segment["name"], segment["start"], segment["end"])
            for segment in segments] == [
                ("Walk", 1, 2),
                ("Run", 3, 4),
            ]


def test_shared_action_slot_copy():
    source = bpy.data.actions.new("Shared")
    rig_a = bpy.data.objects.new("RigA", None)
    rig_b = bpy.data.objects.new("RigB", None)
    channelbag_a = addon._ensure_channelbag(source, rig_a)
    channelbag_b = addon._ensure_channelbag(source, rig_b)
    channelbag_a.fcurves.new("location", index=0).keyframe_points.insert(1, 11)
    channelbag_b.fcurves.new("location", index=0).keyframe_points.insert(1, 22)

    destination = bpy.data.actions.new("Destination")
    copied = addon.copy_segment_to_action(
        source,
        destination,
        1,
        1,
        create_boundaries=False,
        datablock=rig_b,
        source_slot=channelbag_b.slot,
    )
    values = [
        point.co.y
        for fcurve in addon._get_fcurves(destination)
        for point in fcurve.keyframe_points
    ]
    assert copied
    assert values == [22.0]


def test_temporary_split_restores_state():
    addon.register()
    scene = bpy.context.scene
    rig = bpy.data.objects.new("ExportRig", None)
    scene.collection.objects.link(rig)
    rig.animation_data_create()

    source = bpy.data.actions.new("ExportSource")
    channelbag = addon._ensure_channelbag(source, rig)
    curve = channelbag.fcurves.new("location", index=0)
    curve.keyframe_points.insert(1, 0)
    curve.keyframe_points.insert(4, 3)
    rig.animation_data.action = source
    rig.animation_data.action_slot = channelbag.slot

    original_start = scene.frame_start
    original_end = scene.frame_end
    action_names_before = set(bpy.data.actions.keys())

    with addon._temporary_nla_split([rig], scene) as result:
        assert result["actual_track_count"] == 2
        assert result["clip_names"] == ["Run", "Walk"]
        assert len(rig.animation_data.nla_tracks) == 2
        assert rig.animation_data.action == source

    assert len(rig.animation_data.nla_tracks) == 0
    assert rig.animation_data.action == source
    assert rig.animation_data.action_slot == channelbag.slot
    assert scene.frame_start == original_start
    assert scene.frame_end == original_end
    assert set(bpy.data.actions.keys()) == action_names_before
    addon.unregister()


if __name__ == "__main__":
    clear_scene()
    test_registration()
    test_marker_segments()
    test_shared_action_slot_copy()
    test_temporary_split_restores_state()
    print("HYPER_NLA_SMOKE_TESTS_OK")
