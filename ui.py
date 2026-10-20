"""3D View sidebar UI for Hyper NLA Exporter."""

from bpy.props import BoolProperty
from bpy.types import Panel, PropertyGroup

from .clips import get_marker_segments, get_shared_frame_markers
from .export_utils import _get_quick_export_targets

#  UI Panel
# ============================================================

class MARKERNLA_PG_ui_state(PropertyGroup):
    """Transient panel expansion state."""

    show_nla_tools: BoolProperty(
        name="Show NLA Tools",
        description="Show advanced manual NLA conversion tools",
        default=False,
    )


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
        box.prop(scene, "m2nla_start_frame", text="First Clip Start")

        segments = get_marker_segments(scene)
        if segments:
            name_counts = {}
            for seg in segments:
                if not getattr(seg['marker'], "m2nla_muted", False):
                    name = seg['marker'].name
                    name_counts[name] = name_counts.get(name, 0) + 1
            has_duplicates = any(c > 1 for c in name_counts.values())
            has_short_clips = any(
                seg['length'] < 2
                and not getattr(seg['marker'], "m2nla_muted", False)
                for seg in segments)

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

                range_row = row.row(align=True)
                range_row.alert = not is_muted and seg['length'] < 2
                range_row.label(
                    text=f"{seg['start']}~{seg['end']} ({seg['length']}f)")

                del_op = row.operator("markernla.delete_marker", text="", icon='TRASH', emboss=False)
                del_op.marker_name = marker.name
                del_op.marker_frame = marker.frame

            if has_duplicates:
                box.label(text="⚠️ Duplicate unmuted marker names!", icon='ERROR')
            if has_short_clips:
                box.label(text="⚠️ Clips need at least 2 frames!", icon='ERROR')
            # A second marker on the same frame has no row above: its clip
            # would be dropped, so name it here.
            for frame, names in get_shared_frame_markers(scene):
                row = box.row()
                row.alert = True
                row.label(
                    text=f"⚠️ Frame {frame} has {len(names)} markers: "
                         + ", ".join(names),
                    icon='ERROR')

            row = box.row(align=True)
            row.operator("markernla.reset_frame_range", icon='LOOP_BACK')
        else:
            col = box.column(align=True)
            col.label(text="Place markers on the timeline", icon='INFO')
            col.label(text="  Marker name  = clip name")
            col.label(text="  Marker frame = clip end frame")

        # ── Target info ───────────────────────────────
        box = layout.box()
        quick_targets = _get_quick_export_targets(context)
        box.label(text=f"Quick Export: {len(quick_targets)} Actions", icon='OBJECT_DATA')
        
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

        format_note = box.row()
        has_multiple_targets = len(quick_targets) > 1
        has_shape_animation = any(target.id_type == 'KEY'
                                  for target in quick_targets)
        format_note.alert = has_multiple_targets or has_shape_animation
        format_note.label(
            text=("Shape Key animation: use GLB" if has_shape_animation
                  else "FBX: One rig only · GLB: Multi-rig"),
            icon='ERROR' if format_note.alert else 'INFO',
        )

        layout.separator()

        # ── Manual NLA Tools (advanced) ──────────────────────
        box = layout.box()
        ui_state = scene.m2nla_ui_state
        nla_tools_icon = (
            'TRIA_DOWN' if ui_state.show_nla_tools else 'TRIA_RIGHT'
        )
        header = box.row()
        header.prop(ui_state, "show_nla_tools",
                    text="Manual NLA Tools",
                    icon=nla_tools_icon,
                    emboss=False)

        if ui_state.show_nla_tools:
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
