"""Blender background regressions for the P0 fixes.

Clip names deliberately run against alphabetical order (Walk, Idle, Run)
so nothing can pass by accident through a sorted name list.
"""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hyper_NLA_exporter as addon
from hyper_NLA_exporter import export_utils
from hyper_NLA_exporter.action_utils import (
    _ensure_channelbag, _get_fcurves, _preserve_static_transforms,
    copy_segment_to_action, merge_nla_to_action,
)
from test_blender_exports import read_accessor, read_glb


def reset_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action, do_unlink=True)
    scene = bpy.context.scene
    scene.timeline_markers.clear()
    scene.m2nla_start_frame = 1
    scene.m2nla_boundary_keys = True
    scene.m2nla_selected_only = True
    scene.m2nla_auto_export = False
    scene.m2nla_open_folder = False
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


def keyed_action(owner, name, keys, path='location', index=0,
                 group='', interpolation='LINEAR', assign=True):
    """Create an Action for *owner* with one keyed channel."""
    action = bpy.data.actions.new(name)
    channelbag = _ensure_channelbag(action, owner)
    if group:
        curve = channelbag.fcurves.new(path, index=index, group_name=group)
    else:
        curve = channelbag.fcurves.new(path, index=index)
    for frame, value in keys:
        point = curve.keyframe_points.insert(frame, value)
        point.interpolation = interpolation
    curve.update()
    if assign:
        owner.animation_data.action = action
        owner.animation_data.action_slot = channelbag.slot
    return action, curve


# ------------------------------------------------------------------
#  P0-8  F-Curve groups survive copying
# ------------------------------------------------------------------

def test_p0_8_copy_keeps_channel_group():
    reset_scene()
    obj = make_empty('GroupProbe')
    source, _curve = keyed_action(
        obj, 'GroupSource', ((1, 0), (10, 5)), group='Object Transforms')
    clip = bpy.data.actions.new('GroupClip')
    assert copy_segment_to_action(source, clip, 1, 10, datablock=obj)
    copied = _get_fcurves(clip)
    assert copied and copied[0].group is not None, copied
    assert copied[0].group.name == 'Object Transforms'


def test_p0_8_merge_keeps_channel_group():
    reset_scene()
    obj = make_empty('MergeProbe')
    source, _curve = keyed_action(
        obj, 'MergeSource', ((1, 0), (10, 5)), group='Hips', assign=False)
    track = obj.animation_data.nla_tracks.new()
    strip = track.strips.new('Walk', 1, source)
    strip.action_slot = source.slots[0]
    merged = merge_nla_to_action(obj, name='MergedGroups')
    curves = _get_fcurves(merged)
    assert curves and curves[0].group is not None, curves
    assert curves[0].group.name == 'Hips'


def test_p0_8_static_transform_keeps_bone_group():
    reset_scene()
    armature = bpy.data.armatures.new('GroupRigData')
    rig = bpy.data.objects.new('GroupRig', armature)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    bone = armature.edit_bones.new('Root')
    bone.tail = (0, 0, 1)
    bpy.ops.object.mode_set(mode='OBJECT')
    rig.pose.bones['Root'].scale = (100, 100, 100)
    source = bpy.data.actions.new('StaticSource')
    destination = bpy.data.actions.new('StaticClip')
    _preserve_static_transforms(destination, rig, source)
    scale_curves = [curve for curve in _get_fcurves(destination)
                    if curve.data_path.endswith('.scale')]
    assert len(scale_curves) == 3, scale_curves
    assert all(curve.group and curve.group.name == 'Root'
               for curve in scale_curves), [c.group for c in scale_curves]


# ------------------------------------------------------------------
#  P0-4 / P0-5  Exporter result checks and atomic replacement
# ------------------------------------------------------------------

class _ExporterOverride:
    """Stand-in for ``bpy`` that swaps only the scene exporters."""

    def __init__(self, fbx=None, gltf=None):
        self.ops = SimpleNamespace(
            export_scene=SimpleNamespace(fbx=fbx, gltf=gltf))

    def __getattr__(self, name):
        return getattr(bpy, name)


