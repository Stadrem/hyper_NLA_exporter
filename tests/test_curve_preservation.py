"""Blender background regression checks for evaluated clip copying."""

from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hyper_NLA_exporter.action_utils import (
    _ensure_channelbag, _get_fcurves, _preserve_static_transforms,
    copy_segment_to_action,
)


def make_curve(keys, path='location', index=0):
    action = bpy.data.actions.new('CurveSource')
    curve = _ensure_channelbag(action).fcurves.new(path, index=index)
    for frame, value in keys:
        point = curve.keyframe_points.insert(frame, value)
        point.interpolation = 'LINEAR'
    curve.update()
    return action, curve


def copy_curve(source, start, end, boundaries=True):
    destination = bpy.data.actions.new('CurveClip')
    copied = copy_segment_to_action(
        source, destination, start, end, create_boundaries=boundaries)
    curves = _get_fcurves(destination)
    return destination, copied, curves[0] if curves else None


def assert_samples(source, destination, start, end):
    for frame in range(start, end + 1):
        actual = destination.evaluate(frame - start)
        expected = source.evaluate(frame)
        assert abs(actual - expected) < 1e-5, (frame, actual, expected)


def test_cycles_outside_original_keys():
    action, curve = make_curve([(1, 1), (5, 5), (9, 1)])
    curve.modifiers.new('CYCLES')
    for boundaries in (True, False):
        _, copied, result = copy_curve(action, 9, 17, boundaries)
        assert copied
        assert_samples(curve, result, 9, 17)
        assert [result.evaluate(frame) for frame in (0, 4, 8)] == [1, 5, 1]
        assert not result.modifiers


def test_noise_source_time_offset():
    action, curve = make_curve([(1, 0), (50, 0)])
    noise = curve.modifiers.new('NOISE')
    noise.strength = 3
    noise.scale = 2
    _, copied, result = copy_curve(action, 20, 30)
    assert copied
    assert_samples(curve, result, 20, 30)


def test_generator_without_keys():
    action, curve = make_curve([])
    generator = curve.modifiers.new('GENERATOR')
    generator.coefficients = (2, 3)
    _, copied, result = copy_curve(action, 10, 15, False)
    assert copied
    assert_samples(curve, result, 10, 15)


def test_fractional_clip_and_sampled_curve():
    action, curve = make_curve([(1, 1), (5, 5), (9, 1)])
    curve.convert_to_samples(1, 9)
    _, copied, result = copy_curve(action, 2.25, 7.75, False)
    assert copied
    for frame in (2.25, 3, 3.25, 4, 5, 6, 7.25, 7.75):
        assert abs(result.evaluate(frame - 2.25) - curve.evaluate(frame)) < 1e-5


def test_muted_channels():
    action, curve = make_curve([(1, 1), (5, 5)])
    curve.mute = True
    _, copied, result = copy_curve(action, 1, 5)
    assert not copied and result is None
    curve.mute = False
    group = _ensure_channelbag(action).groups.new('Muted group')
    curve.group = group
    group.mute = True
    _, copied, result = copy_curve(action, 1, 5)
    assert not copied and result is None


def test_muted_bone_scale_preserves_static_value():
    bpy.ops.object.armature_add()
    rig = bpy.context.object
    bone = rig.pose.bones[0]
    bone.scale[0] = 2.5
    action, curve = make_curve([(1, 5), (5, 10)], bone.path_from_id('scale'))
    curve.mute = True
    destination, copied, _ = copy_curve(action, 1, 5)
    assert not copied
    _preserve_static_transforms(destination, rig, action)
    result = next(fc for fc in _get_fcurves(destination)
                  if fc.data_path == bone.path_from_id('scale') and fc.array_index == 0)
    assert result.evaluate(0) == 2.5


def test_plain_bezier_precision_with_disabled_modifier():
    action, curve = make_curve([(1, 0), (20, 10)])
    first, last = curve.keyframe_points
    for point in (first, last):
        point.interpolation = 'BEZIER'
        point.handle_left_type = 'FREE'
        point.handle_right_type = 'FREE'
    first.handle_right = (5, 8)
    last.handle_left = (15, 2)
    curve.update()
    modifier = curve.modifiers.new('NOISE')
    modifier.mute = True
    _, copied, result = copy_curve(action, 4, 16)
    assert copied
    assert len(result.keyframe_points) == 2, 'Plain Bezier must not be baked'
    for index in range(49):
        frame = 4 + index * 0.25
        assert abs(result.evaluate(frame - 4) - curve.evaluate(frame)) < 2e-4


if __name__ == '__main__':
    for name, test in list(globals().items()):
        if name.startswith('test_') and callable(test):
            test()
            print('PASS', name)
    print('CURVE_PRESERVATION_TESTS_OK')
