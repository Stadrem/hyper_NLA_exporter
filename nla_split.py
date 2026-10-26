"""Temporary, non-destructive NLA construction for quick export."""

from contextlib import contextmanager

import bpy

from .action_utils import (
    _action_is_empty,
    _get_channelbag,
    _get_fcurves,
    _preserve_static_transforms,
    copy_segment_to_action,
    mark_generated_action,
    unify_flat_interpolation,
)
from .clips import get_marker_segments

#  Temporary NLA split for export
# ============================================================


def _iter_animation_datablocks(objects, include_shape_keys=True):
    """Yield unique animation owners, including mesh Shape Key datablocks.

    The caller supplies the export's complete object scope. Shared mesh data
    can appear on several objects, but its Key animation must be split once.
    """
    seen = set()
    for obj in objects:
        candidates = [obj]
        if include_shape_keys and getattr(obj, 'type', None) == 'MESH':
            shape_keys = getattr(obj.data, 'shape_keys', None)
            if shape_keys is not None:
                candidates.append(shape_keys)
        for datablock in candidates:
            pointer = datablock.as_pointer()
            if pointer not in seen:
                seen.add(pointer)
                yield datablock

def _fit_strip_to_segment(strip, segment):
    """Pin *strip* to the full segment length.

    ``strips.new`` derives the strip range from the Action's *keyed* range.
    With Create Boundary Keys off that range starts at the first real key
    instead of the segment start, so the clip would be exported both too
    short and shifted in time. Declaring the used Action range explicitly
    makes Blender recompute the strip bounds from the segment, and is a
    no-op when boundary keys already sit on both ends.
    """
    action_end = float(max(int(segment['length']), 1) - 1)
    try:
        strip.action_frame_start = 0.0
        strip.action_frame_end = action_end
    except (AttributeError, RuntimeError, TypeError):
        pass


def _fit_action_to_segment(action, segment):
    """Declare the full segment as the split Action's manual frame range.

    The glTF exporter's ACTIONS mode samples each Action over its own frame
    range, not over the strip. Without boundary keys the keyed range starts
    at the first real key, so a GLB clip came out shorter than its marker
    segment and shifted to that key. A manual range pins every exporter and
    ``strips.new`` to the complete clip.
    """
    action.use_frame_range = True
    action.frame_start = 0.0
    action.frame_end = float(max(int(segment['length']), 1) - 1)


def _build_nla_track_for_segment(obj, source_action, source_slot, segment,
                                 track_start, create_boundaries):
    """Create one split Action and its matching NLA Track/Strip.

    Returns a dictionary containing the created datablocks and key count, or
    ``None`` when the source segment has no animated or preserved content.
    """
    action_name = f"{obj.name}_{segment['name']}"
    action = bpy.data.actions.new(name=action_name)
    action.use_fake_user = True
    mark_generated_action(action)

    track = None
    try:
        did_copy = copy_segment_to_action(
            source_action,
            action,
            segment['start'],
            segment['end'],
            create_boundaries=create_boundaries,
            datablock=obj,
            source_slot=source_slot,
        )
        if obj.id_type == 'OBJECT':
            _preserve_static_transforms(
                action,
                obj,
                source_action,
                source_slot=source_slot,
            )
        unify_flat_interpolation(action)

        if not did_copy and not _get_fcurves(action):
            action.use_fake_user = False
            bpy.data.actions.remove(action)
            return None

        _fit_action_to_segment(action, segment)
        channelbag = _get_channelbag(action)
        slot = getattr(channelbag, 'slot', None)
        track = obj.animation_data.nla_tracks.new()
        track.name = segment['name']
        strip = track.strips.new(
            name=segment['name'],
            start=track_start,
            action=action,
        )
        strip.name = segment['name']
        if slot and hasattr(strip, 'action_slot'):
            strip.action_slot = slot
        _fit_strip_to_segment(strip, segment)
        # The default HOLD extends a strip's first pose back to frame 0, so
        # after Markers → NLA every higher track covered the clips below it.
        # Exporters solo one strip and sample only its range, so Quick
        # Export output does not change.
        strip.extrapolation = 'NOTHING'

        key_count = sum(
            len(fcurve.keyframe_points)
            for fcurve in _get_fcurves(action, slot)
        )
        return {
            'action': action,
            'track': track,
            'strip': strip,
            'slot': slot,
            'key_count': key_count,
        }
    except Exception:
        if track is not None:
            obj.animation_data.nla_tracks.remove(track)
        action.use_fake_user = False
        bpy.data.actions.remove(action, do_unlink=True)
        raise


