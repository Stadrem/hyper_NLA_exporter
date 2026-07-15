"""Blender 5.1 Action, Slot, Channelbag, and NLA merge helpers."""

import bpy
from bpy_extras import anim_utils


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


def _ensure_channelbag(action, datablock=None):
    """Ensure *action* has Slot → Layer → Strip → Channelbag and return it."""
    slot = None
    if hasattr(action, 'slots'):
        if datablock:
            # ActionSlots are keyed by identifiers such as "OBRig", not by
            # the datablock's bare name. Match the user-facing display name
            # and ID type instead of constructing Blender's ID prefix.
            slot = next((candidate for candidate in action.slots
                         if (getattr(candidate, 'display_name', None)
                             == datablock.name)
                         and (getattr(candidate, 'target_id_type', None)
                              in {None, datablock.id_type})), None)
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


# ============================================================

#  Action splitting / merging
# ============================================================

def copy_segment_to_action(source_action, dst_action, start, end,
                           create_boundaries=True, datablock=None,
                           source_slot=None):
    """Copy keyframes from *source_action* within [start, end] into *dst_action*.

    Keyframes are re-timed so the clip starts at frame 0.
    *datablock* – if given, a destination slot is created/used for this ID.
    *source_slot* selects the correct Channelbag in a shared Layered Action.
    Returns True if any keyframes were added.
    """
    src_fcurves = _get_fcurves(source_action, source_slot)
    if not src_fcurves:
        return False

    offset = -start
    dst_cb = _ensure_channelbag(dst_action, datablock=datablock)
    has_any = False

    for src_fc in src_fcurves:
        if not src_fc.keyframe_points:
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

        if not keys_in_range and not need_start_key and not need_end_key:
            continue

        try:
            new_fc = dst_cb.fcurves.new(
                data_path=src_fc.data_path,
                index=src_fc.array_index,
                action_group=group_name,
            )
        except TypeError:
            new_fc = dst_cb.fcurves.new(
                data_path=src_fc.data_path,
                index=src_fc.array_index,
            )

        fc_has = False

        if need_start_key:
            val = src_fc.evaluate(start)
            kp = new_fc.keyframe_points.insert(frame=0, value=val,
                                                options={'FAST'})
            kp.interpolation = 'BEZIER'
            fc_has = True

        for src_kp in keys_in_range:
            f = src_kp.co[0] + offset
            new_kp = new_fc.keyframe_points.insert(
                frame=f, value=src_kp.co[1], options={'FAST'})
            new_kp.interpolation     = src_kp.interpolation
            new_kp.easing            = src_kp.easing
            new_kp.handle_left_type  = src_kp.handle_left_type
            new_kp.handle_right_type = src_kp.handle_right_type
            new_kp.handle_left  = (src_kp.handle_left[0]  + offset,
                                   src_kp.handle_left[1])
            new_kp.handle_right = (src_kp.handle_right[0] + offset,
                                   src_kp.handle_right[1])
            fc_has = True

        if need_end_key:
            val = src_fc.evaluate(end)
            kp = new_fc.keyframe_points.insert(frame=end + offset, value=val,
                                                options={'FAST'})
            kp.interpolation = 'BEZIER'
            fc_has = True

        if fc_has:
            new_fc.update()
            has_any = True
        else:
            dst_cb.fcurves.remove(new_fc)

    return has_any


def merge_nla_to_action(obj, name="Merged", scene=None):
    """Merge all NLA strips back into a single Action.

    *scene* – if given, timeline markers are created at each strip's
    end frame so the merged action can later be re-split.
    """
    anim = obj.animation_data
    if anim is None:
        return None

    merged = bpy.data.actions.new(name=name)
    merged.use_fake_user = True
    dst_cb = _ensure_channelbag(merged, datablock=obj)

    dst_map = {}
    has_any = False

    # Collect strip info for marker creation
    strip_infos = []

    for track in anim.nla_tracks:
        if getattr(track, 'mute', False):
            continue
        for strip in track.strips:
            if strip.action is None or getattr(strip, 'mute', False):
                continue

            # -- Map action-local frames to timeline frames ----------
            # NLA strip properties:
            #   strip.frame_start / frame_end  – timeline position
            #   strip.action_frame_start / action_frame_end – action range used
            #   strip.scale – time scale factor
            act_start = getattr(strip, 'action_frame_start', 0.0)
            act_end   = getattr(strip, 'action_frame_end', act_start)
            scale     = getattr(strip, 'scale', 1.0)
            if scale == 0:
                scale = 1.0
            timeline_start = strip.frame_start

            strip_infos.append((strip.name, strip.frame_start, strip.frame_end))

            strip_slot = getattr(strip, 'action_slot', None)
            src_fcurves = _get_fcurves(strip.action, strip_slot)

            for src_fc in src_fcurves:
                if not src_fc.keyframe_points:
                    continue

                key = (src_fc.data_path, src_fc.array_index)
                group_name = src_fc.group.name if src_fc.group else ""

                if key not in dst_map:
                    try:
                        new_fc = dst_cb.fcurves.new(
                            data_path=src_fc.data_path,
                            index=src_fc.array_index,
                            action_group=group_name,
                        )
                    except TypeError:
                        new_fc = dst_cb.fcurves.new(
                            data_path=src_fc.data_path,
                            index=src_fc.array_index,
                        )
                    dst_map[key] = new_fc

                dst_fc = dst_map[key]

                for src_kp in src_fc.keyframe_points:
                    # A strip can use only part of its Action. Do not leak
                    # keys from outside that selected Action range.
                    if not act_start <= src_kp.co[0] <= act_end:
                        continue

                    # Convert action-local frame to timeline frame:
                    #   timeline_frame = strip.frame_start
                    #                  + (action_frame - action_frame_start) * scale
                    f = timeline_start + (src_kp.co[0] - act_start) * scale
                    new_kp = dst_fc.keyframe_points.insert(
                        frame=f, value=src_kp.co[1], options={'FAST'})
                    new_kp.interpolation     = src_kp.interpolation
                    new_kp.easing            = src_kp.easing
                    new_kp.handle_left_type  = src_kp.handle_left_type
                    new_kp.handle_right_type = src_kp.handle_right_type
                    hl_f = timeline_start + (src_kp.handle_left[0]  - act_start) * scale
                    hr_f = timeline_start + (src_kp.handle_right[0] - act_start) * scale
                    new_kp.handle_left  = (hl_f, src_kp.handle_left[1])
                    new_kp.handle_right = (hr_f, src_kp.handle_right[1])
                    has_any = True

    for fc in dst_map.values():
        fc.update()

    if not has_any:
        bpy.data.actions.remove(merged)
        return None

    # -- Create timeline markers at each strip boundary ------------
    if scene is not None and strip_infos:
        # Sort strips by timeline position
        strip_infos.sort(key=lambda x: x[1])
        for strip_name, _start, end in strip_infos:
            end_frame = int(round(end))
            # Avoid duplicate markers at the same frame
            existing = [m for m in scene.timeline_markers
                        if m.frame == end_frame]
            if not existing:
                scene.timeline_markers.new(strip_name, frame=end_frame)

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
        try:
            fc = dst_cb.fcurves.new(
                data_path=data_path, index=index,
                action_group=group_name)
        except TypeError:
            fc = dst_cb.fcurves.new(
                data_path=data_path, index=index)
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
