"""Blender 5.1 Action, Slot, Channelbag, and NLA merge helpers."""

from bisect import bisect_left
from math import ceil, floor

import bpy
from bpy_extras import anim_utils


# ============================================================
#  Generated-Action bookkeeping
# ============================================================
#
# Every Action this addon creates is tagged, so the cleanup paths can drop a
# fake user from their own output without ever touching an Action the user
# authored by hand.

_GENERATED_ACTION_TAG = "m2nla_generated"


def mark_generated_action(action):
    """Tag *action* as created by this addon."""
    action[_GENERATED_ACTION_TAG] = True


def is_generated_action(action):
    """Return True when *action* was created by this addon."""
    return bool(action.get(_GENERATED_ACTION_TAG, False))


def release_generated_action(action):
    """Drop the fake user only from an Action this addon created.

    A user-authored Action keeps its fake user, so removing NLA tracks can
    never delete animation this addon did not generate.
    """
    if action is not None and is_generated_action(action):
        action.use_fake_user = False


# ============================================================
#  Layered Action helpers  (Blender 5.1)
# ============================================================
#
# Blender 5.x animation hierarchy:
#   Action → Slots
#   Action → Layers → Strips (KeyframeStrip) → Channelbag → FCurves

def _get_channelbag(action, slot=None):
    """Return the first Channelbag for *slot* (or the first found)."""
    for layer in action.layers:
        for strip in layer.strips:
            if hasattr(strip, "channelbags"):
                for cb in strip.channelbags:
                    cb_slot = getattr(cb, 'slot',
                                      getattr(cb, 'action_slot', None))
                    cb_handle = getattr(cb, 'slot_handle', None)
                    slot_handle = getattr(slot, 'handle', None)
                    if (slot is None or cb_slot == slot
                            or (slot_handle is not None
                                and cb_handle == slot_handle)):
                        return cb
    return None


def _get_fcurves(action, slot=None):
    """Return FCurves from *action* via its channelbag."""
    cb = _get_channelbag(action, slot)
    return list(cb.fcurves) if cb is not None else []


def _action_is_empty(action):
    """True when *action* holds no F-Curves in any slot or channelbag.

    Such an Action contributes nothing to an export. A leftover empty Action
    on a skinned mesh used to make that mesh count as a second animated
    object, which tripped the one-object FBX rule for no reason.
    """
    if action is None:
        return True
    for layer in getattr(action, 'layers', ()):
        for strip in layer.strips:
            for channelbag in getattr(strip, 'channelbags', ()):
                if len(channelbag.fcurves):
                    return False
    # Legacy (pre-layered) Actions keep their curves directly on the Action.
    if len(getattr(action, 'fcurves', ())):
        return False
    return True


def find_action_slot(action, datablock):
    """Return the Slot of *action* made for *datablock*, or None.

    ActionSlots are keyed by identifiers such as "OBRig", not by the
    datablock's bare name. Match the user-facing display name and ID type
    instead of constructing Blender's ID prefix. Blender 5.x calls the name
    ``name_display``; without it no Slot ever matched and every call made
    another "OBRig.001" Slot.
    """
    return next((candidate for candidate in getattr(action, 'slots', ())
                 if getattr(candidate, 'name_display',
                            getattr(candidate, 'display_name', None))
                 == datablock.name
                 and (getattr(candidate, 'target_id_type', None)
                      in {None, datablock.id_type})), None)


def _ensure_channelbag(action, datablock=None):
    """Ensure *action* has Slot → Layer → Strip → Channelbag and return it."""
    slot = None
    if hasattr(action, 'slots'):
        if datablock:
            slot = find_action_slot(action, datablock)
            if not slot:
                if hasattr(action.slots, 'new_for_id'):
                    slot = action.slots.new_for_id(datablock)
                else:
                    slot = action.slots.new(
                        id_type=datablock.id_type,
                        name=datablock.name,
                    )
        else:
            if not action.slots:
                action.slots.new(id_type='OBJECT', name=action.name)
            slot = action.slots[0]
            
    cb = _get_channelbag(action, slot)
    if cb is not None:
        return cb

    if hasattr(anim_utils, "action_ensure_channelbag_for_slot"):
        return anim_utils.action_ensure_channelbag_for_slot(action, slot)

    if not action.layers:
        action.layers.new(name="Layer")
    layer = action.layers[0]

    if not layer.strips:
        layer.strips.new(type='KEYFRAME')
    strip = layer.strips[0]

    if not strip.channelbags:
        strip.channelbag_add(slot)
    return strip.channelbags[0]


