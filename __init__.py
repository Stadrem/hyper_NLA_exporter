bl_info = {
    "name": "Hyper NLA Exporter",
    "author": "Kim Dongsu",
    "version": (2, 4, 0),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > K-Quick Tools",
    "description": (
        "Place timeline markers to define animation clips, "
        "then export FBX/GLB with automatic split – no NLA hassle"
    ),
    "category": "Animation",
}


import os

import bpy
from contextlib import contextmanager
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ExportHelper
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
#  Marker → segment parsing
# ============================================================

def get_marker_segments(scene):
    """Parse timeline markers into animation segments.

    Marker "Walk" at frame 60  →  segment [scene_start … 60]  named "Walk"
    Marker "Run"  at frame 120 →  segment [61 … 120]           named "Run"
    """
    markers = sorted(scene.timeline_markers, key=lambda m: m.frame)
    if not markers:
        return []

    segments = []
    
    # Export clips use the standard 1-based animation range.
    seg_start = 1

    for marker in markers:
        if marker.frame < seg_start:
            continue
        segments.append({
            "name": marker.name,
            "start": seg_start,
            "end": marker.frame,
            "length": marker.frame - seg_start + 1,
            "marker": marker,
        })
        seg_start = marker.frame + 1

    return segments


# ============================================================
#  Export validation / completion helpers
# ============================================================

def _get_quick_export_targets(context):
    """Return objects with an active Action in the current export scope."""
    scene = context.scene
    objects = (context.selected_objects if scene.m2nla_selected_only
               else scene.objects)
    return [obj for obj in objects
            if obj.animation_data and obj.animation_data.action]


def _with_descendants(objects):
    """Return *objects* plus every child below them."""
    result = set(objects)
    pending = list(objects)
    while pending:
        obj = pending.pop()
        for child in obj.children:
            if child not in result:
                result.add(child)
                pending.append(child)
    return result


def collect_export_issues(context, export_format='FBX'):
    """Return preflight issues as ``(severity, message)`` tuples."""
    scene = context.scene
    issues = []
    segments = [seg for seg in get_marker_segments(scene)
                if not getattr(seg['marker'], 'm2nla_muted', False)]

    invalid_markers = [marker for marker in scene.timeline_markers
                       if (not getattr(marker, 'm2nla_muted', False)
                           and marker.frame < 1)]
    if invalid_markers:
        names = ", ".join(marker.name or "<unnamed>"
                          for marker in invalid_markers[:3])
        issues.append((
            'ERROR',
            f"Markers before frame 1 are not exportable: {names}",
        ))

    if not segments:
        issues.append(('ERROR', "No unmuted marker clips to export"))
    else:
        blank_names = [seg for seg in segments if not seg['name'].strip()]
        if blank_names:
            issues.append(('ERROR', "One or more clip names are empty"))

        name_counts = {}
        for seg in segments:
            name = seg['name'].strip()
            name_counts[name] = name_counts.get(name, 0) + 1
        duplicates = sorted(name for name, count in name_counts.items()
                            if name and count > 1)
        if duplicates:
            issues.append((
                'ERROR',
                "Duplicate clip names: " + ", ".join(duplicates[:4]),
            ))

    scoped_objects = list(context.selected_objects
                          if scene.m2nla_selected_only else scene.objects)
    if scene.m2nla_selected_only and not scoped_objects:
        issues.append(('ERROR', "Selected Only is on, but nothing is selected"))

    targets = _get_quick_export_targets(context)
    if not targets:
        issues.append(('ERROR', "No target object has an active Action"))

    for obj in targets:
        anim = obj.animation_data
        action = anim.action
        source_slot = getattr(anim, 'action_slot', None)
        if len(action.slots) > 1 and source_slot is None:
            issues.append((
                'ERROR',
                f"{obj.name}: shared Action has no assigned slot",
            ))
            continue

        fcurves = _get_fcurves(action, source_slot)
        if not fcurves:
            issues.append((
                'ERROR',
                f"{obj.name}: assigned Action slot has no F-Curves",
            ))
            continue

        if anim.nla_tracks:
            issues.append((
                'WARNING',
                f"{obj.name}: existing NLA tracks may also be exported",
            ))

        for seg in segments:
            has_key = any(
                seg['start'] <= point.co[0] <= seg['end']
                for fcurve in fcurves
                for point in fcurve.keyframe_points
            )
            if not has_key:
                issues.append((
                    'WARNING',
                    f"{obj.name} / {seg['name']}: no keys inside clip range",
                ))

    if scene.m2nla_selected_only and targets:
        included = (set(scoped_objects) if export_format == 'FBX'
                    else _with_descendants(scoped_objects))
        target_armatures = {obj for obj in targets
                            if obj.type == 'ARMATURE'}
        for obj in scene.objects:
            if obj.type != 'MESH' or obj in included:
                continue
            uses_target_armature = any(
                modifier.type == 'ARMATURE'
                and modifier.object in target_armatures
                for modifier in obj.modifiers
            )
            if uses_target_armature:
                issues.append((
                    'WARNING',
                    f"{obj.name}: skinned mesh is outside export selection",
                ))

    return issues