def _reporter(filepath):
    messages = []
    operator = SimpleNamespace(
        filepath=str(filepath),
        report=lambda severity, message: messages.append(
            (set(severity), message)),
    )
    return operator, messages


def _write(path, payload):
    Path(path).write_bytes(payload)
    return {'FINISHED'}


def _staging_leftovers(directory):
    return [path for path in Path(directory).iterdir()
            if path.name.startswith('.hyper_nla_export_')]


def _export_scene_with_one_clip():
    scene = reset_scene()
    obj = make_empty('ExportProbe')
    keyed_action(obj, 'ExportSource', ((1, 0), (20, 5)))
    scene.timeline_markers.new('Walk', frame=20)
    return scene


def test_p0_4_5_failed_exporter_keeps_previous_file():
    scene = _export_scene_with_one_clip()
    failures = {
        'cancelled': lambda **kw: {'CANCELLED'},
        'no file': lambda **kw: {'FINISHED'},
        'empty file': lambda **kw: _write(kw['filepath'], b''),
        'raised': lambda **kw: (_ for _ in ()).throw(RuntimeError('boom')),
        # A partial write followed by a cancel must not leak either.
        'partial': lambda **kw: (_write(kw['filepath'], b'half')
                                 and {'CANCELLED'}),
    }
    with tempfile.TemporaryDirectory(prefix='hyper_nla_p0_export_') as tmp:
        for label, run, kind in (
                ('FBX', export_utils._run_fbx_export, 'fbx'),
                ('GLB', lambda op, sc: export_utils._run_glb_export(
                    op, sc, marker_actions=True), 'gltf')):
            target = Path(tmp) / f'previous.{label.lower()}'
            target.write_bytes(b'last good export')
            for reason, exporter in failures.items():
                operator, messages = _reporter(target)
                override = _ExporterOverride(**{kind: exporter})
                with patch.object(export_utils, 'bpy', override):
                    assert run(operator, scene) is False, (label, reason)
                assert target.read_bytes() == b'last good export', (
                    label, reason)
                assert any('ERROR' in severity and label in message
                           for severity, message in messages), (
                    label, reason, messages)
                assert not _staging_leftovers(tmp), (label, reason)


def test_p0_4_5_successful_export_replaces_file():
    scene = _export_scene_with_one_clip()
    with tempfile.TemporaryDirectory(prefix='hyper_nla_p0_export_') as tmp:
        fbx_path = Path(tmp) / 'clips.fbx'
        glb_path = Path(tmp) / 'clips.glb'
        for path in (fbx_path, glb_path):
            path.write_bytes(b'stale')
        operator, messages = _reporter(fbx_path)
        assert export_utils._run_fbx_export(operator, scene), messages
        assert fbx_path.read_bytes().startswith(b'Kaydara FBX Binary')
        operator, messages = _reporter(glb_path)
        assert export_utils._run_glb_export(operator, scene), messages
        assert glb_path.read_bytes()[:4] == b'glTF'
        assert not _staging_leftovers(tmp)


def test_p0_5_auto_export_failure_keeps_previous_file():
    scene = _export_scene_with_one_clip()
    with tempfile.TemporaryDirectory(prefix='hyper_nla_p0_auto_') as tmp:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(tmp) / 'Auto.blend'))
        scene = bpy.context.scene
        scene.m2nla_auto_export = True
        scene.m2nla_export_path = '//Export/'
        target = Path(tmp) / 'Export' / 'Auto.fbx'
        target.parent.mkdir()
        target.write_bytes(b'last good export')

        override = _ExporterOverride(fbx=lambda **kw: {'CANCELLED'})
        with patch.object(export_utils, 'bpy', override):
            try:
                bpy.ops.markernla.quick_export_fbx('EXEC_DEFAULT')
            except RuntimeError as exc:
                # bpy.ops raises when the operator reports an ERROR.
                assert 'exporter returned CANCELLED' in str(exc), exc
            else:
                raise AssertionError('cancelled exporter was not reported')
        assert target.read_bytes() == b'last good export'

        result = bpy.ops.markernla.quick_export_fbx('EXEC_DEFAULT')
        assert result == {'FINISHED'}, result
        assert target.read_bytes().startswith(b'Kaydara FBX Binary')
        assert not _staging_leftovers(target.parent)
        scene.m2nla_auto_export = False


