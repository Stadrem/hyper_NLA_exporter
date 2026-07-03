bl_info = {
    "name": "Hyper NLA Exporter",
    "author": "Kim Dongsu",
    "version": (2, 0, 0),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > K-Quick Tools",
    "description": (
        "Place timeline markers to define animation clips, "
        "then export FBX/GLB with automatic split – no NLA hassle"
    ),
    "category": "Animation",
}


import bpy
from contextlib import contextmanager
from bpy.props import BoolProperty, StringProperty
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
                    cb_slot = getattr(cb, 'slot', getattr(cb, 'action_slot', None))
                    if slot is None or cb_slot == slot:
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
            slot = action.slots.get(datablock.name)
            if not slot:
                if hasattr(action.slots, 'new_for_id'):
                    slot = action.slots.new_for_id(datablock)
                else:
                    slot = action.slots.new(id_type='OBJECT', name=datablock.name)
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
    seg_start = scene.frame_start

    for marker in markers:
        if marker.frame < seg_start:
            continue
        segments.append({
            "name": marker.name,
            "start": seg_start,
            "end": marker.frame,
            "length": marker.frame - seg_start + 1,
        })
        seg_start = marker.frame + 1

    return segments


# ============================================================
#  Action splitting / merging
# ============================================================

def copy_segment_to_action(source_action, dst_action, start, end,
                           create_boundaries=True, datablock=None):
    """Copy keyframes from *source_action* within [start, end] into *dst_action*.

    Keyframes are re-timed so the clip starts at frame 0.
    *datablock* – if given, a slot is created/used for this ID.
    Returns True if any keyframes were added.
    """
    src_fcurves = _get_fcurves(source_action)
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


