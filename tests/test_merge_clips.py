"""NLA → Action clip layout regressions; run in Blender background.

Hand-built NLA often stacks alternative clips (Yes/No variants) on the
same frames, sharing one Action with a Slot per object. Merging used to
lay them over each other and drop a marker at every object's strip end.
"""

from pathlib import Path
import sys
from types import SimpleNamespace

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import hyper_NLA_exporter as addon
from hyper_NLA_exporter import operators
from hyper_NLA_exporter.action_utils import (
    _ensure_channelbag, find_action_slot, merge_nla_to_action,
)


def reset_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action, do_unlink=True)
    scene = bpy.context.scene
    scene.timeline_markers.clear()
    scene.m2nla_start_frame = 1
    scene.m2nla_boundary_keys = True
    scene.m2nla_clear_nla = True
    scene.m2nla_unlink_source = True
    scene.frame_start = 1
    scene.frame_end = 250
    scene.frame_set(1)
    return scene


def make_empty(name):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    obj.animation_data_create()
    return obj


def shared_action(name, keys_by_owner):
    """One Action with a Slot per owner, keyed linearly on location.x."""
    action = bpy.data.actions.new(name)
    for owner, keys in keys_by_owner:
        curve = _ensure_channelbag(action, owner).fcurves.new(
            'location', index=0)
        for frame, value in keys:
            curve.keyframe_points.insert(frame, value).interpolation = 'LINEAR'
        curve.update()
    return action


def add_strip(owner, action, start, action_range):
    track = owner.animation_data.nla_tracks.new()
    track.name = action.name
    strip = track.strips.new(action.name, start, action)
    strip.action_slot = find_action_slot(action, owner)
    strip.action_frame_start, strip.action_frame_end = action_range
    return strip


def run(operator):
    messages = []
    reporter = SimpleNamespace(report=lambda severity, message:
                               messages.append((set(severity), message)))
    return operator.execute(reporter, bpy.context), messages


def markers(scene):
    return sorted((marker.frame, marker.name)
                  for marker in scene.timeline_markers)


def assert_x(scene, obj, expected):
    for frame, value in expected:
        scene.frame_set(frame)
        assert abs(obj.location.x - value) < 1e-4, (
            obj.name, frame, obj.location.x, value)


def _variant_scene():
    """Yes and No variants on the same frames, like LuckBall.blend."""
    scene = reset_scene()
    body = make_empty('Body')
    button = make_empty('Button')
    yes_only = make_empty('YesOnly')
    yes = shared_action('Yes', (
        (body, ((0, 0.0), (19, 10.0))),
        (button, ((5, 1.0), (9, 2.0))),
        (yes_only, ((10, 0.0), (19, 5.0))),
    ))
    no = shared_action('No', (
        (body, ((0, 0.0), (19, -10.0))),
        (button, ((5, -1.0), (9, -2.0))),
    ))
    add_strip(body, yes, 1, (0, 19))
    add_strip(body, no, 1, (0, 19))
    add_strip(button, yes, 6, (5, 9))
    add_strip(button, no, 6, (5, 9))
    add_strip(yes_only, yes, 11, (10, 19))
    return scene, (body, button, yes_only), (yes, no)


def test_overlapping_clips_are_placed_in_sequence():
    scene, objects, sources = _variant_scene()
    body, button, yes_only = objects
    assert [(s.frame_start, s.frame_end) for t in button.animation_data
            .nla_tracks for s in t.strips] == [(6, 10), (6, 10)]

    result, messages = run(operators.MARKERNLA_OT_merge)
    assert result == {'FINISHED'}, messages

    # One marker per clip, at the clip's end, not at each object's strip end.
    assert markers(scene) == [(20, 'Yes'), (40, 'No')], markers(scene)

    merged = body.animation_data.action
    assert merged is not None and merged not in sources
    for obj in objects:
        anim = obj.animation_data
        assert anim.action == merged, (obj.name, anim.action)
        assert anim.action_slot.name_display == obj.name
        assert not anim.nla_tracks
    assert all(source.use_fake_user for source in sources)

    # Yes keeps its frames; No moves by the Yes length, every object alike.
    assert_x(scene, body, ((1, 0.0), (20, 10.0), (21, 0.0), (40, -10.0)))
    assert_x(scene, button, ((6, 1.0), (10, 2.0), (26, -1.0), (30, -2.0)))
    assert_x(scene, yes_only, ((11, 0.0), (20, 5.0)))