# ------------------------------------------------------------------
#  P0-10 / P0-6  Curve shape at clip boundaries
# ------------------------------------------------------------------

def _source_curve(keys, interpolation='BEZIER', handle_type='AUTO_CLAMPED',
                  name='ShapeSource'):
    action = bpy.data.actions.new(name)
    curve = _ensure_channelbag(action).fcurves.new('location', index=0)
    for frame, value in keys:
        point = curve.keyframe_points.insert(frame, value)
        point.interpolation = interpolation
        point.handle_left_type = handle_type
        point.handle_right_type = handle_type
    curve.update()
    return action, curve


def _copied_curve(source, start, end, boundaries=True):
    clip = bpy.data.actions.new('ShapeClip')
    assert copy_segment_to_action(
        source, clip, start, end, create_boundaries=boundaries)
    return _get_fcurves(clip)[0]


def _max_error(source_curve, copied_curve, start, end, step=0.25,
               clip_start=None):
    """Largest source/copy difference over source frames [start, end].

    The copy is retimed so *clip_start* (default: *start*) is frame 0.
    """
    clip_start = start if clip_start is None else clip_start
    worst = 0.0
    for index in range(int((end - start) / step) + 1):
        frame = start + index * step
        worst = max(worst, abs(
            copied_curve.evaluate(frame - clip_start)
            - source_curve.evaluate(frame)))
    return worst


P0_10_KEYS = ((1, 0), (30, 4), (60, 12), (90, 30))


def test_p0_10_marker_on_auto_handle_key_keeps_shape():
    for handle_type in ('AUTO_CLAMPED', 'AUTO', 'VECTOR', 'ALIGNED', 'FREE'):
        _action, curve = _source_curve(P0_10_KEYS, handle_type=handle_type)
        for boundaries in (True, False):
            # Keys sit exactly on both markers, and on one marker only.
            for start, end in ((30, 60), (30, 75), (15, 60), (1, 30)):
                copied = _copied_curve(_action, start, end, boundaries)
                low, high = start, end
                if not boundaries:
                    # Without boundary keys only the keyed span is exact.
                    keyed = [frame for frame, _ in P0_10_KEYS
                             if start <= frame <= end]
                    low, high = keyed[0], keyed[-1]
                error = _max_error(curve, copied, low, high,
                                   clip_start=start)
                assert error < 1e-4, (handle_type, boundaries,
                                      (start, end), error)


def test_p0_10_untouched_keys_keep_auto_handles():
    action, _curve = _source_curve(
        ((1, 0), (10, 3), (20, 9), (30, 4), (40, 0)))
    copied = _copied_curve(action, 10, 30)
    types = [(point.handle_left_type, point.handle_right_type)
             for point in copied.keyframe_points]
    # Only the keys that lost a neighbour are pinned; the inner key keeps
    # its editable automatic handles.
    assert types[1] == ('AUTO_CLAMPED', 'AUTO_CLAMPED'), types
    assert types[0] == ('FREE', 'FREE') and types[-1] == ('FREE', 'FREE')