def _new_fcurve(channelbag, data_path, index, group_name=""):
    """Create an F-Curve in *channelbag*, filed under *group_name*.

    Channelbag ``fcurves.new`` takes ``group_name``. The legacy
    ``action_group`` keyword raises TypeError there, and the old fallback
    for that error silently dropped every channel group.
    """
    if group_name:
        return channelbag.fcurves.new(
            data_path=data_path, index=index, group_name=group_name)
    return channelbag.fcurves.new(data_path=data_path, index=index)


# ============================================================

#  Action splitting / merging
# ============================================================

def _lerp_point(a, b, factor):
    """Linearly interpolate two 2D points."""
    return (
        a[0] + (b[0] - a[0]) * factor,
        a[1] + (b[1] - a[1]) * factor,
    )


def _split_bezier(points, factor):
    """Split a cubic Bezier and return its left and right control points."""
    p0, p1, p2, p3 = points
    p01 = _lerp_point(p0, p1, factor)
    p12 = _lerp_point(p1, p2, factor)
    p23 = _lerp_point(p2, p3, factor)
    p012 = _lerp_point(p01, p12, factor)
    p123 = _lerp_point(p12, p23, factor)
    point = _lerp_point(p012, p123, factor)
    return (
        (p0, p01, p012, point),
        (point, p123, p23, p3),
    )


def _bezier_frame_parameter(points, frame):
    """Return the cubic parameter whose X coordinate matches *frame*."""
    low = 0.0
    high = 1.0
    for _iteration in range(48):
        factor = (low + high) * 0.5
        left, _right = _split_bezier(points, factor)
        x = left[3][0]
        if x < frame:
            low = factor
        else:
            high = factor
    return (low + high) * 0.5


def _bezier_subsegment(points, start_factor, end_factor):
    """Return control points for a trimmed portion of a cubic Bezier."""
    if start_factor <= 0.0:
        right = points
    else:
        _left, right = _split_bezier(points, start_factor)

    if end_factor >= 1.0:
        return right

    remaining = 1.0 - start_factor
    relative_end = ((end_factor - start_factor) / remaining
                    if remaining > 1e-12 else 1.0)
    left, _right = _split_bezier(right, relative_end)
    return left


# Handle types Blender recomputes from the neighbouring keys on update().
_NEIGHBOR_HANDLE_TYPES = {'AUTO', 'AUTO_CLAMPED', 'VECTOR'}


def _copy_key_shape(src_kp, dst_kp):
    """Copy interpolation and easing parameters of one keyframe."""
    dst_kp.interpolation = src_kp.interpolation
    dst_kp.easing = src_kp.easing
    dst_kp.back = src_kp.back
    dst_kp.amplitude = src_kp.amplitude
    dst_kp.period = src_kp.period


def _freeze_source_handles(dst_kp, src_kp, map_frame):
    """Pin *dst_kp* to the handles *src_kp* has inside its original curve.

    AUTO, AUTO_CLAMPED, and VECTOR handles are derived from the adjacent
    keys. Once a clip drops one of those neighbours, ``update()`` would
    rebuild the handles from the remaining keys and bend the clip. FREE
    handles keep the exact source coordinates; *map_frame* converts a
    source frame into the destination's time.
    """
    dst_kp.handle_left_type = 'FREE'
    dst_kp.handle_right_type = 'FREE'
    dst_kp.handle_left = (map_frame(src_kp.handle_left[0]),
                          src_kp.handle_left[1])
    dst_kp.handle_right = (map_frame(src_kp.handle_right[0]),
                           src_kp.handle_right[1])


def _same_neighbor(a, b, epsilon=1e-6):
    """Compare two optional neighbour frames or ``(frame, value)`` keys."""
    if a is None or b is None:
        return a is b
    if not isinstance(a, tuple):
        a, b = (a,), (b,)
    return all(abs(x - y) <= epsilon for x, y in zip(a, b))