def _preflight_allows_export(operator, context, export_format):
    """Report preflight results and return False when errors block export."""
    issues = collect_export_issues(context, export_format)
    errors = [message for severity, message in issues
              if severity == 'ERROR']
    warnings = [message for severity, message in issues
                if severity == 'WARNING']
    if errors:
        operator.report(
            {'ERROR'},
            f"Preflight failed ({len(errors)}): {errors[0]}",
        )
        return False
    if warnings:
        operator.report(
            {'WARNING'},
            f"Preflight warnings ({len(warnings)}): {warnings[0]}",
        )
    return True


def _open_export_folder(scene, filepath, operator):
    """Open the exported file's containing folder when enabled."""
    if not scene.m2nla_open_folder:
        return
    folder = os.path.dirname(bpy.path.abspath(filepath))
    if not os.path.isdir(folder):
        operator.report({'WARNING'}, f"Export folder not found: {folder}")
        return
    try:
        result = bpy.ops.wm.path_open(filepath=folder)
        if 'FINISHED' not in result:
            operator.report({'WARNING'}, f"Could not open folder: {folder}")
    except Exception as exc:
        operator.report({'WARNING'}, f"Could not open export folder: {exc}")


def _export_directory(scene):
    """Return the absolute configured export directory."""
    path = scene.m2nla_export_path.strip() or "//Export/"
    return os.path.normpath(bpy.path.abspath(path))


def _default_export_name(filename_ext):
    """Use the blend filename for a predictable default export name."""
    blend_name = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    return f"{blend_name or 'untitled'}{filename_ext}"


def _set_auto_export_filepath(operator, scene):
    """Set the deterministic Auto Export filepath when the mode is enabled."""
    if not scene.m2nla_auto_export:
        return True
    if not bpy.data.is_saved or not bpy.data.filepath:
        operator.report(
            {'ERROR'},
            "Save the blend file before using Auto Export",
        )
        return False
    operator.filepath = os.path.join(
        _export_directory(scene),
        _default_export_name(operator.filename_ext),
    )
    return True


def _invoke_quick_export(operator, context, event):
    """Run directly in Auto Export mode, otherwise open the file browser."""
    scene = context.scene
    if not scene.m2nla_auto_export:
        return _invoke_export_browser(operator, context, event)

    if not _set_auto_export_filepath(operator, scene):
        return {'CANCELLED'}
    return operator.execute(context)


def _invoke_export_browser(operator, context, event):
    """Open an ExportHelper browser at the scene's configured directory."""
    directory = _export_directory(context.scene)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        operator.report(
            {'WARNING'},
            f"Could not create export folder; using current folder: {exc}",
        )
        directory = os.path.dirname(bpy.data.filepath) or os.getcwd()

    operator.filepath = os.path.join(
        directory, _default_export_name(operator.filename_ext))
    return ExportHelper.invoke(operator, context, event)


def _prepare_export_destination(scene, operator):
    """Resolve the selected filepath and make sure its directory exists."""
    operator.filepath = os.path.normpath(bpy.path.abspath(operator.filepath))
    directory = os.path.dirname(operator.filepath)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        operator.report({'ERROR'}, f"Could not create export folder: {exc}")
        return False
    return True


def collect_split_issues(split_result):
    """Validate the NLA tracks created by a temporary marker split."""
    issues = []
    expected_names = set(split_result['expected_clip_names'])
    created_names = set(split_result['clip_names'])
    missing_globally = sorted(expected_names - created_names)
    if missing_globally:
        issues.append((
            'ERROR',
            "No object produced these clips: "
            + ", ".join(missing_globally[:4]),
        ))

    expected_total = split_result['expected_track_count']
    actual_total = split_result['actual_track_count']
    if actual_total != expected_total:
        issues.append((
            'WARNING',
            f"Created {actual_total}/{expected_total} expected NLA tracks",
        ))

    for object_result in split_result['objects']:
        object_name = object_result['name']
        expected_count = object_result['expected_track_count']
        actual_count = object_result['actual_track_count']
        if actual_count != expected_count:
            issues.append((
                'WARNING',
                f"{object_name}: created {actual_count}/{expected_count} tracks",
            ))

        for clip in object_result['clips']:
            clip_issues = []
            if not clip['created']:
                clip_issues.append(('WARNING', "track was not created"))
            else:
                if clip['action_empty']:
                    clip_issues.append(('ERROR', "Action is empty"))
                if clip['strip_empty']:
                    clip_issues.append(('ERROR', "strip is empty"))
                if clip['track_name'] != clip['name']:
                    clip_issues.append((
                        'ERROR',
                        f"track name is '{clip['track_name']}'",
                    ))
                if clip['strip_name'] != clip['name']:
                    clip_issues.append((
                        'ERROR',
                        f"strip name is '{clip['strip_name']}'",
                    ))
                start_matches = abs(
                    clip['actual_start'] - clip['expected_start']) < 0.001
                end_matches = abs(
                    clip['actual_end'] - clip['expected_end']) < 0.001
                if not start_matches or not end_matches:
                    clip_issues.append((
                        'ERROR',
                        "strip range is "
                        f"{clip['actual_start']:g}-{clip['actual_end']:g}; "
                        f"expected {clip['expected_start']:g}-"
                        f"{clip['expected_end']:g}",
                    ))

            if clip_issues:
                severity = ('ERROR' if any(level == 'ERROR'
                                           for level, _ in clip_issues)
                            else 'WARNING')
                message = "; ".join(message for _level, message
                                    in clip_issues)
                clip['severity'] = severity
                clip['message'] = message
                issues.append((
                    severity,
                    f"{object_name} / {clip['name']}: {message}",
                ))
            else:
                clip['severity'] = 'OK'
                clip['message'] = (
                    f"Track/Strip OK  "
                    f"{clip['actual_start']:g}-{clip['actual_end']:g}"
                )

    return issues