def test_p0_10_merge_keeps_partial_strip_shape():
    for scale in (1.0, 2.0):
        scene = reset_scene()
        obj = make_empty('MergeShapeProbe')
        source, curve = _source_curve(P0_10_KEYS, name='MergeShapeSource')
        source.slots[0].target_id_type = 'OBJECT'
        track = obj.animation_data.nla_tracks.new()
        strip = track.strips.new('Idle', 1, source)
        strip.action_slot = source.slots[0]
        strip.action_frame_start = 30
        strip.action_frame_end = 60
        strip.scale = scale
        merged = merge_nla_to_action(obj, name='MergedShape', scene=scene)
        result = _get_fcurves(merged)[0]
        worst = 0.0
        for index in range(int(30 * scale * 4) + 1):
            timeline = 1 + index * 0.25
            expected = curve.evaluate(30 + (timeline - 1) / scale)
            worst = max(worst, abs(result.evaluate(timeline) - expected))
        assert worst < 1e-4, (scale, worst)


EASING_TYPES = ('QUAD', 'CUBIC', 'SINE', 'EXPO', 'CIRC',
                'BACK', 'BOUNCE', 'ELASTIC')


def _easing_curve(interpolation, easing='EASE_IN_OUT'):
    action, curve = _source_curve(
        ((1, 0), (41, 10), (81, -4)), interpolation=interpolation,
        handle_type='AUTO_CLAMPED', name=f'Ease{interpolation}')
    for point in curve.keyframe_points:
        point.easing = easing
        point.back = 2.6
        point.amplitude = 1.7
        point.period = 6.5
    curve.update()
    return action, curve


def test_p0_6_clipped_easing_is_baked_per_frame():
    for interpolation in EASING_TYPES:
        action, curve = _easing_curve(interpolation)
        # Markers inside an easing interval, at either or both ends.
        for start, end in ((1, 21), (21, 41), (21, 61), (11, 31)):
            copied = _copied_curve(action, start, end)
            error = _max_error(curve, copied, start, end, step=1.0)
            assert error < 1e-4, (interpolation, (start, end), error)


def test_p0_6_full_easing_interval_keeps_parameters():
    for interpolation in EASING_TYPES:
        action, curve = _easing_curve(interpolation, easing='EASE_OUT')
        copied = _copied_curve(action, 41, 81)
        assert len(copied.keyframe_points) == 2, interpolation
        first = copied.keyframe_points[0]
        assert (first.interpolation, first.easing) == (
            interpolation, 'EASE_OUT')
        assert abs(first.back - 2.6) < 1e-6
        assert abs(first.amplitude - 1.7) < 1e-6
        assert abs(first.period - 6.5) < 1e-6
        error = _max_error(curve, copied, 41, 81)
        assert error < 1e-4, (interpolation, error)


def test_p0_6_merge_keeps_easing_parameters():
    scene = reset_scene()
    obj = make_empty('MergeEaseProbe')
    source, curve = _easing_curve('ELASTIC')
    track = obj.animation_data.nla_tracks.new()
    strip = track.strips.new('Run', 1, source)
    strip.action_slot = source.slots[0]
    merged = merge_nla_to_action(obj, name='MergedEase', scene=scene)
    result = _get_fcurves(merged)[0]
    first = result.keyframe_points[0]
    assert (abs(first.amplitude - 1.7) < 1e-6
            and abs(first.period - 6.5) < 1e-6
            and abs(first.back - 2.6) < 1e-6), (
        first.back, first.amplitude, first.period)
    # The strip starts at frame 1, so merged and source time coincide.
    assert _max_error(curve, result, 1, 81, clip_start=0) < 1e-4


# ------------------------------------------------------------------
#  P0-9  Clip length without boundary keys
# ------------------------------------------------------------------

P0_9_CLIPS = {'Walk': (1, 60), 'Idle': (61, 100)}


def _sparse_key_scene(boundaries):
    scene = reset_scene()
    scene.m2nla_boundary_keys = boundaries
    obj = make_empty('SparseProbe')
    keyed_action(obj, 'SparseSource',
                 ((10, 1.0), (50, 5.0), (70, 7.0), (90, 9.0)))
    scene.timeline_markers.new('Walk', frame=60)
    scene.timeline_markers.new('Idle', frame=100)
    return scene, obj