def _preserve_clipped_curve_shape(src_fc, dst_fc, copied_points, offset):
    """Preserve source interpolation when segment boundaries cut a curve.

    For Bezier curves this trims the original cubic with de Casteljau's
    algorithm and assigns the exact new boundary handles. This avoids the
    curve distortion caused by inserting a value-only boundary key.

    Easing interpolations (QUAD, SINE, BACK, ELASTIC, ...) are equations
    over the whole key interval, so a trimmed interval cannot reuse them;
    it is baked at the one-frame export rate instead. A copied key whose
    automatic handles depended on a neighbour the clip dropped is frozen to
    its source handles, even when a marker sits exactly on that key.
    """
    if len(copied_points) < 2:
        return

    source_keys = list(src_fc.keyframe_points)
    epsilon = 1e-6

    # FAST insertion can relocate the RNA wrappers for earlier points. Rebind
    # every source frame to the actual destination point after all inserts.
    # keyframe_points stay sorted by frame, so a binary search replaces the
    # per-point linear scan that made this quadratic on dense curves.
    destination_keys = list(dst_fc.keyframe_points)
    if not destination_keys:
        return
    destination_frames = [point.co[0] for point in destination_keys]
    rebound_points = []
    for source_frame, _stale_point in copied_points:
        destination_frame = source_frame + offset
        index = bisect_left(destination_frames, destination_frame)
        if index >= len(destination_frames):
            index = len(destination_frames) - 1
        elif index > 0 and (
                abs(destination_frames[index - 1] - destination_frame)
                <= abs(destination_frames[index] - destination_frame)):
            # A tie resolves to the lower index, as the previous min() did.
            index -= 1
        rebound_points.append((source_frame, destination_keys[index]))
    rebound_points.sort(key=lambda item: item[0])

    # Freeze first: a clipped Bezier interval below then overwrites the
    # handle on its trimmed side with the exact de Casteljau coordinates.
    source_frames = [point.co[0] for point in source_keys]
    copied_frames = [frame for frame, _point in rebound_points]
    for position, (frame, dst_point) in enumerate(rebound_points):
        index = bisect_left(source_frames, frame - epsilon)
        if (index >= len(source_keys)
                or abs(source_frames[index] - frame) > epsilon):
            continue  # A boundary key, not a copy of a source key.
        src_point = source_keys[index]
        if (src_point.handle_left_type not in _NEIGHBOR_HANDLE_TYPES
                and src_point.handle_right_type
                not in _NEIGHBOR_HANDLE_TYPES):
            continue
        source_prev = source_frames[index - 1] if index > 0 else None
        source_next = (source_frames[index + 1]
                       if index + 1 < len(source_frames) else None)
        copied_prev = copied_frames[position - 1] if position > 0 else None
        copied_next = (copied_frames[position + 1]
                       if position + 1 < len(copied_frames) else None)
        if (not _same_neighbor(source_prev, copied_prev)
                or not _same_neighbor(source_next, copied_next)):
            _freeze_source_handles(
                dst_point, src_point, lambda x: x + offset)

    bake_ranges = []
    source_index = 0
    for (frame_a, dst_a), (frame_b, dst_b) in zip(
            rebound_points, rebound_points[1:]):
        source_pair = None
        while (source_index + 1 < len(source_keys) - 1
               and frame_a >= source_keys[source_index + 1].co[0] - epsilon):
            source_index += 1
        if source_index + 1 < len(source_keys):
            source_a = source_keys[source_index]
            source_b = source_keys[source_index + 1]
            if (source_a.co[0] - epsilon <= frame_a
                    and frame_b <= source_b.co[0] + epsilon):
                source_pair = (source_a, source_b)

        if source_pair is None:
            # Before the first or after the last source key, match Blender's
            # FCurve extrapolation instead of inventing a Bezier ease.
            dst_a.interpolation = (
                'LINEAR' if src_fc.extrapolation == 'LINEAR' else 'CONSTANT'
            )
            continue

        source_a, source_b = source_pair
        dst_a.interpolation = source_a.interpolation

        # A complete source interval already has its original handles,
        # handle types, and easing. Only rework it when a marker clips it.
        clips_start = abs(frame_a - source_a.co[0]) > epsilon
        clips_end = abs(frame_b - source_b.co[0]) > epsilon
        if not clips_start and not clips_end:
            continue
        if source_a.interpolation in {'CONSTANT', 'LINEAR'}:
            continue  # Any part of these is still the same interpolation.
        if source_a.interpolation != 'BEZIER':
            dst_a.interpolation = 'LINEAR'
            bake_ranges.append((frame_a, frame_b))
            continue

        points = (
            tuple(source_a.co),
            tuple(source_a.handle_right),
            tuple(source_b.handle_left),
            tuple(source_b.co),
        )
        start_factor = _bezier_frame_parameter(points, frame_a)
        end_factor = _bezier_frame_parameter(points, frame_b)
        _p0, handle_right, handle_left, _p3 = _bezier_subsegment(
            points, start_factor, end_factor)

        # Blender recalculates an AUTO/AUTO_CLAMPED handle pair together.
        # Freeze both sides before assigning the trimmed handles so update()
        # cannot replace the exact coordinates below.
        dst_a.handle_left_type = 'FREE'
        dst_a.handle_right_type = 'FREE'
        dst_b.handle_left_type = 'FREE'
        dst_b.handle_right_type = 'FREE'
        dst_a.handle_right = (
            handle_right[0] + offset,
            handle_right[1],
        )
        dst_b.handle_left = (
            handle_left[0] + offset,
            handle_left[1],
        )

    # Inserting relocates the RNA wrappers used above, so bake last.
    for frame_a, frame_b in bake_ranges:
        for frame in range(floor(frame_a) + 1, ceil(frame_b)):
            if frame_a + epsilon < frame < frame_b - epsilon:
                point = dst_fc.keyframe_points.insert(
                    frame=frame + offset, value=src_fc.evaluate(frame),
                    options={'FAST'})
                point.interpolation = 'LINEAR'


