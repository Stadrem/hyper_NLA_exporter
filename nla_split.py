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

                # Action name includes object prefix to avoid collisions
                # across different rigs. NLA Track name stays as marker name
                # (that's what glTF uses as the animation clip name).
                action_name = f"{obj.name}_{seg['name']}"
                new_action = bpy.data.actions.new(name=action_name)
                new_action.use_fake_user = True
                state['temp_actions'].append(new_action)

                did_copy = copy_segment_to_action(
                    original_action, new_action, seg['start'], seg['end'],
                    create_boundaries=boundary_keys,
                    datablock=obj,
                    source_slot=original_slot,
                )
                # Inject un-keyframed pose-bone transforms (e.g. Root scale)
                # so they survive NLA rest-pose evaluation.
                _preserve_static_transforms(
                    new_action, obj, original_action,
                    source_slot=original_slot,
                )

                # Check if the action has any content (animated keys or
                # static transforms).
                has_content = did_copy or bool(_get_fcurves(new_action))

                if has_content:
                    dst_cb = _get_channelbag(new_action)
                    slot = getattr(dst_cb, 'slot', None)

                    track = anim.nla_tracks.new()
                    state['temp_tracks'].append(track)
                    track.name = seg['name']
                    strip = track.strips.new(
                        name=seg['name'],
                        start=1,
                        action=new_action,
                    )
                    strip.name = seg['name']
                    if slot and hasattr(strip, 'action_slot'):
                        strip.action_slot = slot
                    clip_names.add(seg['name'])
                    action_key_count = sum(
                        len(fcurve.keyframe_points)
                        for fcurve in _get_fcurves(new_action, slot)
                    )
                    clip_result.update({
                        'created': True,
                        'action_empty': action_key_count == 0,
                        'strip_empty': (
                            strip.action is None or action_key_count == 0
                        ),
                        'track_name': track.name,
                        'strip_name': strip.name,
                        'actual_start': float(strip.frame_start),
                        'actual_end': float(strip.frame_end),
                    })
                    object_result['actual_track_count'] += 1
                    split_result['actual_track_count'] += 1
                else:
                    state['temp_actions'].remove(new_action)
                    new_action.use_fake_user = False
                    bpy.data.actions.remove(new_action)

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

            anim.action = state['original_action']
            if state['original_slot'] is not None:
                try:
                    anim.action_slot = state['original_slot']
                except Exception:
                    pass


# ============================================================
