"""Operators for validation, export, conversion, preview, and cleanup."""

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper

from .action_utils import (
    _get_channelbag,
    _get_fcurves,
    _preserve_static_transforms,
    copy_segment_to_action,
    merge_nla_to_action,
)
from .clips import get_marker_segments
from .export_utils import (
    _get_quick_export_targets,
    _invoke_export_browser,
    _invoke_quick_export,
    _open_export_folder,
    _preflight_allows_export,
    _prepare_export_destination,
    _remember_export_directory,
    _set_auto_export_filepath,
    _split_allows_export,
    collect_export_issues,
    collect_split_issues,
)
from .nla_split import _temporary_nla_split

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
                # ACTIONS mode respects muted strips. Merge by NLA track name
                # so per-object temporary Actions still become one clip.
                export_animation_mode='ACTIONS',
                export_merge_animation='NLA_TRACK',
                export_anim_single_armature=False,
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
                try:
                    bpy.ops.export_scene.gltf(
                        use_selection=scene.m2nla_selected_only, **kwargs)
                except TypeError:
                    try:
                        kwargs.pop('export_animation_mode', None)
                        kwargs.pop('export_merge_animation', None)
                        kwargs.pop('export_anim_single_armature', None)
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
                for anim, action, slot in active_action_states:
                    anim.action = action
                    if slot is not None:
                        try:
                            anim.action_slot = slot
                        except Exception:
                            pass
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