def _curve_is_enabled(fcurve):
    """Whether a channel contributes animation, including its group mute."""
    return not (fcurve.mute or (fcurve.group and fcurve.group.mute))


def _needs_evaluated_copy(fcurve):
    """Modifiers and sampled channels cannot be preserved by copying keys."""
    return bool(fcurve.sampled_points) or any(
        not modifier.mute and (
            not modifier.use_influence or modifier.influence != 0.0)
        for modifier in fcurve.modifiers
    )


def _bake_segment_curve(source, destination, start, end):
    """Bake in source time, then retime to zero for a portable export clip.

    A one-frame step matches the export sampling rate. Include both source
    and clip-relative integer frames, plus original key/sample times, so
    fractional clip starts and short keyed events remain represented.
    Modifier curves require evaluated endpoints even when ordinary boundary
    key creation is disabled: their original keys may be outside the clip.
    """
    frames = {float(start), float(end)}
    frames.update(range(ceil(start), floor(end) + 1))
    frames.update(start + index for index in range(1, floor(end - start) + 1))
    frames.update(point.co[0] for point in source.keyframe_points
                  if start <= point.co[0] <= end)
    frames.update(point.co[0] for point in source.sampled_points
                  if start <= point.co[0] <= end)
    for frame in sorted(frames):
        point = destination.keyframe_points.insert(
            frame=frame - start, value=source.evaluate(frame), options={'FAST'})
        point.interpolation = 'LINEAR'


