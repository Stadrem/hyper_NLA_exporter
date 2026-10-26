"""glTF interpolation regressions for split clips; run in Blender background.

The glTF exporter bakes a property, with a warning each time, when its keys
name more than one interpolation. Split clips used to mix CONSTANT holds,
BEZIER boundary keys and the source interpolation on unchanged motion.
"""

from contextlib import contextmanager
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import hyper_NLA_exporter as addon
from hyper_NLA_exporter.action_utils import _ensure_channelbag, _get_fcurves
from hyper_NLA_exporter.clips import get_marker_segments
from hyper_NLA_exporter.nla_split import _temporary_nla_split


def reset_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action, do_unlink=True)
    scene = bpy.context.scene
    scene.timeline_markers.clear()
    scene.m2nla_start_frame = 1
    scene.m2nla_boundary_keys = True
    return scene


def animated_empty(keys_by_index, interpolation='LINEAR'):
    """An empty keyed on location; *keys_by_index* maps index → keys.

    A key given as ``(frame, value, interpolation)`` overrides the default.
    """
    obj = bpy.data.objects.new('Mover', None)
    bpy.context.scene.collection.objects.link(obj)
    obj.animation_data_create()
    action = bpy.data.actions.new('Source')
    channelbag = _ensure_channelbag(action, obj)
    for index, keys in keys_by_index.items():
        curve = channelbag.fcurves.new('location', index=index)
        for frame, value, *override in keys:
            point = curve.keyframe_points.insert(frame, value)
            point.interpolation = override[0] if override else interpolation
        curve.update()
    obj.animation_data.action = action
    return obj, action


@contextmanager
def split_clips(scene, obj):
    """Yield ``{clip name: split Action}`` while the split exists."""
    with _temporary_nla_split([obj], scene):
        yield {strip.name: strip.action
               for track in obj.animation_data.nla_tracks
               for strip in track.strips}


def interpolations(action):
    by_path = {}
    for curve in _get_fcurves(action):
        by_path.setdefault(curve.data_path, set()).update(
            point.interpolation for point in curve.keyframe_points)
    return by_path


def assert_same_motion(source, action, start, end):
    """Every split curve still follows its source curve over the clip."""
    sources = {(curve.data_path, curve.array_index): curve
               for curve in _get_fcurves(source)}
    for curve in _get_fcurves(action):
        original = sources[(curve.data_path, curve.array_index)]
        for step in range(int((end - start) * 4) + 1):
            frame = start + step * 0.25
            actual = curve.evaluate(frame - start)
            expected = original.evaluate(frame)
            assert abs(actual - expected) < 1e-5, (
                curve.array_index, frame, actual, expected)


def segments(scene):
    return {seg['name']: (seg['start'], seg['end'])
            for seg in get_marker_segments(scene)}


def test_holds_and_boundary_keys_take_the_motion_interpolation():
    scene = reset_scene()
    # x moves in Move only; y never moves. Move starts with a hold before
    # x's first key and Idle is one long hold.
    obj, source = animated_empty({
        0: [(10, 0.0), (20, 3.0)],
        1: [(10, 1.0), (20, 1.0)],
    })
    scene.timeline_markers.new('Move', frame=30)
    scene.timeline_markers.new('Idle', frame=50)
    ranges = segments(scene)
    with split_clips(scene, obj) as clips:
        for name, action in clips.items():
            assert interpolations(action) == {'location': {'LINEAR'}}, (
                name, interpolations(action))
            assert_same_motion(source, action, *ranges[name])


def test_bezier_motion_gets_flat_bezier_holds():
    scene = reset_scene()
    obj, source = animated_empty({0: [(10, 0.0), (20, 3.0)]}, 'BEZIER')
    scene.timeline_markers.new('Move', frame=30)
    ranges = segments(scene)
    with split_clips(scene, obj) as clips:
        action = clips['Move']
        assert interpolations(action) == {'location': {'BEZIER'}}, (
            interpolations(action))
        assert_same_motion(source, action, *ranges['Move'])


def test_real_steps_are_left_alone():
    scene = reset_scene()
    # A CONSTANT jump next to LINEAR motion cannot share one glTF sampler.
    obj, source = animated_empty({0: [
        (1, 0.0, 'LINEAR'), (10, 2.0, 'CONSTANT'), (15, 5.0, 'LINEAR'),
        (20, 6.0, 'LINEAR'),
    ]})
    scene.timeline_markers.new('Step', frame=20)
    ranges = segments(scene)
    with split_clips(scene, obj) as clips:
        action = clips['Step']
        kinds = [point.interpolation
                 for point in _get_fcurves(action)[0].keyframe_points]
        assert kinds[:-1] == ['LINEAR', 'CONSTANT', 'LINEAR'], kinds
        assert_same_motion(source, action, *ranges['Step'])


def run_all():
    addon.register()
    try:
        for name, test in list(globals().items()):
            if name.startswith('test_') and callable(test):
                test()
                print('PASS', name)
    finally:
        addon.unregister()
    print('HYPER_NLA_GLTF_INTERPOLATION_TESTS_OK')


if __name__ == '__main__':
    run_all()
