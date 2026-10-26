"""Operators for validation, export, conversion, preview, and cleanup."""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper

from .action_utils import (
    find_action_slot,
    is_generated_action,
    merge_nla_to_action,
    release_generated_action,
)
from .clips import get_marker_segments, get_shared_frame_markers
from .export_utils import (
    _get_export_scope,
    _get_quick_export_targets,
    _finish_export,
    _invoke_export_browser,
    _invoke_quick_export,
    _preflight_allows_export,
    _prepare_export_destination,
    _run_fbx_export,
    _run_glb_export,
    _set_auto_export_filepath,
    _split_allows_export,
    _temporary_descendant_selection,
    collect_export_issues,
    collect_split_issues,
)
from .nla_split import _build_nla_track_for_segment, _temporary_nla_split

#  Operators  – Quick Export (main workflow)
# ============================================================

# A popup menu taller than the window flows into extra columns, so long
# preflight lists are capped and fully OK objects collapse into one line.
_POPUP_ISSUE_LIMIT = 12
_POPUP_OBJECT_LIMIT = 6


def _draw_preflight(layout, issues, split_result, static_errors):
    """Draw the preflight popup: issues first, then the split dry run."""
    if issues:
        layout.label(text="Preflight", icon='VIEWZOOM')
        for severity, message in issues[:_POPUP_ISSUE_LIMIT]:
            icon = {'ERROR': 'CANCEL', 'INFO': 'INFO'}.get(severity, 'ERROR')
            row = layout.row()
            row.alert = severity == 'ERROR'
            row.label(text=message, icon=icon)
        hidden = len(issues) - _POPUP_ISSUE_LIMIT
        if hidden > 0:
            layout.label(
                text=f"… {hidden} more (full list in System Console)",
                icon='BLANK1')

    if split_result is not None:
        if issues:
            layout.separator()
        actual = split_result['actual_track_count']
        expected = split_result['expected_track_count']
        layout.label(
            text=f"NLA Split Dry Run — {actual}/{expected} tracks",
            icon='CHECKMARK' if actual == expected else 'ERROR',
        )
        objects = split_result['objects']
        flagged = [result for result in objects
                   if any(clip['severity'] != 'OK'
                          for clip in result['clips'])]
        ok_count = len(objects) - len(flagged)
        if ok_count:
            clip_count = len(split_result['expected_clip_names'])
            layout.label(
                text=(f"{ok_count} object(s): all {clip_count} clip(s) "
                      "Track/Strip OK"),
                icon='CHECKMARK',
            )
        for object_result in flagged[:_POPUP_OBJECT_LIMIT]:
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
                if severity == 'OK':
                    continue
                symbol = '⚠' if severity == 'WARNING' else '✗'
                row = box.row()
                row.alert = severity == 'ERROR'
                row.label(
                    text=f"{clip['name']}  {symbol}  {clip['message']}",
                    icon='ERROR' if severity == 'WARNING' else 'CANCEL',
                )
        hidden = len(flagged) - _POPUP_OBJECT_LIMIT
        if hidden > 0:
            layout.label(text=(f"… {hidden} more object(s) with issues "
                               "(full list in System Console)"),
                         icon='BLANK1')
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
            try:
                with _temporary_nla_split(_get_export_scope(context),
                                          context.scene) as result:
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
            _draw_preflight(menu.layout, issues, split_result, static_errors)

        title = (f"{self.export_format} Preflight — "
                 f"{error_count} errors, {warning_count} warnings")
        # The popup caps long lists; the System Console keeps all of them.
        if issues:
            print(title)
            for severity, message in issues:
                print(f"  [{severity}] {message}")
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
    allow_multiple_fbx_targets: BoolProperty(
        name="Allow Multiple FBX Targets",
        description=(
            "Experimental: bypass the one-animated-object safety check. "
            "Blender may create incomplete animation takes"
        ),
        default=False,
        options={'HIDDEN'},
    )

    @classmethod
    def poll(cls, context):
        return len(context.scene.timeline_markers) > 0

    def invoke(self, context, event):
        if self.allow_multiple_fbx_targets:
            # A test export must never inherit Auto Export and silently
            # overwrite the normal production FBX.
            return _invoke_export_browser(
                self,
                context,
                event,
                filename_suffix="_multi_rig_test",
            )
        return _invoke_quick_export(self, context, event)

    def execute(self, context):
        scene = context.scene
        if (not self.allow_multiple_fbx_targets
                and not _set_auto_export_filepath(self, scene)):
            return {'CANCELLED'}
        if not _prepare_export_destination(scene, self):
            return {'CANCELLED'}
        if not _preflight_allows_export(
                self,
                context,
                'FBX',
                allow_multiple_fbx_targets=self.allow_multiple_fbx_targets):
            return {'CANCELLED'}
        anim_objs = _get_quick_export_targets(context)

        if not anim_objs:
            self.report({'ERROR'}, "No valid objects with animation data found")
            return {'CANCELLED'}
        if self.allow_multiple_fbx_targets and len(anim_objs) > 1:
            self.report({'WARNING'}, (
                "Experimental multi-target FBX export: Blender may produce "
                "incomplete animation takes"
            ))

        with _temporary_nla_split(_get_export_scope(context),
                                  scene) as split_result:
            clip_names = split_result['clip_names']
            if not clip_names:
                self.report({'ERROR'}, "No keyframes found in marker segments")
                return {'CANCELLED'}
            if not _split_allows_export(self, split_result):
                return {'CANCELLED'}

            with _temporary_descendant_selection(context):
                if not _run_fbx_export(self, scene):
                    return {'CANCELLED'}

        return _finish_export(
            self,
            scene,
            f"Exported {len(clip_names)} clips → {self.filepath}",
        )


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

        with _temporary_nla_split(_get_export_scope(context),
                                  scene) as split_result:
            clip_names = split_result['clip_names']
            if not clip_names:
                self.report({'ERROR'}, "No keyframes found in marker segments")
                return {'CANCELLED'}
            if not _split_allows_export(self, split_result):
                return {'CANCELLED'}

            # ACTIONS mode would also export each source Action. Temporarily
            # detach only the active Action; the surrounding split context
            # keeps the original Action and slot available for restoration.
            active_action_states = []
            for obj in anim_objs:
                anim = obj.animation_data
                active_action_states.append((
                    anim,
                    anim.action,
                    getattr(anim, 'action_slot', None),
                ))
                anim.action = None

            try:
                with _temporary_descendant_selection(context):
                    if not _run_glb_export(
                            self, scene, marker_actions=True):
                        return {'CANCELLED'}
            finally:
                for anim, action, slot in active_action_states:
                    anim.action = action
                    if slot is not None:
                        try:
                            anim.action_slot = slot
                        except Exception:
                            pass

        return _finish_export(
            self,
            scene,
            f"Exported {len(clip_names)} clips → {self.filepath}",
        )