def test_p0_9_glb_clip_spans_marker_segment():
    for boundaries in (False, True):
        scene, _obj = _sparse_key_scene(boundaries)
        fps = scene.render.fps / scene.render.fps_base
        with tempfile.TemporaryDirectory(prefix='hyper_nla_p0_9_') as tmp:
            path = Path(tmp) / 'sparse.glb'
            result = bpy.ops.markernla.quick_export_glb(
                'EXEC_DEFAULT', filepath=str(path))
            assert result == {'FINISHED'}, result
            document, binary = read_glb(path)
        animations = {item['name']: item for item in document['animations']}
        assert set(animations) == set(P0_9_CLIPS), list(animations)
        for name, (start, end) in P0_9_CLIPS.items():
            animation = animations[name]
            sampler = animation['samplers'][animation['channels'][0]['sampler']]
            accessor = document['accessors'][sampler['input']]
            expected = (end - start) / fps
            assert abs(accessor['min'][0]) < 1e-4, (boundaries, name, accessor)
            assert abs(accessor['max'][0] - expected) < 1e-4, (
                boundaries, name, accessor, expected)
            times = [row[0] for row in read_accessor(
                document, binary, sampler['input'])]
            assert abs(times[0]) < 1e-4 and abs(times[-1] - expected) < 1e-4


def test_p0_9_fbx_clip_spans_marker_segment():
    scene, _obj = _sparse_key_scene(False)
    with tempfile.TemporaryDirectory(prefix='hyper_nla_p0_9_') as tmp:
        path = Path(tmp) / 'sparse.fbx'
        result = bpy.ops.markernla.quick_export_fbx(
            'EXEC_DEFAULT', filepath=str(path))
        assert result == {'FINISHED'}, result
        reset_scene()
        assert bpy.ops.import_scene.fbx(filepath=str(path)) == {'FINISHED'}
    for name, (start, end) in P0_9_CLIPS.items():
        action = bpy.data.actions[f'SparseProbe|{name}']
        assert tuple(action.frame_range) == (1.0, float(end - start + 1)), (
            name, tuple(action.frame_range))


# ------------------------------------------------------------------
#  P0-1 / P0-3 / P0-7  Existing NLA during the temporary split
# ------------------------------------------------------------------

def _add_track(owner, track_name, strip_name, action, frame=1):
    track = owner.animation_data.nla_tracks.new()
    track.name = track_name
    strip = track.strips.new(strip_name, frame, action)
    strip.action_slot = action.slots[0]
    return track, strip


def _walk_idle_markers(scene):
    scene.timeline_markers.new('Walk', frame=10)
    scene.timeline_markers.new('Idle', frame=20)


def _nla_only_scene():
    """A mover with an active Action beside owners that only have NLA."""
    scene = reset_scene()
    _walk_idle_markers(scene)
    mover = make_empty('Mover')
    keyed_action(mover, 'MoverSource', ((1, 0), (10, 9), (20, 19)))

    nla_only = make_empty('NlaOnly')
    legacy, _ = keyed_action(nla_only, 'LegacyMove', ((1, 0), (20, 5)),
                             index=2, assign=False)
    nla_track, _ = _add_track(nla_only, 'LegacyTrack', 'LegacyStrip', legacy)
    nla_track.is_solo = True

    bpy.ops.mesh.primitive_cube_add()
    face = bpy.context.object
    face.name = 'Face'
    face.shape_key_add(name='Basis')
    face.shape_key_add(name='Smile').data[0].co.z += 1.0
    keys = face.data.shape_keys
    keys.animation_data_create()
    legacy_face, _ = keyed_action(
        keys, 'LegacyFaceAction', ((1, 0.0), (20, 1.0)),
        path='key_blocks["Smile"].value', assign=False)
    face_track, _ = _add_track(keys, 'LegacyFace', 'LegacyFaceStrip',
                               legacy_face)
    for obj in (mover, nla_only, face):
        obj.select_set(True)
    return scene, mover, nla_track, face_track