def merge_nla_to_action(obj, name="Merged"):
    """Merge all NLA strips back into a single Action."""
    anim = obj.animation_data
    if anim is None:
        return None

    merged = bpy.data.actions.new(name=name)
    merged.use_fake_user = True
    dst_cb = _ensure_channelbag(merged, datablock=obj)

    dst_map = {}
    has_any = False

    for track in anim.nla_tracks:
        for strip in track.strips:
            if strip.action is None:
                continue

            offset = strip.frame_start
            src_fcurves = _get_fcurves(strip.action)

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
                    f = src_kp.co[0] + offset
                    new_kp = dst_fc.keyframe_points.insert(
                        frame=f, value=src_kp.co[1], options={'FAST'})
                    new_kp.interpolation     = src_kp.interpolation
                    new_kp.easing            = src_kp.easing
                    new_kp.handle_left_type  = src_kp.handle_left_type
                    new_kp.handle_right_type = src_kp.handle_right_type
                    new_kp.handle_left  = (src_kp.handle_left[0]  + offset,
                                           src_kp.handle_left[1])
                    new_kp.handle_right = (src_kp.handle_right[0] + offset,
                                           src_kp.handle_right[1])
                    has_any = True

    for fc in dst_map.values():
        fc.update()

    if not has_any:
        bpy.data.actions.remove(merged)
        return None

    return merged


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
            'temp_tracks': []
        })

    segments = get_marker_segments(scene)
    clip_names = set()
    boundary_keys = scene.m2nla_boundary_keys

    # Backup original scene frame range
    orig_frame_start = scene.frame_start
    orig_frame_end = scene.frame_end
    
    # Calculate max segment length to cover all animations
    max_len = max((seg['length'] for seg in segments), default=1)

    for state in object_states:
        obj = state['obj']
        anim = state['anim']
        original_action = state['original_action']

        for seg in segments:
            # Action name includes object prefix to avoid collisions
            # across different rigs. NLA Track name stays as marker name
            # (that's what glTF uses as the animation clip name).
            action_name = f"{obj.name}_{seg['name']}"
            new_action = bpy.data.actions.new(name=action_name)
            new_action.use_fake_user = True
            
            did_copy = copy_segment_to_action(
                original_action, new_action, seg['start'], seg['end'],
                create_boundaries=boundary_keys,
                datablock=obj,
            )
            
            if did_copy:
                slot = None
                if hasattr(new_action, 'slots'):
                    slot = new_action.slots.get(obj.name)

                track = anim.nla_tracks.new()
                track.name = seg['name']
                strip = track.strips.new(
                    name=seg['name'],
                    start=1,  # Always start at frame 1 for the exported clip
                    action=new_action,
                )
                strip.name = seg['name']
                if slot and hasattr(strip, 'action_slot'):
                    strip.action_slot = slot
                state['temp_tracks'].append((track, new_action))
                clip_names.add(seg['name'])
            else:
                bpy.data.actions.remove(new_action)

        # Detach the source action so the NLA strips are what gets exported.
        state['anim'].action = None

    # Temporarily set scene range to cover the longest segment from frame 1
    scene.frame_start = 1
    scene.frame_end = max_len

    bpy.context.view_layer.depsgraph.update()
    bpy.context.view_layer.update()
    current_frame = scene.frame_current
    scene.frame_set(current_frame)

    try:
        yield list(clip_names)
    finally:
        # Restore scene frame range
        scene.frame_start = orig_frame_start
        scene.frame_end = orig_frame_end

        for state in object_states:
            anim = state['anim']
            for track, action in state['temp_tracks']:
                anim.nla_tracks.remove(track)
                action.use_fake_user = False
                action.user_clear()
                try:
                    bpy.data.actions.remove(action)
                except Exception:
                    # Force-remove even if references linger
                    try:
                        bpy.data.actions.remove(action, do_unlink=True)
                    except Exception:
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

    def execute(self, context):
        scene = context.scene
        all_objs = list(context.selected_objects if scene.m2nla_selected_only else context.scene.objects)
        anim_objs = [o for o in all_objs if o.animation_data and o.animation_data.action]

        if not anim_objs:
            self.report({'ERROR'}, "No valid objects with animation data found")
            return {'CANCELLED'}

        with _temporary_nla_split(anim_objs, scene) as clip_names:
            if not clip_names:
                self.report({'ERROR'}, "No keyframes found in marker segments")
                return {'CANCELLED'}

            try:
                bpy.ops.export_scene.fbx(
                    filepath=self.filepath,
                    use_selection=scene.m2nla_selected_only,
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
        return {'FINISHED'}


class MARKERNLA_OT_quick_export_glb(Operator, ExportHelper):
    """One-click marker-split GLB export – original animation untouched"""
    bl_idname      = "markernla.quick_export_glb"
    bl_label       = "Quick Export GLB"
    bl_description = (
        "Split by markers → export GLB → restore original action. "
        "Each marker segment becomes a separate animation clip"
    )

    filename_ext  = ".glb"
    filter_glob: StringProperty(default="*.glb", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return len(context.scene.timeline_markers) > 0

    def execute(self, context):
        scene = context.scene
        objs = list(
            context.selected_objects if scene.m2nla_selected_only
            else context.scene.objects
        )
        anim_objs = [o for o in objs
                     if o.animation_data and o.animation_data.action]

        if not anim_objs:
            self.report({'ERROR'}, "No valid objects with animation data found")
            return {'CANCELLED'}

        with _temporary_nla_split(anim_objs, scene) as clip_names:
            if not clip_names:
                self.report({'ERROR'}, "No keyframes found in marker segments")
                return {'CANCELLED'}

            kwargs = dict(
                filepath=self.filepath,
                export_format='GLB',
                export_animations=True,
                export_animation_mode='NLA_TRACKS',
            )

            # IMPORTANT: Always use use_selection=False for glTF.
            # The glTF exporter in NLA_TRACKS mode needs the full
            # scene hierarchy to correctly resolve skinned mesh
            # parenting (flatten meshes out of armature nodes).
            # Manipulating selection breaks this flattening and
            # causes mesh duplication / misplaced nodes.
            try:
                bpy.ops.export_scene.gltf(
                    use_selection=False, **kwargs)
            except TypeError:
                try:
                    kwargs.pop('export_animation_mode', None)
                    kwargs['export_nla_strips'] = True
                    bpy.ops.export_scene.gltf(
                        use_selection=False, **kwargs)
                except Exception as exc:
                    self.report({'ERROR'}, f"GLB export failed: {exc}")
                    return {'CANCELLED'}
            except Exception as exc:
                self.report({'ERROR'}, f"GLB export failed: {exc}")
                return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Exported {len(clip_names)} clips → {self.filepath}"
        )
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
        "and push them as NLA strips"
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
                )
                
                if did_copy:
                    slot = None
                    if hasattr(new_action, 'slots'):
                        slot = new_action.slots.get(obj.name)

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
        "Combine all NLA strips into one action, placing keyframes "
        "at their original timeline positions"
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
            merged = merge_nla_to_action(obj, name=f"{obj.name}_Merged")
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

    def execute(self, context):
        scene = context.scene
        try:
            bpy.ops.export_scene.fbx(
                filepath=self.filepath,
                use_selection=scene.m2nla_selected_only,
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

    def execute(self, context):
        scene = context.scene
        kwargs = dict(
            filepath=self.filepath,
            export_format='GLB',
            export_animations=True,
            export_animation_mode='NLA_TRACKS',
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
            col = box.column(align=True)
            for seg in segments:
                row = col.row(align=True)
                row.label(text=seg['name'], icon='ACTION')
                row.label(text=f"{seg['start']} → {seg['end']}  ({seg['length']}f)")
        else:
            col = box.column(align=True)
            col.label(text="Place markers on the timeline", icon='INFO')
            col.label(text="  Marker name  = clip name")
            col.label(text="  Marker frame = clip end frame")

        # ── Target info ───────────────────────────────
        box = layout.box()
        objs = context.selected_objects if scene.m2nla_selected_only else context.scene.objects
        valid_objs = [o for o in objs if o.animation_data]
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
        col.prop(scene, "m2nla_boundary_keys")
        col.prop(scene, "m2nla_selected_only")

        layout.separator()

        # ── Quick Export (main feature) ──────────────────────
        box = layout.box()
        box.label(text="Quick Export (Marker Split)", icon='EXPORT')
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
    MARKERNLA_OT_quick_export_fbx,
    MARKERNLA_OT_quick_export_glb,
    MARKERNLA_OT_convert,
    MARKERNLA_OT_merge,
    MARKERNLA_OT_export_fbx,
    MARKERNLA_OT_export_glb,
    MARKERNLA_OT_cleanup,
    MARKERNLA_PT_panel,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    S = bpy.types.Scene
    S.m2nla_boundary_keys = BoolProperty(
        name="Create Boundary Keys",
        description=(
            "Evaluate the curve at segment start/end and insert keyframes "
            "there if they are missing.  Ensures each clip has clean "
            "first and last poses"
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
        description="Export only selected objects",
        default=True,
    )
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
        "m2nla_boundary_keys",
        "m2nla_clear_nla",
        "m2nla_unlink_source",
        "m2nla_selected_only",
        "m2nla_show_nla_tools",
    )
    for p in props:
        if hasattr(S, p):
            delattr(S, p)


if __name__ == "__main__":
    register()