# ============================================================
#  Operators  – Manual NLA tools (advanced)
# ============================================================

def _preserve_or_release_action(action):
    """Keep authored animation when its last active/NLA user is removed."""
    if action is None:
        return
    if is_generated_action(action):
        release_generated_action(action)
    else:
        action.use_fake_user = True


def _remove_manual_nla_track(anim, track):
    for strip in track.strips:
        _preserve_or_release_action(strip.action)
    anim.nla_tracks.remove(track)


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
        shared_frames = get_shared_frame_markers(scene)
        if shared_frames:
            frame, names = shared_frames[0]
            self.report({'ERROR'}, (
                f"Markers share frame {frame} ({', '.join(names)}); "
                "move one so every clip has its own end frame"))
            return {'CANCELLED'}

        # Stage the complete result alongside the existing tracks. Nothing
        # authored is detached until every object/segment has valid content.
        states = [{
            'obj': obj,
            'anim': obj.animation_data,
            'source': obj.animation_data.action,
            'slot': getattr(obj.animation_data, 'action_slot', None),
            'tracks': list(obj.animation_data.nla_tracks),
            'active_track': obj.animation_data.nla_tracks.active,
        } for obj in objs]
        original_actions = {action.as_pointer() for action in bpy.data.actions}
        total_created = 0
        built_strips = []
        try:
            for seg in segments:
                for state in states:
                    built = _build_nla_track_for_segment(
                        state['obj'],
                        state['source'],
                        state['slot'],
                        seg,
                        track_start=seg['start'],
                        create_boundaries=scene.m2nla_boundary_keys,
                    )
                    if built is None or not built['key_count']:
                        raise ValueError(
                            f"No keyframes for {state['obj'].name} / "
                            f"{seg['name']}. Enable Create Boundary Keys "
                            "or adjust the marker range")
                    built_strips.append((built['strip'], seg['name']))
                    total_created += 1
        except Exception as exc:
            # Also catch partial construction: the builder may have created
            # an Action or track before raising, without returning a result.
            for state in states:
                anim = state['anim']
                original_tracks = {track.as_pointer()
                                   for track in state['tracks']}
                for track in list(anim.nla_tracks):
                    if track.as_pointer() not in original_tracks:
                        anim.nla_tracks.remove(track)
                anim.nla_tracks.active = state['active_track']
            for action in list(bpy.data.actions):
                if (action.as_pointer() not in original_actions
                        and is_generated_action(action)):
                    bpy.data.actions.remove(action)
            self.report({'ERROR'}, f"Conversion cancelled; original animation kept: {exc}")
            return {'CANCELLED'}

        if scene.m2nla_clear_nla:
            for state in states:
                for track in state['tracks']:
                    _remove_manual_nla_track(state['anim'], track)

        # Strip names are unique per owner: a kept or just-removed strip
        # named like a clip forced the new one to "Walk.001". Claim the
        # clip names again now that the cleared strips are gone.
        renamed = []
        for strip, clip_name in built_strips:
            if strip.name != clip_name:
                strip.name = clip_name
            if strip.name != clip_name:
                renamed.append(strip.name)

        if scene.m2nla_unlink_source:
            for obj in objs:
                anim = obj.animation_data
                source = anim.action
                if source is not None:
                    # Detaching can drop the Action's only user. Guarantee
                    # the "preserved in the blend file" behaviour promised
                    # by the Unlink Source Action description.
                    source.use_fake_user = True
                anim.action = None

        if renamed:
            self.report({'WARNING'}, (
                f"Created {total_created} NLA strips; kept NLA strips "
                "already use those clip names, so new strips are named: "
                + ", ".join(renamed[:4])
            ))
            return {'FINISHED'}

        self.report({'INFO'}, f"Created {total_created} NLA strips across {len(objs)} objects")
        return {'FINISHED'}


