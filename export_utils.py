"""Export validation, destination, and completion helpers."""

import os

import bpy
from bpy_extras.io_utils import ExportHelper

from .action_utils import _get_fcurves
from .clips import get_marker_segments

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
    elif export_format == 'FBX' and len(targets) > 1:
        issues.append((
            'ERROR',
            "FBX Quick Export supports one animated object at a time; "
            "multiple active Actions produce incomplete Blender FBX takes",
        ))

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


def _run_fbx_export(operator, scene):
    """Run the shared FBX exporter configuration and report failures."""
    try:
        bpy.ops.export_scene.fbx(
            filepath=operator.filepath,
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
        operator.report({'ERROR'}, f"FBX export failed: {exc}")
        return False
    return True


def _run_glb_export(operator, scene, marker_actions=False):
    """Run GLB export for marker Actions or existing NLA tracks."""
    kwargs = {
        'filepath': operator.filepath,
        'export_format': 'GLB',
        'export_animations': True,
        'export_def_bones': scene.m2nla_only_deform_bones,
    }
    if marker_actions:
        kwargs.update({
            'export_animation_mode': 'ACTIONS',
            'export_merge_animation': 'NLA_TRACK',
            'export_anim_single_armature': False,
            'export_apply': True,
            'export_rest_position_armature': False,
        })
    else:
        kwargs['export_animation_mode'] = 'NLA_TRACKS'

    try:
        bpy.ops.export_scene.gltf(
            use_selection=scene.m2nla_selected_only,
            **kwargs,
        )
    except TypeError:
        # Compatibility fallback for Blender versions using the older glTF
        # NLA option instead of export_animation_mode.
        kwargs.pop('export_animation_mode', None)
        kwargs.pop('export_merge_animation', None)
        kwargs.pop('export_anim_single_armature', None)
        kwargs.pop('export_rest_position_armature', None)
        kwargs['export_nla_strips'] = True
        try:
            bpy.ops.export_scene.gltf(
                use_selection=scene.m2nla_selected_only,
                **kwargs,
            )
        except Exception as exc:
            operator.report({'ERROR'}, f"GLB export failed: {exc}")
            return False
    except Exception as exc:
        operator.report({'ERROR'}, f"GLB export failed: {exc}")
        return False
    return True


def _finish_export(operator, scene, message):
    """Report export success and update shared destination state."""
    operator.report({'INFO'}, message)
    _remember_export_directory(scene, operator.filepath)
    _open_export_folder(scene, operator.filepath, operator)
    return {'FINISHED'}


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