@contextmanager
def _temporary_nla_split(objects, scene, include_shape_keys=True):
    """Temporarily split object and Shape Key actions into matching clips.
    Each animation owner gets a separate Action to avoid slot conflicts.

    *objects* is the export scope. Owners with a non-empty active Action are
    split; every owner in scope has its existing NLA muted, including
    objects and Shape Keys that carry NLA tracks but no active Action, so
    no stale track can leak into the exported takes.
    """
    segments = [seg for seg in get_marker_segments(scene)
                if not getattr(seg['marker'], "m2nla_muted", False)]
    clip_name_set = {seg['name'] for seg in segments}

    object_states = []
    nla_states = []
    for obj in _iter_animation_datablocks(objects, include_shape_keys):
        anim = obj.animation_data
        if not anim:
            continue
        if anim.nla_tracks:
            nla_states.append({
                'anim': anim,
                'track_states': [
                    {
                        'track': track,
                        'mute': track.mute,
                        'is_solo': getattr(track, 'is_solo', False),
                        'strip_states': [
                            {
                                'strip': strip,
                                'name': strip.name,
                                'mute': strip.mute,
                            }
                            for strip in track.strips
                        ],
                    }
                    for track in anim.nla_tracks
                ],
            })
        if _action_is_empty(anim.action):
            continue
        object_states.append({
            'obj': obj,
            'anim': anim,
            'original_action': anim.action,
            'original_slot': getattr(anim, 'action_slot', None),
            'use_nla': anim.use_nla,
            'temp_tracks': [],
            'temp_actions': [],
        })

    clip_names = set()
    boundary_keys = scene.m2nla_boundary_keys
    split_result = {
        'expected_clip_names': [seg['name'] for seg in segments],
        'clip_names': [],
        'expected_track_count': len(object_states) * len(segments),
        'actual_track_count': 0,
        'objects': [],
    }

    # Backup original scene frame range and playhead
    orig_frame_start = scene.frame_start
    orig_frame_end = scene.frame_end
    orig_frame_current = scene.frame_current
    
    # Calculate max segment length to cover all animations
    max_len = max((seg['length'] for seg in segments), default=1)
    first_clip_start = int(getattr(scene, 'm2nla_start_frame', 1))

    try:
        # Static pose values that _preserve_static_transforms injects come
        # from the last evaluation. Evaluate at First Clip Start before and
        # after muting, so channels driven by the old NLA or by drivers no
        # longer depend on where the playhead happened to sit.
        scene.frame_set(first_clip_start)

        # Existing user NLA must not leak into a marker Quick Export.
        # Preserve both controls because a solo track can suppress the
        # temporary tracks even when that existing track is muted.
        for nla_state in nla_states:
            for track_state in nla_state['track_states']:
                track = track_state['track']
                track.mute = True
                if hasattr(track, 'is_solo'):
                    track.is_solo = False
                for strip_state in track_state['strip_states']:
                    strip = strip_state['strip']
                    strip.mute = True
                    # Strip names are unique per owner, so an existing strip
                    # named like a clip would turn the temporary strip into
                    # "Walk.001". Park it under a free name until restore.
                    if strip.name in clip_name_set:
                        strip.name = "m2nla_parked"

        scene.frame_set(first_clip_start)

        for state in object_states:
            obj = state['obj']
            original_action = state['original_action']
            original_slot = state['original_slot']
            # The FBX exporter samples the temporary tracks. With NLA
            # evaluation off they are ignored and every take came out as a
            # still pose, while the export still reported success.
            state['anim'].use_nla = True

            object_result = {
                'name': obj.name,
                'expected_track_count': len(segments),
                'actual_track_count': 0,
                'clips': [],
            }
            split_result['objects'].append(object_result)

            for seg in segments:
                clip_result = {
                    'name': seg['name'],
                    'source_start': seg['start'],
                    'source_end': seg['end'],
                    'expected_start': 1.0,
                    'expected_end': float(seg['length']),
                    'created': False,
                    'action_empty': True,
                    'strip_empty': True,
                    'track_name': '',
                    'strip_name': '',
                    'actual_start': 0.0,
                    'actual_end': 0.0,
                    'severity': 'WARNING',
                    'message': 'track was not created',
                }
                object_result['clips'].append(clip_result)

                built = _build_nla_track_for_segment(
                    obj,
                    original_action,
                    original_slot,
                    seg,
                    track_start=1,
                    create_boundaries=boundary_keys,
                )
                if built is not None:
                    state['temp_actions'].append(built['action'])
                    state['temp_tracks'].append(built['track'])
                    clip_names.add(seg['name'])
                    strip = built['strip']
                    action_key_count = built['key_count']
                    clip_result.update({
                        'created': True,
                        'action_empty': action_key_count == 0,
                        'strip_empty': (
                            strip.action is None or action_key_count == 0
                        ),
                        'track_name': built['track'].name,
                        'strip_name': strip.name,
                        'actual_start': float(strip.frame_start),
                        'actual_end': float(strip.frame_end),
                    })
                    object_result['actual_track_count'] += 1
                    split_result['actual_track_count'] += 1

            # Keep the original action active. The FBX and glTF exporters
            # temporarily detach it while soloing NLA strips, then restore it.

        # Temporarily set scene range to cover the longest segment from frame 1
        scene.frame_start = 1
        scene.frame_end = max_len

        # The FBX exporter writes every bone's default Lcl Translation and
        # Lcl Rotation from the pose evaluated at the current frame, so the
        # exported file used to depend on where the playhead happened to sit:
        # a consumer that falls back to those defaults showed one clip with
        # another clip's pose. Pin the playhead to the first clip's start so
        # the same scene always produces the same file. frame_set also
        # re-evaluates the depsgraph, making the temporary tracks visible.
        scene.frame_set(first_clip_start)

        split_result['clip_names'] = sorted(clip_names)
        yield split_result
    finally:
        # Restore all animation owners before evaluating the original frame.
        scene.frame_start = orig_frame_start
        scene.frame_end = orig_frame_end

        for state in object_states:
            anim = state['anim']
            for track in reversed(state['temp_tracks']):
                try:
                    anim.nla_tracks.remove(track)
                except (ReferenceError, RuntimeError):
                    pass

            for action in reversed(state['temp_actions']):
                if action.name not in bpy.data.actions:
                    continue
                action.use_fake_user = False
                try:
                    bpy.data.actions.remove(action, do_unlink=True)
                except (ReferenceError, RuntimeError):
                    pass

            anim.action = state['original_action']
            if state['original_slot'] is not None:
                try:
                    anim.action_slot = state['original_slot']
                except Exception:
                    pass
            anim.use_nla = state['use_nla']

        # The temporary strips are gone, so parked names are free again.
        for nla_state in nla_states:
            for track_state in nla_state['track_states']:
                try:
                    track = track_state['track']
                    track.mute = track_state['mute']
                    if hasattr(track, 'is_solo'):
                        track.is_solo = track_state['is_solo']
                    for strip_state in track_state['strip_states']:
                        strip = strip_state['strip']
                        strip.mute = strip_state['mute']
                        if strip.name != strip_state['name']:
                            strip.name = strip_state['name']
                except (ReferenceError, RuntimeError):
                    pass

        try:
            scene.frame_set(orig_frame_current)
        except (ReferenceError, RuntimeError):
            pass


# ============================================================