class MARKERNLA_OT_merge(Operator):
    """Merge NLA strips back into a single action"""
    bl_idname  = "markernla.merge"
    bl_label   = "NLA → Action"
    bl_description = (
        "Combine simple NLA strips into one shared action, one clip per "
        "strip name. Clips that overlap are placed one after another, with "
        "a marker at each clip's end (ignores repeat, reverse, blending, "
        "influence, and modifiers)"
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

        # One Action with a Slot per object keeps clips that span several
        # objects together, the way Markers → NLA and shared Actions use them.
        name = (f"{objs[0].name}_Merged" if len(objs) == 1 else "NLA_Merged")
        merged = merge_nla_to_action(objs, name=name, scene=scene)
        if merged is None:
            if all(track.mute for obj in objs
                   for track in obj.animation_data.nla_tracks):
                # Unchecked tracks in the NLA editor are muted, and merging
                # skips muted tracks like playback does.
                self.report({'ERROR'}, (
                    "All NLA tracks are muted; check the tracks to merge "
                    "in the NLA editor"))
            else:
                self.report({'ERROR'}, "No keyframes found in NLA strips")
            return {'CANCELLED'}

        merged_count = 0
        for obj in objs:
            slot = find_action_slot(merged, obj)
            if slot is None:
                continue

            if scene.m2nla_clear_nla:
                for trk in list(obj.animation_data.nla_tracks):
                    _remove_manual_nla_track(obj.animation_data, trk)

            _preserve_or_release_action(obj.animation_data.action)
            obj.animation_data.action = merged
            obj.animation_data.action_slot = slot
            merged_count += 1

        self.report({'INFO'}, (
            f"Merged NLA into {merged.name} for {merged_count} objects"))
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
        if not _run_fbx_export(self, scene):
            return {'CANCELLED'}

        return _finish_export(
            self, scene, f"Exported FBX → {self.filepath}")


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
        if not _run_glb_export(self, scene):
            return {'CANCELLED'}

        return _finish_export(
            self, scene, f"Exported GLB → {self.filepath}")


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
        "Restore the timeline range: Start = First Clip Start, "
        "End = last marker frame"
    )
    bl_options = {'INTERNAL'}

    def execute(self, context):
        scene = context.scene
        scene.frame_start = scene.m2nla_start_frame
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
    """Remove all NLA tracks from the selected objects"""
    bl_idname  = "markernla.cleanup"
    bl_label   = "Cleanup NLA"
    bl_description = (
        "Remove every NLA track from the selected objects. Actions this "
        "addon generated are released; hand-authored Actions are preserved "
        "with a fake user and stay in the blend file"
    )
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
                _remove_manual_nla_track(obj.animation_data, trk)
                removed += 1

        self.report({'INFO'}, f"Removed {removed} NLA track(s)")
        return {'FINISHED'}


# ============================================================