def _split_allows_export(operator, split_result):
    """Report generated-split problems and block export on hard errors."""
    issues = collect_split_issues(split_result)
    errors = [message for severity, message in issues
              if severity == 'ERROR']
    warnings = [message for severity, message in issues
                if severity == 'WARNING']
    if errors:
        operator.report(
            {'ERROR'},
            f"NLA split validation failed ({len(errors)}): {errors[0]}",
        )
        return False
    if warnings:
        operator.report(
            {'WARNING'},
            f"NLA split warnings ({len(warnings)}): {warnings[0]}",
        )
    return True


def _remember_export_directory(scene, filepath):
    """Keep the last successful directory as the next export destination."""
    directory = os.path.dirname(bpy.path.abspath(filepath))
    configured = _export_directory(scene)
    if os.path.normcase(directory) == os.path.normcase(configured):
        return
    scene.m2nla_export_path = directory + os.sep


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
#  Operators  – Quick Export (main workflow)
# ============================================================

class MARKERNLA_OT_validate_export(Operator):
    """Validate marker clips and export targets before Quick Export"""
    bl_idname = "markernla.validate_export"
    bl_label = "Export Preflight"
    bl_description = (
        "Build a temporary marker split and check clip names, tracks, "
        "strips, frame ranges, Action content, slots, and hierarchy"
    )
    bl_options = {'INTERNAL'}

    export_format: EnumProperty(
        name="Format",
        items=(
            ('FBX', "FBX", "Validate the current FBX export scope"),
            ('GLB', "GLB", "Validate the current GLB export scope"),
        ),
        default='FBX',
    )

    def execute(self, context):
        issues = collect_export_issues(context, self.export_format)
        split_result = None
        static_errors = [message for severity, message in issues
                         if severity == 'ERROR']

        if not static_errors:
            targets = _get_quick_export_targets(context)
            try:
                with _temporary_nla_split(targets, context.scene) as result:
                    split_result = result
                    issues.extend(collect_split_issues(split_result))
            except Exception as exc:
                issues.append((
                    'ERROR',
                    f"Temporary NLA split check failed: {exc}",
                ))

        error_count = sum(severity == 'ERROR'
                          for severity, _message in issues)
        warning_count = sum(severity == 'WARNING'
                            for severity, _message in issues)

        def draw_popup(menu, _context):
            layout = menu.layout
            if issues:
                layout.label(text="Preflight", icon='VIEWZOOM')
                for severity, message in issues:
                    icon = 'CANCEL' if severity == 'ERROR' else 'ERROR'
                    row = layout.row()
                    row.alert = severity == 'ERROR'
                    row.label(text=message, icon=icon)

            if split_result is not None:
                if issues:
                    layout.separator()
                actual = split_result['actual_track_count']
                expected = split_result['expected_track_count']
                summary_icon = ('CHECKMARK' if actual == expected
                                else 'ERROR')
                layout.label(
                    text=f"NLA Split Dry Run — {actual}/{expected} tracks",
                    icon=summary_icon,
                )
                for object_result in split_result['objects']:
                    box = layout.box()
                    box.label(
                        text=(
                            f"{object_result['name']} — "
                            f"{object_result['actual_track_count']}/"
                            f"{object_result['expected_track_count']} tracks"
                        ),
                        icon='OBJECT_DATA',
                    )
                    for clip in object_result['clips']:
                        severity = clip['severity']
                        symbol = {'OK': '✓', 'WARNING': '⚠'}.get(
                            severity, '✗')
                        icon = {'OK': 'CHECKMARK', 'WARNING': 'ERROR'}.get(
                            severity, 'CANCEL')
                        row = box.row()
                        row.alert = severity == 'ERROR'
                        row.label(
                            text=(f"{clip['name']}  {symbol}  "
                                  f"{clip['message']}"),
                            icon=icon,
                        )
            elif not issues:
                layout.label(
                    text="Ready to export — no issues found",
                    icon='CHECKMARK',
                )
            elif static_errors:
                layout.separator()
                layout.label(
                    text="NLA split dry run skipped until errors are fixed",
                    icon='INFO',
                )

        title = (f"{self.export_format} Preflight — "
                 f"{error_count} errors, {warning_count} warnings")
        # Blender can crash when popup_menu is requested in --background
        # mode. Interactive sessions still get the full issue list popup.
        if not bpy.app.background:
            context.window_manager.popup_menu(
                draw_popup, title=title, icon='INFO')

        if error_count:
            self.report({'ERROR'}, title)
        elif warning_count:
            self.report({'WARNING'}, title)
        else:
            self.report({'INFO'}, f"{self.export_format} is ready to export")
        return {'FINISHED'}