def copy_segment_to_action(source_action, dst_action, start, end,
                           create_boundaries=True, datablock=None,
                           source_slot=None):
    """Copy keyframes from *source_action* within [start, end] into *dst_action*.

    Keyframes are re-timed so the clip starts at frame 0.
    *datablock* – if given, a destination slot is created/used for this ID.
    *source_slot* selects the correct Channelbag in a shared Layered Action.
    Modifier and sampled curves are baked at one-frame intervals; ordinary
    curves retain their original interpolation and clipped Bezier handles.
    Returns True if any keyframes were added.
    """
    src_fcurves = _get_fcurves(source_action, source_slot)
    if not src_fcurves or end < start:
        return False

    offset = -start
    dst_cb = _ensure_channelbag(dst_action, datablock=datablock)
    has_any = False

    for src_fc in src_fcurves:
        if not _curve_is_enabled(src_fc):
            continue

        bake_evaluated = _needs_evaluated_copy(src_fc)
        if not src_fc.keyframe_points and not bake_evaluated:
            continue

        group_name = src_fc.group.name if src_fc.group else ""

        keys_in_range = [
            kp for kp in src_fc.keyframe_points
            if start <= kp.co[0] <= end
        ]
        need_start_key = create_boundaries and not any(
            abs(kp.co[0] - start) < 0.001 for kp in src_fc.keyframe_points
        )
        need_end_key = create_boundaries and not any(
            abs(kp.co[0] - end) < 0.001 for kp in src_fc.keyframe_points
        )
        if abs(end - start) < 0.001:
            need_end_key = False

        if (not bake_evaluated and not keys_in_range
                and not need_start_key and not need_end_key):
            continue

        new_fc = _new_fcurve(
            dst_cb, src_fc.data_path, src_fc.array_index, group_name)

        new_fc.extrapolation = src_fc.extrapolation
        new_fc.auto_smoothing = src_fc.auto_smoothing
        if bake_evaluated:
            _bake_segment_curve(src_fc, new_fc, start, end)
            new_fc.update()
            has_any = True
            continue

        fc_has = False
        copied_points = []

        if need_start_key:
            val = src_fc.evaluate(start)
            kp = new_fc.keyframe_points.insert(frame=0, value=val,
                                                options={'FAST'})
            copied_points.append((start, kp))
            fc_has = True

        for src_kp in keys_in_range:
            f = src_kp.co[0] + offset
            new_kp = new_fc.keyframe_points.insert(
                frame=f, value=src_kp.co[1], options={'FAST'})
            _copy_key_shape(src_kp, new_kp)
            new_kp.handle_left_type  = src_kp.handle_left_type
            new_kp.handle_right_type = src_kp.handle_right_type
            new_kp.handle_left  = (src_kp.handle_left[0]  + offset,
                                   src_kp.handle_left[1])
            new_kp.handle_right = (src_kp.handle_right[0] + offset,
                                   src_kp.handle_right[1])
            copied_points.append((src_kp.co[0], new_kp))
            fc_has = True

        if need_end_key:
            val = src_fc.evaluate(end)
            kp = new_fc.keyframe_points.insert(frame=end + offset, value=val,
                                                options={'FAST'})
            copied_points.append((end, kp))
            fc_has = True

        if fc_has:
            _preserve_clipped_curve_shape(
                src_fc, new_fc, copied_points, offset)
            new_fc.update()
            has_any = True
        else:
            dst_cb.fcurves.remove(new_fc)

    return has_any


# Interpolations a glTF sampler can store without baking.
_GLTF_INTERPOLATIONS = {'CONSTANT', 'LINEAR', 'BEZIER'}


def _is_flat_span(point_a, point_b, epsilon=1e-6):
    """Whether the interval from *point_a* to *point_b* holds one value.

    Between two equal values every interpolation, easing included, stays
    on that value; only a Bezier with sloped handles can leave it.
    """
    value = point_a.co[1]
    tolerance = epsilon * max(1.0, abs(value))
    if abs(point_b.co[1] - value) > tolerance:
        return False
    if point_a.interpolation != 'BEZIER':
        return True
    return (abs(point_a.handle_right[1] - value) <= tolerance
            and abs(point_b.handle_left[1] - value) <= tolerance)