def test_p0_1_nla_only_owners_are_muted_and_restored():
    scene, _mover, nla_track, face_track = _nla_only_scene()
    scope = export_utils._get_export_scope(bpy.context)
    with addon._temporary_nla_split(scope, scene) as result:
        assert result['clip_names'] == ['Idle', 'Walk'], result
        for track in (nla_track, face_track):
            assert track.mute and not track.is_solo, track.name
            assert all(strip.mute for strip in track.strips), track.name
    assert not nla_track.mute and nla_track.is_solo
    assert not face_track.mute and not face_track.is_solo
    assert not any(strip.mute for track in (nla_track, face_track)
                   for strip in track.strips)


def test_p0_1_quick_exports_skip_nla_only_owners():
    with tempfile.TemporaryDirectory(prefix='hyper_nla_p0_1_') as tmp:
        _scene, _mover, nla_track, face_track = _nla_only_scene()
        glb_path = Path(tmp) / 'nla_only.glb'
        result = bpy.ops.markernla.quick_export_glb(
            'EXEC_DEFAULT', filepath=str(glb_path))
        assert result == {'FINISHED'}, result
        document, _binary = read_glb(glb_path)
        names = [animation['name'] for animation in document['animations']]
        assert sorted(names) == ['Idle', 'Walk'], names
        for animation in document['animations']:
            animated = {document['nodes'][channel['target']['node']]['name']
                        for channel in animation['channels']}
            assert animated == {'Mover'}, (animation['name'], animated)
        assert not nla_track.mute and nla_track.is_solo

        # FBX bakes every object in the hierarchy; drop the Shape Key NLA
        # owner from the selection since FBX cannot carry Shape Key clips.
        bpy.data.objects['Face'].select_set(False)
        fbx_path = Path(tmp) / 'nla_only.fbx'
        result = bpy.ops.markernla.quick_export_fbx(
            'EXEC_DEFAULT', filepath=str(fbx_path))
        assert result == {'FINISHED'}, result
        data = fbx_path.read_bytes()
        assert b'Walk' in data and b'Idle' in data
        assert b'Legacy' not in data
        assert not nla_track.mute and nla_track.is_solo


def _strip_name_collision_scene():
    scene = reset_scene()
    _walk_idle_markers(scene)
    mover = make_empty('Mover')
    keyed_action(mover, 'MoverSource', ((1, 0), (10, 9), (20, 19)))
    old, _ = keyed_action(mover, 'OldWalk', ((1, 0), (20, 2)),
                          index=1, assign=False)
    old_track, old_strip = _add_track(mover, 'OldWalkTrack', 'Walk', old)
    return scene, mover, old_track, old_strip


def test_p0_3_existing_strip_named_like_clip():
    scene, mover, old_track, old_strip = _strip_name_collision_scene()
    with addon._temporary_nla_split([mover], scene) as result:
        issues = addon.collect_split_issues(result)
        assert not [issue for issue in issues if issue[0] == 'ERROR'], issues
        strips = {clip['name']: clip['strip_name']
                  for clip in result['objects'][0]['clips']}
        assert strips == {'Walk': 'Walk', 'Idle': 'Idle'}, strips
    assert old_strip.name == 'Walk' and not old_strip.mute
    assert list(mover.animation_data.nla_tracks) == [old_track]

    with tempfile.TemporaryDirectory(prefix='hyper_nla_p0_3_') as tmp:
        for extension in ('fbx', 'glb'):
            operator = getattr(bpy.ops.markernla, f'quick_export_{extension}')
            result = operator('EXEC_DEFAULT',
                              filepath=str(Path(tmp) / f'clash.{extension}'))
            assert result == {'FINISHED'}, (extension, result)
            assert old_strip.name == 'Walk', (extension, old_strip.name)


def _run_convert():
    from hyper_NLA_exporter import operators
    messages = []
    reporter = SimpleNamespace(report=lambda severity, message:
                               messages.append((set(severity), message)))
    result = operators.MARKERNLA_OT_convert.execute(reporter, bpy.context)
    return result, messages