class MARKERNLA_OT_quick_export_fbx(Operator, ExportHelper):
    """One-click marker-split FBX export – original animation untouched"""
    bl_idname      = "markernla.quick_export_fbx"
    bl_label       = "Quick Export FBX"
    bl_description = (
        "Split by markers → export FBX → restore original action. "
        "Each marker segment becomes a separate animation take"
    )

    filename_ext  = ".fbx"
    filter_glob: StringProperty(default="*.fbx", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return len(context.scene.timeline_markers) > 0

    def invoke(self, context, event):
        return _invoke_quick_export(self, context, event)

    def execute(self, context):
        scene = context.scene
        if not _set_auto_export_filepath(self, scene):
            return {'CANCELLED'}
        if not _prepare_export_destination(scene, self):
            return {'CANCELLED'}
        if not _preflight_allows_export(self, context, 'FBX'):
            return {'CANCELLED'}
        anim_objs = _get_quick_export_targets(context)

        if not anim_objs:
            self.report({'ERROR'}, "No valid objects with animation data found")
            return {'CANCELLED'}

        with _temporary_nla_split(anim_objs, scene) as split_result:
            clip_names = split_result['clip_names']
            if not clip_names:
                self.report({'ERROR'}, "No keyframes found in marker segments")
                return {'CANCELLED'}
            if not _split_allows_export(self, split_result):
                return {'CANCELLED'}

            try:
                bpy.ops.export_scene.fbx(
                    filepath=self.filepath,
                    use_selection=scene.m2nla_selected_only,
                    use_armature_deform_only=scene.m2nla_only_deform_bones,
                    bake_anim=True,
                    bake_anim_use_nla_strips=True,
                    bake_anim_use_all_actions=False,
                    bake_anim_force_startend_keying=True,
                    add_leaf_bones=False,
                    path_mode='AUTO',
                )
            except Exception as exc:
                self.report({'ERROR'}, f"FBX export failed: {exc}")
                return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Exported {len(clip_names)} clips → {self.filepath}"
        )
        _remember_export_directory(scene, self.filepath)
        _open_export_folder(scene, self.filepath, self)
        return {'FINISHED'}