def unify_flat_interpolation(action):
    """Give each property one interpolation where only holds differ.

    The glTF exporter bakes a whole property (every array index of one data
    path) as soon as two of its keys name different interpolations, and logs
    a warning each time. Clip copies routinely mix them without changing
    the motion: holds before the first and after the last key are CONSTANT,
    boundary keys are inserted as BEZIER, and the last key's interpolation
    is never evaluated. Hold intervals and last keys take the interpolation
    of the moving intervals, so an unchanged curve exports unbaked. A
    property whose moving intervals already disagree is left as it is.
    """
    groups = {}
    for fcurve in _get_fcurves(action):
        groups.setdefault(fcurve.data_path, []).append(fcurve)

    for fcurves in groups.values():
        flat_spans = []
        moving = set()
        for fcurve in fcurves:
            points = list(fcurve.keyframe_points)
            for point_a, point_b in zip(points, points[1:]):
                if _is_flat_span(point_a, point_b):
                    flat_spans.append((point_a, point_b))
                else:
                    moving.add(point_a.interpolation)
        if len(moving) > 1:
            continue
        target = moving.pop() if moving else 'LINEAR'
        if target not in _GLTF_INTERPOLATIONS:
            continue  # The exporter bakes easing anyway.

        for point_a, point_b in flat_spans:
            point_a.interpolation = target
            if target == 'BEZIER':
                # FREE keeps the handles on the far sides where they are.
                for point in (point_a, point_b):
                    left, right = tuple(point.handle_left), tuple(
                        point.handle_right)
                    point.handle_left_type = 'FREE'
                    point.handle_right_type = 'FREE'
                    point.handle_left = left
                    point.handle_right = right
                value = point_a.co[1]
                point_a.handle_right = (point_a.handle_right[0], value)
                point_b.handle_left = (point_b.handle_left[0], value)
        for fcurve in fcurves:
            if fcurve.keyframe_points:
                fcurve.keyframe_points[-1].interpolation = target
            fcurve.update()


def _collect_merge_clips(objects):
    """Group unmuted NLA strips into clips and lay the clips out in sequence.

    A clip is every strip sharing one strip name across *objects*. Markers
    → NLA names each object's strip after its segment while giving every
    object its own Action, so the strip name, not the Action, identifies a
    clip. Hand-built NLA often stacks clips as alternatives on the same
    frames (Yes/No variants); merging those in place overwrote one with the
    other. Each clip keeps its original start unless an earlier clip still
    occupies it, in which case the whole clip, every object's strip
    included, moves to the first free frame. Objects keep their timing
    relative to one another inside a clip.
    """
    clips = {}
    for obj in objects:
        for track in obj.animation_data.nla_tracks:
            if getattr(track, 'mute', False):
                continue
            for strip in track.strips:
                if strip.action is None or getattr(strip, 'mute', False):
                    continue
                clip = clips.get(strip.name)
                if clip is None:
                    clip = clips[strip.name] = {
                        'name': strip.name,
                        'start': strip.frame_start,
                        'end': strip.frame_end,
                        'order': len(clips),
                        'strips': [],
                    }
                clip['start'] = min(clip['start'], strip.frame_start)
                clip['end'] = max(clip['end'], strip.frame_end)
                clip['strips'].append((obj, strip))

    ordered = sorted(clips.values(),
                     key=lambda clip: (clip['start'], clip['order']))
    next_free = None
    for clip in ordered:
        start = clip['start']
        if next_free is not None:
            start = max(start, next_free)
        clip['shift'] = start - clip['start']
        # Markers sit on whole frames; the next clip starts after this one.
        clip['marker'] = ceil(clip['end'] + clip['shift'] - 1e-4)
        next_free = clip['marker'] + 1
    return ordered