def test_overlapping_clips_resplit_into_the_same_clips():
    scene, objects, _sources = _variant_scene()
    assert run(operators.MARKERNLA_OT_merge)[0] == {'FINISHED'}
    result, messages = run(operators.MARKERNLA_OT_convert)
    assert result == {'FINISHED'}, messages
    for obj in objects:
        names = [track.name for track in obj.animation_data.nla_tracks]
        assert names == ['Yes', 'No'], (obj.name, names)


def test_sequential_clips_keep_their_frames():
    scene = reset_scene()
    mover = make_empty('Mover')
    walk = shared_action('Walk', ((mover, ((1, 0.0), (60, 6.0))),))
    idle = shared_action('Idle', ((mover, ((61, 7.0), (100, 1.0))),))
    add_strip(mover, walk, 1, (1, 60))
    add_strip(mover, idle, 61, (61, 100))
    merged = merge_nla_to_action(mover, name='Sequential', scene=scene)
    assert markers(scene) == [(60, 'Walk'), (100, 'Idle')], markers(scene)
    frames = [point.co[0] for point in
              merged.layers[0].strips[0].channelbags[0]
              .fcurves[0].keyframe_points]
    assert frames == [1, 60, 61, 100], frames


def test_merge_makes_one_slot_per_object():
    scene = reset_scene()
    mover = make_empty('Mover')
    action = shared_action('Walk', ((mover, ((1, 0.0), (10, 1.0))),))
    channelbag = _ensure_channelbag(action, mover)
    for index in (1, 2):
        curve = channelbag.fcurves.new('location', index=index)
        curve.keyframe_points.insert(1, 0.0)
        curve.keyframe_points.insert(10, float(index))
    assert len(action.slots) == 1, [slot.identifier for slot in action.slots]
    add_strip(mover, action, 1, (1, 10))
    merged = merge_nla_to_action(mover, name='Slots', scene=scene)
    assert [slot.identifier for slot in merged.slots] == ['OBMover'], (
        [slot.identifier for slot in merged.slots])


def test_markers_to_nla_round_trip_keeps_shared_clips():
    """Markers → NLA gives each object its own Action per clip."""
    scene = reset_scene()
    first = make_empty('First')
    second = make_empty('Second')
    for obj, factor in ((first, 1.0), (second, 2.0)):
        source = shared_action(
            obj.name + 'Source', ((obj, ((1, factor), (40, 40 * factor))),))
        obj.animation_data.action = source
        obj.animation_data.action_slot = source.slots[0]
    scene.timeline_markers.new('Walk', frame=20)
    scene.timeline_markers.new('Idle', frame=40)
    assert run(operators.MARKERNLA_OT_convert)[0] == {'FINISHED'}
    assert first.animation_data.nla_tracks[0].strips[0].action != (
        second.animation_data.nla_tracks[0].strips[0].action)

    scene.timeline_markers.clear()
    result, messages = run(operators.MARKERNLA_OT_merge)
    assert result == {'FINISHED'}, messages
    assert markers(scene) == [(20, 'Walk'), (40, 'Idle')], markers(scene)
    assert first.animation_data.action == second.animation_data.action
    assert_x(scene, first, ((1, 1.0), (20, 20.0), (21, 21.0), (40, 40.0)))
    assert_x(scene, second, ((1, 2.0), (20, 40.0), (21, 42.0), (40, 80.0)))


def run_all():
    addon.register()
    try:
        for name, test in list(globals().items()):
            if name.startswith('test_') and callable(test):
                test()
                print('PASS', name)
    finally:
        addon.unregister()
    print('HYPER_NLA_MERGE_CLIP_TESTS_OK')


if __name__ == '__main__':
    run_all()