def test_p0_3_convert_reclaims_clip_names():
    scene, mover, _old_track, _old_strip = _strip_name_collision_scene()
    scene.m2nla_clear_nla = True
    result, messages = _run_convert()
    assert result == {'FINISHED'}, messages
    strips = [track.strips[0].name for track in mover.animation_data.nla_tracks]
    assert strips == ['Walk', 'Idle'], strips

    scene, mover, _old_track, old_strip = _strip_name_collision_scene()
    scene.m2nla_clear_nla = False
    result, messages = _run_convert()
    assert result == {'FINISHED'}, messages
    assert old_strip.name == 'Walk'
    assert any('WARNING' in severity and 'Walk.001' in message
               for severity, message in messages), messages


def _driven_rig_scene(first_clip_start):
    scene = reset_scene()
    scene.m2nla_start_frame = first_clip_start
    _walk_idle_markers(scene)
    armature = bpy.data.armatures.new('DrivenRigData')
    rig = bpy.data.objects.new('DrivenRig', armature)
    scene.collection.objects.link(rig)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    armature.edit_bones.new('Root').tail = (0, 0, 1)
    bpy.ops.object.mode_set(mode='OBJECT')
    rig.animation_data_create()
    bone_path = 'pose.bones["Root"]'
    keyed_action(rig, 'RigSource', ((1, 0), (20, 4)),
                 path=f'{bone_path}.location', index=0)
    # Only the old NLA animates location.y; a driver animates scale.x.
    old, _ = keyed_action(rig, 'RigOldNLA', ((1, 2), (100, 12)),
                          path=f'{bone_path}.location', index=1,
                          assign=False)
    _add_track(rig, 'OldTrack', 'OldStrip', old)
    driver = rig.driver_add(f'{bone_path}.scale', 0).driver
    driver.type = 'SCRIPTED'
    driver.expression = '1 + frame / 10'
    return scene, rig


def _injected_values(scene, rig):
    values = {}
    with addon._temporary_nla_split([rig], scene):
        for track in rig.animation_data.nla_tracks:
            if track.name not in {'Walk', 'Idle'}:
                continue
            for curve in _get_fcurves(track.strips[0].action):
                if curve.data_path.endswith(('.scale', '.location')):
                    key = (track.name, curve.data_path, curve.array_index)
                    values[key] = curve.evaluate(0)
    return values


def test_p0_7_static_values_ignore_playhead():
    first_clip_start = 5
    results = []
    for playhead in (50, 80):
        scene, rig = _driven_rig_scene(first_clip_start)
        scene.frame_set(playhead)
        results.append(_injected_values(scene, rig))
        assert scene.frame_current == playhead
    assert results[0] == results[1], results
    values = results[0]
    for clip in ('Walk', 'Idle'):
        scale = values[(clip, 'pose.bones["Root"].scale', 0)]
        assert abs(scale - (1 + first_clip_start / 10)) < 1e-5, values
        old_nla_y = 2 + (first_clip_start - 1) * 10 / 99
        location_y = values[(clip, 'pose.bones["Root"].location', 1)]
        assert abs(location_y - old_nla_y) < 1e-4, values


# ------------------------------------------------------------------
#  P0-2  Markers sharing one frame
# ------------------------------------------------------------------

class _RecordingLayout:
    """Minimal UILayout stand-in that records label text."""

    def __init__(self, labels):
        self.labels = labels

    def label(self, text='', **_kwargs):
        self.labels.append(text)

    def __getattr__(self, _name):
        return lambda *args, **kwargs: _RecordingLayout(self.labels)


def _panel_labels():
    from hyper_NLA_exporter.ui import MARKERNLA_PT_panel
    labels = []
    MARKERNLA_PT_panel.draw(
        SimpleNamespace(layout=_RecordingLayout(labels)), bpy.context)
    return labels