class MARKERNLA_OT_quick_export_glb(Operator, ExportHelper):
    """One-click marker-split GLB export – original animation untouched"""
    bl_idname      = "markernla.quick_export_glb"
    bl_label       = "Quick Export GLB"
    bl_description = (
        "Split by markers → export GLB → restore original action. "
        "Each marker segment becomes a separate animation take"
    )

    filename_ext  = ".glb"
    filter_glob: StringProperty(default="*.glb", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return len(context.scene.timeline_markers) > 0

    def invoke(self, context, event):
        return _invoke_quick_export(self, context, event)

    def execute(self, context):
        scene = context.scene
        if not _set_auto_export_filepath(self, scene):
            return {'CANCELLED'}
        if not _prepare_export_destination(scene, self):
            return {'CANCELLED'}
        if not _preflight_allows_export(self, context, 'GLB'):
            return {'CANCELLED'}
        anim_objs = _get_quick_export_targets(context)

        if not anim_objs:
            self.report({'ERROR'}, "No valid objects with animation data found")
            return {'CANCELLED'}

        with _temporary_nla_split(anim_objs, scene) as split_result:
            clip_names = split_result['clip_names']
            if not clip_names:
                self.report({'ERROR'}, "No keyframes found in marker segments")
                return {'CANCELLED'}
            if not _split_allows_export(self, split_result):
                return {'CANCELLED'}

            kwargs = dict(
                filepath=self.filepath,
                export_format='GLB',
                export_animations=True,
                export_animation_mode='NLA_TRACKS',
                export_apply=True,
                export_rest_position_armature=False,
                export_def_bones=scene.m2nla_only_deform_bones,
            )

            # FIX: Auto-select children if Selected Only is enabled so that 
            # glTF exporter doesn't break skinned mesh hierarchy.
            original_selection = [o for o in context.selected_objects]
            if scene.m2nla_selected_only:
                def select_recursive(obj):
                    for child in obj.children:
                        child.select_set(True)
                        select_recursive(child)
                for obj in original_selection:
                    select_recursive(obj)

            try:
                try:
                    bpy.ops.export_scene.gltf(
                        use_selection=scene.m2nla_selected_only, **kwargs)
                except TypeError:
                    try:
                        kwargs.pop('export_animation_mode', None)
                        kwargs.pop('export_rest_position_armature', None)
                        kwargs['export_nla_strips'] = True
                        bpy.ops.export_scene.gltf(
                            use_selection=scene.m2nla_selected_only, **kwargs)
                    except Exception as exc:
                        self.report({'ERROR'}, f"GLB export failed: {exc}")
                        return {'CANCELLED'}
                except Exception as exc:
                    self.report({'ERROR'}, f"GLB export failed: {exc}")
                    return {'CANCELLED'}
            finally:
                if scene.m2nla_selected_only:
                    bpy.ops.object.select_all(action='DESELECT')
                    for obj in original_selection:
                        obj.select_set(True)

        self.report(
            {'INFO'},
            f"Exported {len(clip_names)} clips → {self.filepath}"
        )
        _remember_export_directory(scene, self.filepath)
        _open_export_folder(scene, self.filepath, self)
        return {'FINISHED'}


# ============================================================
#  Operators  – Manual NLA tools (advanced)
# ============================================================

class MARKERNLA_OT_convert(Operator):
    """Convert timeline markers into separate NLA action strips"""
    bl_idname  = "markernla.convert"
    bl_label   = "Markers → NLA"
    bl_description = (
        "Read timeline markers, split the active action into clips, "
        "and push them as NLA strips (Simple stack)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.timeline_markers) > 0

    def execute(self, context):
        scene  = context.scene
        objs = [o for o in context.selected_objects if o.animation_data and o.animation_data.action]

        if not objs:
            self.report({'ERROR'}, "No selected objects with animation data")
            return {'CANCELLED'}

        segments = get_marker_segments(scene)
        if not segments:
            self.report({'ERROR'}, "No valid marker segments found")
            return {'CANCELLED'}

        total_created = 0
        
        for obj in objs:
            if scene.m2nla_clear_nla and obj.animation_data.nla_tracks:
                for trk in list(obj.animation_data.nla_tracks):
                    obj.animation_data.nla_tracks.remove(trk)

        for seg in segments:
            for obj in objs:
                source = obj.animation_data.action
                if not source:
                    continue

                # Action name includes object prefix to avoid collisions
                action_name = f"{obj.name}_{seg['name']}"
                new_action = bpy.data.actions.new(name=action_name)
                new_action.use_fake_user = True
                    
                did_copy = copy_segment_to_action(
                    source, new_action, seg['start'], seg['end'],
                    create_boundaries=scene.m2nla_boundary_keys,
                    datablock=obj,
                    source_slot=getattr(obj.animation_data,
                                        'action_slot', None),
                )

                _preserve_static_transforms(
                    new_action, obj, source,
                    source_slot=getattr(obj.animation_data,
                                        'action_slot', None),
                )
                has_content = did_copy or bool(_get_fcurves(new_action))

                if has_content:
                    dst_cb = _get_channelbag(new_action)
                    slot = getattr(dst_cb, 'slot', None)

                    track = obj.animation_data.nla_tracks.new()
                    track.name = seg['name']
                    strip = track.strips.new(
                        name=seg['name'],
                        start=seg['start'],
                        action=new_action,
                    )
                    strip.name = seg['name']
                    if slot and hasattr(strip, 'action_slot'):
                        strip.action_slot = slot
                    total_created += 1
                else:
                    bpy.data.actions.remove(new_action)

        if scene.m2nla_unlink_source:
            for obj in objs:
                obj.animation_data.action = None

        if total_created == 0:
            self.report({'ERROR'}, "No keyframes found in any marker segment")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Created {total_created} NLA strips across {len(objs)} objects")
        return {'FINISHED'}


class MARKERNLA_OT_merge(Operator):
    """Merge NLA strips back into a single action"""
    bl_idname  = "markernla.merge"
    bl_label   = "NLA → Action"
    bl_description = (
        "Combine simple NLA strips into one action at their timeline "
        "positions (ignores repeat, reverse, blending, influence, and modifiers)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) > 0

    def execute(self, context):
        scene = context.scene
        objs = [o for o in context.selected_objects if o.animation_data and o.animation_data.nla_tracks]

        if not objs:
            self.report({'ERROR'}, "No selected objects with NLA tracks")
            return {'CANCELLED'}

        merged_count = 0
        for obj in objs:
            merged = merge_nla_to_action(obj, name=f"{obj.name}_Merged",
                                          scene=scene)
            if merged is None:
                continue

            if scene.m2nla_clear_nla:
                for trk in list(obj.animation_data.nla_tracks):
                    for strip in trk.strips:
                        if strip.action:
                            strip.action.use_fake_user = False
                    obj.animation_data.nla_tracks.remove(trk)

            obj.animation_data.action = merged
            if merged.slots:
                obj.animation_data.action_slot = merged.slots[0]
            merged_count += 1

        if merged_count == 0:
            self.report({'ERROR'}, "No keyframes found in NLA strips")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Merged NLA into actions for {merged_count} objects")
        return {'FINISHED'}


# ---- Legacy NLA export (for when user already has NLA tracks) ------------

class MARKERNLA_OT_export_fbx(Operator, ExportHelper):
    """Export FBX from existing NLA strips"""
    bl_idname     = "markernla.export_fbx"
    bl_label      = "Export NLA FBX"
    bl_description = "Export existing NLA strips as FBX animation takes"

    filename_ext  = ".fbx"
    filter_glob: StringProperty(default="*.fbx", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        return _invoke_export_browser(self, context, event)

    def execute(self, context):
        scene = context.scene
        if not _prepare_export_destination(scene, self):
            return {'CANCELLED'}
        try:
            bpy.ops.export_scene.fbx(
                filepath=self.filepath,
                use_selection=scene.m2nla_selected_only,
                use_armature_deform_only=scene.m2nla_only_deform_bones,
                bake_anim=True,
                bake_anim_use_nla_strips=True,
                bake_anim_use_all_actions=False,
                bake_anim_force_startend_keying=True,
                add_leaf_bones=False,
                path_mode='AUTO',
            )
        except Exception as exc:
            self.report({'ERROR'}, f"FBX export failed: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Exported FBX → {self.filepath}")
        _remember_export_directory(scene, self.filepath)
        _open_export_folder(scene, self.filepath, self)
        return {'FINISHED'}


class MARKERNLA_OT_export_glb(Operator, ExportHelper):
    """Export GLB from existing NLA strips"""
    bl_idname     = "markernla.export_glb"
    bl_label      = "Export NLA GLB"
    bl_description = "Export existing NLA strips as GLB animation clips"

    filename_ext  = ".glb"
    filter_glob: StringProperty(default="*.glb", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        return _invoke_export_browser(self, context, event)

    def execute(self, context):
        scene = context.scene
        if not _prepare_export_destination(scene, self):
            return {'CANCELLED'}
        kwargs = dict(
            filepath=self.filepath,
            export_format='GLB',
            export_animations=True,
            export_animation_mode='NLA_TRACKS',
            export_def_bones=scene.m2nla_only_deform_bones,
        )
        try:
            bpy.ops.export_scene.gltf(
                use_selection=scene.m2nla_selected_only, **kwargs)
        except TypeError:
            try:
                # Fallback for older Blender versions
                kwargs.pop('export_animation_mode', None)
                kwargs['export_nla_strips'] = True
                bpy.ops.export_scene.gltf(
                    use_selection=scene.m2nla_selected_only, **kwargs)
            except Exception as exc:
                self.report({'ERROR'}, f"GLB export failed: {exc}")
                return {'CANCELLED'}
        except Exception as exc:
            self.report({'ERROR'}, f"GLB export failed: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Exported GLB → {self.filepath}")
        _remember_export_directory(scene, self.filepath)
        _open_export_folder(scene, self.filepath, self)
        return {'FINISHED'}


# ---- Segment preview (frame-range) ----------------------------------------

class MARKERNLA_OT_set_frame_range(Operator):
    """Set the playback range to this marker segment"""
    bl_idname  = "markernla.set_frame_range"
    bl_label   = "Preview Segment"
    bl_description = "Set timeline Start/End to this segment's frame range"
    bl_options = {'INTERNAL'}

    frame_start: IntProperty()
    frame_end:   IntProperty()

    def execute(self, context):
        scene = context.scene
        scene.frame_start = self.frame_start
        scene.frame_end   = self.frame_end
        scene.frame_set(self.frame_start)
        return {'FINISHED'}


class MARKERNLA_OT_reset_frame_range(Operator):
    """Reset playback range to the full animation length"""
    bl_idname  = "markernla.reset_frame_range"
    bl_label   = "Reset Range"
    bl_description = (
        "Restore the timeline range: Start = 1, "
        "End = last marker frame"
    )
    bl_options = {'INTERNAL'}

    def execute(self, context):
        scene = context.scene
        scene.frame_start = 1
        markers = scene.timeline_markers
        if markers:
            scene.frame_end = max(m.frame for m in markers)
        return {'FINISHED'}


class MARKERNLA_OT_delete_marker(Operator):
    """Delete this marker"""
    bl_idname  = "markernla.delete_marker"
    bl_label   = "Delete Marker"
    bl_description = "Delete this marker from the timeline"
    bl_options = {'INTERNAL', 'UNDO'}

    marker_name: StringProperty()
    marker_frame: IntProperty()

    def execute(self, context):
        scene = context.scene
        for m in scene.timeline_markers:
            if m.name == self.marker_name and m.frame == self.marker_frame:
                scene.timeline_markers.remove(m)
                break
        return {'FINISHED'}


# ---- Cleanup -------------------------------------------------------------

class MARKERNLA_OT_cleanup(Operator):
    """Remove all NLA tracks (and unlink their actions)"""
    bl_idname  = "markernla.cleanup"
    bl_label   = "Cleanup NLA"
    bl_description = "Remove every NLA track from the active object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) > 0

    def execute(self, context):
        objs = [o for o in context.selected_objects if o.animation_data and o.animation_data.nla_tracks]
        if not objs:
            self.report({'ERROR'}, "No selected objects with NLA tracks")
            return {'CANCELLED'}

        removed = 0
        for obj in objs:
            for trk in list(obj.animation_data.nla_tracks):
                for strip in trk.strips:
                    if strip.action:
                        strip.action.use_fake_user = False
                obj.animation_data.nla_tracks.remove(trk)
                removed += 1

        self.report({'INFO'}, f"Removed {removed} NLA track(s)")
        return {'FINISHED'}


# ============================================================
#  UI Panel
# ============================================================

class MARKERNLA_PT_panel(Panel):
    bl_label       = "Hyper NLA Exporter"
    bl_idname      = "MARKERNLA_PT_panel"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'K-Quick Tools'
    bl_options     = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='NLA')

    def draw(self, context):
        layout = self.layout
        scene  = context.scene
        obj    = context.active_object

        # ── Marker Segments ──────────────────────────────────
        box = layout.box()
        box.label(text="Marker Segments", icon='MARKER_HLT')

        segments = get_marker_segments(scene)
        if segments:
            name_counts = {}
            for seg in segments:
                if not getattr(seg['marker'], "m2nla_muted", False):
                    name = seg['marker'].name
                    name_counts[name] = name_counts.get(name, 0) + 1
            has_duplicates = any(c > 1 for c in name_counts.values())

            col = box.column(align=True)
            for seg in segments:
                row = col.row(align=True)
                marker = seg['marker']

                # Mute Toggle
                is_muted = getattr(marker, "m2nla_muted", False)
                icon = 'HIDE_ON' if is_muted else 'HIDE_OFF'
                row.prop(marker, "m2nla_muted", text="", icon=icon, emboss=False)

                op = row.operator("markernla.set_frame_range", text="", icon='PLAY')
                op.frame_start = seg['start']
                op.frame_end   = seg['end']

                name_row = row.row(align=True)
                if not is_muted and name_counts.get(marker.name, 0) > 1:
                    name_row.alert = True
                name_row.prop(marker, "name", text="")

                row.label(text=f"{seg['start']}~{seg['end']} ({seg['length']}f)")

                del_op = row.operator("markernla.delete_marker", text="", icon='TRASH', emboss=False)
                del_op.marker_name = marker.name
                del_op.marker_frame = marker.frame

            if has_duplicates:
                box.label(text="⚠️ Duplicate unmuted marker names!", icon='ERROR')

            row = box.row(align=True)
            row.operator("markernla.reset_frame_range", icon='LOOP_BACK')
        else:
            col = box.column(align=True)
            col.label(text="Place markers on the timeline", icon='INFO')
            col.label(text="  Marker name  = clip name")
            col.label(text="  Marker frame = clip end frame")

        # ── Target info ───────────────────────────────
        box = layout.box()
        objs = context.selected_objects if scene.m2nla_selected_only else context.scene.objects
        valid_objs = [o for o in objs if o.animation_data and (o.animation_data.action or o.animation_data.nla_tracks)]
        box.label(text=f"Targets: {len(valid_objs)} Objects", icon='OBJECT_DATA')
        
        if obj and obj.animation_data:
            if obj.animation_data.action:
                act = obj.animation_data.action
                box.label(text=f"Active Action: {act.name}", icon='ACTION')
            elif obj.animation_data.nla_tracks:
                n = len(obj.animation_data.nla_tracks)
                box.label(text=f"Active NLA Tracks: {n}", icon='NLA')

        layout.separator()

        # ── Settings ─────────────────────────────────────────
        box = layout.box()
        box.label(text="Settings", icon='PREFERENCES')
        col = box.column(align=True)
        col.prop(scene, "m2nla_export_path", text="Export Path")
        col.prop(scene, "m2nla_auto_export")
        col.prop(scene, "m2nla_only_deform_bones")
        col.prop(scene, "m2nla_boundary_keys")
        col.prop(scene, "m2nla_selected_only")
        col.prop(scene, "m2nla_open_folder")

        layout.separator()

        # ── Quick Export (main feature) ──────────────────────
        box = layout.box()
        box.label(text="Quick Export (Marker Split)", icon='EXPORT')
        row = box.row(align=True)
        op = row.operator("markernla.validate_export",
                          text="Check FBX", icon='CHECKMARK')
        op.export_format = 'FBX'
        op = row.operator("markernla.validate_export",
                          text="Check GLB", icon='CHECKMARK')
        op.export_format = 'GLB'

        col = box.column(align=True)
        col.scale_y = 1.6
        row = col.row(align=True)
        row.operator("markernla.quick_export_fbx", text="FBX", icon='EXPORT')
        row.operator("markernla.quick_export_glb", text="GLB", icon='EXPORT')

        layout.separator()

        # ── Manual NLA Tools (advanced) ──────────────────────
        box = layout.box()
        header = box.row()
        header.prop(scene, "m2nla_show_nla_tools",
                    text="Manual NLA Tools",
                    icon='TRIA_DOWN' if scene.m2nla_show_nla_tools else 'TRIA_RIGHT',
                    emboss=False)

        if scene.m2nla_show_nla_tools:
            col = box.column(align=True)
            col.prop(scene, "m2nla_clear_nla")
            col.prop(scene, "m2nla_unlink_source")

            col = box.column(align=True)
            col.scale_y = 1.4
            col.operator("markernla.convert", icon='NLA')
            col.operator("markernla.merge", icon='ACTION')

            box.separator()

            sub = box.column(align=True)
            sub.label(text="Export existing NLA:", icon='NLA')
            row = sub.row(align=True)
            row.scale_y = 1.3
            row.operator("markernla.export_fbx", icon='EXPORT')
            row.operator("markernla.export_glb", icon='EXPORT')

            box.separator()
            box.operator("markernla.cleanup", icon='TRASH')


# ============================================================
#  Registration
# ============================================================

_classes = (
    MARKERNLA_OT_validate_export,
    MARKERNLA_OT_quick_export_fbx,
    MARKERNLA_OT_quick_export_glb,
    MARKERNLA_OT_convert,
    MARKERNLA_OT_merge,
    MARKERNLA_OT_export_fbx,
    MARKERNLA_OT_export_glb,
    MARKERNLA_OT_set_frame_range,
    MARKERNLA_OT_reset_frame_range,
    MARKERNLA_OT_delete_marker,
    MARKERNLA_OT_cleanup,
    MARKERNLA_PT_panel,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    S = bpy.types.Scene

    bpy.types.TimelineMarker.m2nla_muted = BoolProperty(
        name="Mute Clip",
        description="Exclude this marker segment from Quick Export",
        default=False,
    )

    S.m2nla_only_deform_bones = BoolProperty(
        name="Only Deform Bones",
        description="Export only deformation bones (optimizes game exports)",
        default=False,
    )
    S.m2nla_boundary_keys = BoolProperty(
        name="Create Boundary Keys",
        description=(
            "Evaluate curve at segment start/end and insert missing keys. "
            "If off, unkeyed channels may reset to rest pose within segments"
        ),
        default=True,
    )
    S.m2nla_clear_nla = BoolProperty(
        name="Clear Existing NLA",
        description="Remove existing NLA tracks before creating new ones",
        default=True,
    )
    S.m2nla_unlink_source = BoolProperty(
        name="Unlink Source Action",
        description=(
            "Detach the source action from the object after conversion "
            "(the action data itself is preserved in the blend file)"
        ),
        default=True,
    )
    S.m2nla_selected_only = BoolProperty(
        name="Selected Only",
        description=(
            "Export only selected objects; Quick GLB also includes all "
            "descendants of the selection"
        ),
        default=True,
    )
    S.m2nla_open_folder = BoolProperty(
        name="Open Folder After Export",
        description="Open the containing folder after a successful export",
        default=True,
    )
    S.m2nla_auto_export = BoolProperty(
        name="Auto Export",
        description=(
            "Skip the file browser and overwrite an FBX or GLB named after "
            "the saved blend file in Export Path"
        ),
        default=False,
    )
    S.m2nla_export_path = StringProperty(
        name="Export Path",
        description=(
            "Folder used for exports; // is relative to the blend file"
        ),
        default="//Export/",
        subtype='DIR_PATH',
        options={'PATH_SUPPORTS_BLEND_RELATIVE'},
    )
    for scene in bpy.data.scenes:
        if scene.m2nla_export_path.strip().lower() in {
                "/export", "/export/", "\\export", "\\export\\"}:
            scene.m2nla_export_path = "//Export/"
    S.m2nla_show_nla_tools = BoolProperty(
        name="Show NLA Tools",
        description="Show advanced manual NLA conversion tools",
        default=False,
    )


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)

    S = bpy.types.Scene
    props = (
        "m2nla_only_deform_bones",
        "m2nla_boundary_keys",
        "m2nla_clear_nla",
        "m2nla_unlink_source",
        "m2nla_selected_only",
        "m2nla_open_folder",
        "m2nla_auto_export",
        "m2nla_export_path",
        "m2nla_show_nla_tools",
    )
    for p in props:
        if hasattr(S, p):
            delattr(S, p)

    if hasattr(bpy.types.TimelineMarker, "m2nla_muted"):
        delattr(bpy.types.TimelineMarker, "m2nla_muted")


if __name__ == "__main__":
    register()