def merge_nla_to_action(objects, name="Merged", scene=None):
    """Merge the NLA strips of *objects* into one shared Action.

    *objects* is one datablock or an iterable of them. Each object gets its
    own Slot in the merged Action. Strips are grouped into clips by strip
    name and the clips are placed one after another (see
    ``_collect_merge_clips``), so overlapping alternatives no longer land
    on the same frames.
    *scene* – if given, one timeline marker is created at each clip's end
    frame so the merged Action can later be re-split.
    """
    if isinstance(objects, bpy.types.ID):
        objects = [objects]
    # Sorted by name so clips that start together keep a stable order.
    objects = sorted((obj for obj in objects if obj.animation_data),
                     key=lambda obj: obj.name)
    clips = _collect_merge_clips(objects)
    if not clips:
        return None

    merged = bpy.data.actions.new(name=name)
    merged.use_fake_user = True

    dst_bags = {}
    dst_map = {}
    neighbor_checks = {}
    has_any = False
    # Clipped copies of each strip's Action range. Their keys are read again
    # when handles are pinned below, so they are removed only at the end.
    pieces = []

    try:
        for clip in clips:
            for obj, strip in clip['strips']:
                # -- Map action-local frames to timeline frames ----------
                # NLA strip properties:
                #   strip.frame_start / frame_end  – timeline position
                #   strip.action_frame_start / action_frame_end – range used
                #   strip.scale – time scale factor
                act_start = getattr(strip, 'action_frame_start', 0.0)
                act_end   = getattr(strip, 'action_frame_end', act_start)
                scale     = getattr(strip, 'scale', 1.0)
                if scale == 0:
                    scale = 1.0
                timeline_start = strip.frame_start + clip['shift']

                # Copy the used range the way clip export does: boundary keys
                # on both ends, holds that follow the FCurve extrapolation,
                # trimmed Bezier and easing intervals. Raw keys let a curve
                # whose keys end early ease into the next clip's first key
                # instead of holding its last value until the strip ends.
                piece = bpy.data.actions.new(name="m2nla_merge_piece")
                pieces.append(piece)
                if not copy_segment_to_action(
                        strip.action, piece, act_start, act_end,
                        create_boundaries=True, datablock=obj,
                        source_slot=getattr(strip, 'action_slot', None)):
                    continue

                # Piece frames start at 0 on the strip's first frame:
                #   timeline_frame = strip.frame_start + clip shift
                #                  + piece_frame * scale
                def to_timeline(frame, start=timeline_start, factor=scale):
                    return start + frame * factor

                for src_fc in _get_fcurves(piece):
                    src_points = list(src_fc.keyframe_points)
                    if not src_points:
                        continue

                    key = (obj.as_pointer(), src_fc.data_path,
                           src_fc.array_index)
                    group_name = src_fc.group.name if src_fc.group else ""

                    if key not in dst_map:
                        dst_cb = dst_bags.get(obj.as_pointer())
                        if dst_cb is None:
                            dst_cb = dst_bags[obj.as_pointer()] = (
                                _ensure_channelbag(merged, datablock=obj))
                        dst_map[key] = _new_fcurve(
                            dst_cb, src_fc.data_path, src_fc.array_index,
                            group_name)

                    dst_fc = dst_map[key]

                    for index, src_kp in enumerate(src_points):
                        f = to_timeline(src_kp.co[0])
                        new_kp = dst_fc.keyframe_points.insert(
                            frame=f, value=src_kp.co[1], options={'FAST'})
                        _copy_key_shape(src_kp, new_kp)
                        new_kp.handle_left_type  = src_kp.handle_left_type
                        new_kp.handle_right_type = src_kp.handle_right_type
                        new_kp.handle_left  = (
                            to_timeline(src_kp.handle_left[0]),
                            src_kp.handle_left[1])
                        new_kp.handle_right = (
                            to_timeline(src_kp.handle_right[0]),
                            src_kp.handle_right[1])
                        has_any = True

                        if (src_kp.handle_left_type in _NEIGHBOR_HANDLE_TYPES
                                or src_kp.handle_right_type
                                in _NEIGHBOR_HANDLE_TYPES):
                            neighbors = [
                                (to_timeline(point.co[0]), point.co[1])
                                if point is not None else None
                                for point in (
                                    src_points[index - 1]
                                    if index > 0 else None,
                                    src_points[index + 1]
                                    if index + 1 < len(src_points) else None,
                                )
                            ]
                            neighbor_checks.setdefault(key, []).append((
                                f, src_kp, to_timeline, neighbors,
                                scale != 1.0))

                    # The strip ends on this key. Hold it until the next clip
                    # starts rather than easing across the clip boundary.
                    new_kp.interpolation = 'CONSTANT'

        # Automatic handles follow the neighbouring keys. Where an adjacent
        # clip gives a merged key other neighbours, or the strip rescales
        # time, pin the handles the key had inside its strip.
        for key, checks in neighbor_checks.items():
            points = list(dst_map[key].keyframe_points)
            frames = [point.co[0] for point in points]
            for frame, src_kp, to_timeline, neighbors, rescaled in checks:
                index = bisect_left(frames, frame - 1e-6)
                if index >= len(points) or abs(frames[index] - frame) > 1e-6:
                    continue
                merged_neighbors = [
                    tuple(points[index - 1].co) if index > 0 else None,
                    tuple(points[index + 1].co)
                    if index + 1 < len(points) else None,
                ]
                if rescaled or not all(
                        _same_neighbor(a, b)
                        for a, b in zip(neighbors, merged_neighbors)):
                    _freeze_source_handles(points[index], src_kp, to_timeline)

        for fc in dst_map.values():
            fc.update()
    finally:
        for piece in pieces:
            bpy.data.actions.remove(piece)

    if not has_any:
        bpy.data.actions.remove(merged)
        return None

    # -- One timeline marker at each clip's end -------------------
    if scene is not None:
        for clip in clips:
            # Avoid duplicate markers at the same frame
            existing = [m for m in scene.timeline_markers
                        if m.frame == clip['marker']]
            if not existing:
                scene.timeline_markers.new(clip['name'], frame=clip['marker'])

    return merged