def _shared_frame_errors():
    return [message for severity, message
            in addon.collect_export_issues(bpy.context, 'GLB')
            if severity == 'ERROR' and 'share a frame' in message]


def test_p0_2_markers_on_one_frame_are_reported():
    scene = reset_scene()
    mover = make_empty('Mover')
    keyed_action(mover, 'MoverSource', ((1, 0), (30, 29)))
    scene.timeline_markers.new('Walk', frame=10)
    idle = scene.timeline_markers.new('Idle', frame=20)
    run = scene.timeline_markers.new('Run', frame=20)
    # get_marker_segments still yields one clip per frame ...
    assert len(addon.get_marker_segments(scene)) == 2
    # ... so the clip that disappears must block export and show in the UI.
    errors = _shared_frame_errors()
    assert len(errors) == 1 and '20' in errors[0], errors
    assert 'Idle' in errors[0] and 'Run' in errors[0], errors
    assert any('Frame 20' in text and 'Idle' in text and 'Run' in text
               for text in _panel_labels()), _panel_labels()

    result, messages = _run_convert()
    assert result == {'CANCELLED'}, messages
    assert not mover.animation_data.nla_tracks

    # A muted twin can still swallow the unmuted clip, so it stays an error.
    idle.m2nla_muted = True
    assert _shared_frame_errors()
    run.m2nla_muted = True
    assert not _shared_frame_errors()
    assert not any('Frame 20' in text for text in _panel_labels())


# ------------------------------------------------------------------
#  P0-11  Converted strips do not hold over lower tracks
# ------------------------------------------------------------------

P0_11_CLIPS = {'Walk': (1, 20), 'Idle': (21, 40), 'Run': (41, 60)}


def _frame_ramp_scene():
    """location.x equals the frame number, split into three clips."""
    scene = reset_scene()
    mover = make_empty('Ramp')
    keyed_action(mover, 'RampSource', ((1, 1.0), (100, 100.0)))
    for name, (_start, end) in P0_11_CLIPS.items():
        scene.timeline_markers.new(name, frame=end)
    return scene, mover


def test_p0_11_converted_clips_play_in_sequence():
    scene, mover = _frame_ramp_scene()
    result, messages = _run_convert()
    assert result == {'FINISHED'}, messages
    assert mover.animation_data.action is None
    tracks = mover.animation_data.nla_tracks
    assert [track.name for track in tracks] == list(P0_11_CLIPS)
    assert all(track.strips[0].extrapolation == 'NOTHING' for track in tracks)
    for frame in (5, 15, 25, 35, 45, 55):
        scene.frame_set(frame)
        assert abs(mover.location.x - frame) < 1e-4, (frame, mover.location.x)


def test_p0_11_quick_export_strips_unaffected():
    scene, _mover = _frame_ramp_scene()
    with tempfile.TemporaryDirectory(prefix='hyper_nla_p0_11_') as tmp:
        path = Path(tmp) / 'ramp.glb'
        result = bpy.ops.markernla.quick_export_glb(
            'EXEC_DEFAULT', filepath=str(path))
        assert result == {'FINISHED'}, result
        document, binary = read_glb(path)
    animations = {item['name']: item for item in document['animations']}
    assert set(animations) == set(P0_11_CLIPS), list(animations)
    for name, (start, end) in P0_11_CLIPS.items():
        animation = animations[name]
        channel = next(channel for channel in animation['channels']
                       if channel['target']['path'] == 'translation')
        sampler = animation['samplers'][channel['sampler']]
        values = read_accessor(document, binary, sampler['output'])
        assert abs(values[0][0] - start) < 1e-4, (name, values[0])
        assert abs(values[-1][0] - end) < 1e-4, (name, values[-1])


def run_all():
    addon.register()
    try:
        for name, test in list(globals().items()):
            if name.startswith('test_') and callable(test):
                test()
                print('PASS', name)
    finally:
        addon.unregister()
    print('HYPER_NLA_P0_REGRESSION_TESTS_OK')


if __name__ == '__main__':
    run_all()
