"""Regression tests for manual NLA data preservation; run in Blender background."""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import hyper_NLA_exporter as addon
from hyper_NLA_exporter import operators
from hyper_NLA_exporter.action_utils import mark_generated_action


def reset_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)
    scene = bpy.context.scene
    scene.timeline_markers.clear()
    scene.m2nla_start_frame = 1
    scene.m2nla_clear_nla = True
    scene.m2nla_unlink_source = True
    scene.m2nla_boundary_keys = False
    return scene


def make_action(obj, name, frames=(1, 5)):
    action = bpy.data.actions.new(name)
    cb = addon._ensure_channelbag(action, obj)
    fc = cb.fcurves.new('location', index=0)
    for frame in frames:
        fc.keyframe_points.insert(frame, float(frame))
    return action


def make_object(name='ManualProbe', frames=(1, 5)):
    obj = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    anim = obj.animation_data_create()
    source = make_action(obj, name + '_Source', frames)
    anim.action = source
    anim.action_slot = source.slots[0]
    old = make_action(obj, name + '_OldNLA')
    track = anim.nla_tracks.new()
    track.name = 'Existing'
    strip = track.strips.new('Existing', 1, old)
    strip.action_slot = old.slots[0]
    return obj, source, old, track


def execute(operator):
    messages = []
    reporter = SimpleNamespace(report=lambda severity, message:
                               messages.append((severity, message)))
    return operator.execute(reporter, bpy.context), messages


def test_failed_split_keeps_everything():
    scene = reset_scene()
    obj, source, old, track = make_object(frames=(20, 30))
    scene.timeline_markers.new('Empty', frame=5)
    track.mute = True
    track.is_solo = True
    track.strips[0].mute = True
    slot = obj.animation_data.action_slot
    before_actions = set(bpy.data.actions.keys())
    result, _ = execute(operators.MARKERNLA_OT_convert)
    assert result == {'CANCELLED'}
    assert list(obj.animation_data.nla_tracks) == [track]
    assert obj.animation_data.nla_tracks.active == track
    assert track.mute and track.is_solo and track.strips[0].mute
    assert obj.animation_data.action == source
    assert obj.animation_data.action_slot == slot
    assert not source.use_fake_user and not old.use_fake_user
    assert set(bpy.data.actions.keys()) == before_actions


def test_partial_split_rolls_back_all_objects():
    scene = reset_scene()
    first = make_object('First')
    second = make_object('Second', frames=(20, 30))
    scene.timeline_markers.new('Clip', frame=5)
    before_actions = set(bpy.data.actions.keys())
    result, _ = execute(operators.MARKERNLA_OT_convert)
    assert result == {'CANCELLED'}
    for obj, source, old, track in (first, second):
        assert obj.animation_data.action == source
        assert list(obj.animation_data.nla_tracks) == [track]
        assert not source.use_fake_user and not old.use_fake_user
    assert set(bpy.data.actions.keys()) == before_actions


def test_builder_failure_removes_partial_content():
    scene = reset_scene()
    obj, source, old, track = make_object()
    scene.timeline_markers.new('Clip', frame=5)
    before_actions = set(bpy.data.actions.keys())

    def broken_build(*args, **kwargs):
        action = bpy.data.actions.new('InterruptedOutput')
        mark_generated_action(action)
        action.use_fake_user = True
        obj.animation_data.nla_tracks.new()
        raise RuntimeError('Injected construction failure')

    with patch.object(operators, '_build_nla_track_for_segment', broken_build):
        result, _ = execute(operators.MARKERNLA_OT_convert)
    assert result == {'CANCELLED'}
    assert list(obj.animation_data.nla_tracks) == [track]
    assert obj.animation_data.action == source
    assert not old.use_fake_user
    assert set(bpy.data.actions.keys()) == before_actions


def test_successful_conversion_preserves_sources():
    scene = reset_scene()
    obj, source, old, old_track = make_object()
    old_track.name = 'Clip'
    scene.timeline_markers.new('Clip', frame=5)
    result, _ = execute(operators.MARKERNLA_OT_convert)
    assert result == {'FINISHED'}
    assert obj.animation_data.action is None
    assert source.use_fake_user and old.use_fake_user
    tracks = obj.animation_data.nla_tracks
    assert len(tracks) == 1 and tracks[0].name == 'Clip'
    assert tracks[0].strips[0].action.use_fake_user


def test_merge_preserves_authored_actions():
    reset_scene()
    obj, source, old, _ = make_object()
    result, _ = execute(operators.MARKERNLA_OT_merge)
    assert result == {'FINISHED'}
    assert not obj.animation_data.nla_tracks
    assert source.use_fake_user and old.use_fake_user
    assert obj.animation_data.action not in (source, old)


def test_cleanup_survives_save_reload():
    reset_scene()
    obj, source, old, _ = make_object()
    generated = make_action(obj, 'GeneratedToRelease')
    mark_generated_action(generated)
    generated.use_fake_user = True
    track = obj.animation_data.nla_tracks.new()
    track.strips.new('Generated', 1, generated)
    old_name = old.name
    generated_name = generated.name
    source_name = source.name
    result, _ = execute(operators.MARKERNLA_OT_cleanup)
    assert result == {'FINISHED'}
    assert not obj.animation_data.nla_tracks
    assert old.use_fake_user
    assert not generated.use_fake_user and generated.users == 0
    assert obj.animation_data.action == source
    with tempfile.TemporaryDirectory(prefix='hyper_nla_manual_') as tmp:
        path = str(Path(tmp) / 'preservation.blend')
        bpy.ops.wm.save_as_mainfile(filepath=path)
        bpy.ops.wm.open_mainfile(filepath=path)
        assert old_name in bpy.data.actions
        assert source_name in bpy.data.actions
        assert generated_name not in bpy.data.actions


if __name__ == '__main__':
    addon.register()
    tests = [test_failed_split_keeps_everything,
             test_partial_split_rolls_back_all_objects,
             test_builder_failure_removes_partial_content,
             test_successful_conversion_preserves_sources,
             test_merge_preserves_authored_actions,
             test_cleanup_survives_save_reload]
    for test in tests:
        test()
        print('PASS:', test.__name__)
    addon.unregister()
    print('Manual NLA safety: all 6 tests passed')