# ============================================================
#  Static-transform preservation for NLA export
# ============================================================

def _preserve_static_transforms(dst_action, obj, src_action,
                                source_slot=None):
    """Inject constant keyframes for un-keyframed pose-bone transforms.

    When an action is pushed to NLA and the original is detached, Blender
    evaluates the pose from *rest-pose + NLA strips*.  Any bone transform
    that was set in the pose but **never keyframed** (e.g. a Root bone
    with scale 100) has no FCurve and therefore no NLA contribution –
    it silently reverts to the rest-pose default.

    This function detects such "static" transforms and writes a constant
    keyframe at frame 0 in *dst_action* so the value survives NLA
    evaluation.
    """
    if obj.type != 'ARMATURE':
        return

    # Collect channels already present in the source action
    src_channels = set()
    for fc in _get_fcurves(src_action, source_slot):
        if _curve_is_enabled(fc):
            src_channels.add((fc.data_path, fc.array_index))

    # Collect channels already present in the destination action
    dst_cb = _get_channelbag(dst_action)
    if dst_cb is None:
        dst_cb = _ensure_channelbag(dst_action, datablock=obj)
    dst_channels = set()
    for fc in dst_cb.fcurves:
        dst_channels.add((fc.data_path, fc.array_index))

    def _inject(data_path, index, value, group_name):
        if (data_path, index) in src_channels:
            return  # Already keyframed in source → copy_segment handles it
        if (data_path, index) in dst_channels:
            return  # Already in destination
        fc = _new_fcurve(dst_cb, data_path, index, group_name)
        fc.keyframe_points.insert(frame=0, value=value)
        fc.update()

    for pbone in obj.pose.bones:
        bp = f'pose.bones["{pbone.name}"]'
        grp = pbone.name

        # Scale  (rest default = 1.0)
        for i in range(3):
            if abs(pbone.scale[i] - 1.0) > 1e-6:
                _inject(f'{bp}.scale', i, pbone.scale[i], grp)

        # Location  (rest default = 0.0)
        for i in range(3):
            if abs(pbone.location[i]) > 1e-6:
                _inject(f'{bp}.location', i, pbone.location[i], grp)

        # Rotation
        if pbone.rotation_mode == 'QUATERNION':
            defaults = (1.0, 0.0, 0.0, 0.0)
            for i in range(4):
                if abs(pbone.rotation_quaternion[i] - defaults[i]) > 1e-6:
                    _inject(f'{bp}.rotation_quaternion', i,
                            pbone.rotation_quaternion[i], grp)
        elif pbone.rotation_mode == 'AXIS_ANGLE':
            defaults = (0.0, 0.0, 1.0, 0.0)
            for i in range(4):
                if abs(pbone.rotation_axis_angle[i] - defaults[i]) > 1e-6:
                    _inject(f'{bp}.rotation_axis_angle', i,
                            pbone.rotation_axis_angle[i], grp)
        else:  # Euler
            for i in range(3):
                if abs(pbone.rotation_euler[i]) > 1e-6:
                    _inject(f'{bp}.rotation_euler', i,
                            pbone.rotation_euler[i], grp)


# ============================================================
