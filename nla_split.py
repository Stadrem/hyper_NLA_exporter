"""Temporary, non-destructive NLA construction for quick export."""

from contextlib import contextmanager

import bpy

from .action_utils import (
    _get_channelbag,
    _get_fcurves,
    _preserve_static_transforms,
    copy_segment_to_action,
)
from .clips import get_marker_segments

#  Temporary NLA split for export
# ============================================================

def _build_nla_track_for_segment(obj, source_action, source_slot, segment,
                                 track_start, create_boundaries):
    """Create one split Action and its matching NLA Track/Strip.

    Returns a dictionary containing the created datablocks and key count, or
    ``None`` when the source segment has no animated or preserved content.
    """
    action_name = f"{obj.name}_{segment['name']}"
    action = bpy.data.actions.new(name=action_name)
    action.use_fake_user = True

    did_copy = copy_segment_to_action(
        source_action,
        action,
        segment['start'],
        segment['end'],
        create_boundaries=create_boundaries,
        datablock=obj,
        source_slot=source_slot,
    )
    _preserve_static_transforms(
        action,
        obj,
        source_action,
        source_slot=source_slot,
    )

    if not did_copy and not _get_fcurves(action):
        action.use_fake_user = False
        bpy.data.actions.remove(action)
        return None

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


@contextmanager
def _temporary_nla_split(objects, scene):
    """Temporarily split actions into NLA strips by markers for multiple objects.
    Each object gets its own separate Action to avoid slot-sharing conflicts.
    """
    object_states = []
    
    for obj in objects:
        anim = obj.animation_data
        if not anim or not anim.action:
            continue
        object_states.append({
            'obj': obj,
            'anim': anim,
            'original_action': anim.action,
            'original_slot': getattr(anim, 'action_slot', None),
            'existing_track_states': [
                {
                    'track': track,
                    'mute': track.mute,
                    'is_solo': getattr(track, 'is_solo', False),
                    'strip_states': [
                        {
                            'strip': strip,
                            'mute': strip.mute,
                        }
                        for strip in track.strips
                    ],
                }
                for track in anim.nla_tracks
            ],
            'temp_tracks': [],
            'temp_actions': [],
        })

    segments = [seg for seg in get_marker_segments(scene)
                if not getattr(seg['marker'], "m2nla_muted", False)]
    clip_names = set()
    boundary_keys = scene.m2nla_boundary_keys
    split_result = {
        'expected_clip_names': [seg['name'] for seg in segments],
        'clip_names': [],
        'expected_track_count': len(object_states) * len(segments),
        'actual_track_count': 0,
        'objects': [],
    }

    # Backup original scene frame range
    orig_frame_start = scene.frame_start
    orig_frame_end = scene.frame_end
    
    # Calculate max segment length to cover all animations
    max_len = max((seg['length'] for seg in segments), default=1)

    try:
        for state in object_states:
            obj = state['obj']
            anim = state['anim']
            original_action = state['original_action']
            original_slot = state['original_slot']

            # Existing user NLA must not leak into a marker Quick Export.
            # Preserve both controls because a solo track can suppress the
            # temporary tracks even when that existing track is muted.
            for track_state in state['existing_track_states']:
                track = track_state['track']
                track.mute = True
                if hasattr(track, 'is_solo'):
                    track.is_solo = False
                for strip_state in track_state['strip_states']:
                    strip_state['strip'].mute = True

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

        depsgraph = bpy.context.evaluated_depsgraph_get()
        if depsgraph:
            depsgraph.update()
        current_frame = scene.frame_current
        scene.frame_set(current_frame)

        split_result['clip_names'] = sorted(clip_names)
        yield split_result
    finally:
        # Restore scene frame range
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

            for track_state in state['existing_track_states']:
                try:
                    track = track_state['track']
                    track.mute = track_state['mute']
                    if hasattr(track, 'is_solo'):
                        track.is_solo = track_state['is_solo']
                    for strip_state in track_state['strip_states']:
                        strip_state['strip'].mute = strip_state['mute']
                except (ReferenceError, RuntimeError):
                    pass

            anim.action = state['original_action']
            if state['original_slot'] is not None:
                try:
                    anim.action_slot = state['original_slot']
                except Exception:
                    pass


# ============================================================
