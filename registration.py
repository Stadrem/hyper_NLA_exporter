"""Addon class and RNA property registration."""

import bpy
from bpy.props import BoolProperty, IntProperty, PointerProperty, StringProperty

from .operators import (
    MARKERNLA_OT_cleanup,
    MARKERNLA_OT_convert,
    MARKERNLA_OT_delete_marker,
    MARKERNLA_OT_export_fbx,
    MARKERNLA_OT_export_glb,
    MARKERNLA_OT_merge,
    MARKERNLA_OT_quick_export_fbx,
    MARKERNLA_OT_quick_export_glb,
    MARKERNLA_OT_reset_frame_range,
    MARKERNLA_OT_set_frame_range,
    MARKERNLA_OT_validate_export,
)
from .ui import MARKERNLA_PG_ui_state, MARKERNLA_PT_panel

#  Registration
# ============================================================

_property_classes = (
    MARKERNLA_PG_ui_state,
)

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

_scene_props = (
    "m2nla_only_deform_bones",
    "m2nla_boundary_keys",
    "m2nla_start_frame",
    "m2nla_clear_nla",
    "m2nla_unlink_source",
    "m2nla_selected_only",
    "m2nla_open_folder",
    "m2nla_auto_export",
    "m2nla_export_path",
    "m2nla_draco_enable",
    "m2nla_draco_level",
    "m2nla_draco_position_bits",
    "m2nla_draco_normal_bits",
    "m2nla_draco_texcoord_bits",
    "m2nla_draco_color_bits",
    "m2nla_draco_generic_bits",
    "m2nla_ui_state",
)

# (property suffix, label, glTF default) for Draco quantization bits.
_draco_quantization = (
    ("position", "Position", 14),
    ("normal", "Normal", 10),
    ("texcoord", "Tex Coord", 12),
    ("color", "Color", 10),
    ("generic", "Generic", 12),
)


def _unregister_class_if_registered(cls):
    """Remove a stale class left behind by a live addon reload."""
    existing = getattr(bpy.types, cls.__name__, None)
    registered_class = existing or cls
    if existing is None and not getattr(cls, "is_registered", False):
        return
    try:
        bpy.utils.unregister_class(registered_class)
    except (RuntimeError, ValueError):
        pass


def _clear_registered_properties():
    """Remove RNA definitions before rebuilding addon runtime state."""
    S = bpy.types.Scene
    for prop_name in _scene_props:
        if hasattr(S, prop_name):
            delattr(S, prop_name)

    if hasattr(bpy.types.TimelineMarker, "m2nla_muted"):
        delattr(bpy.types.TimelineMarker, "m2nla_muted")


def register():
    # Clear old panel/operator classes first so a live reload cannot leave
    # a panel drawing against properties from another addon version.
    for cls in reversed(_classes):
        _unregister_class_if_registered(cls)
    _clear_registered_properties()
    for cls in reversed(_property_classes):
        _unregister_class_if_registered(cls)
    for cls in _property_classes:
        bpy.utils.register_class(cls)

    S = bpy.types.Scene

    S.m2nla_ui_state = PointerProperty(type=MARKERNLA_PG_ui_state)

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
    S.m2nla_start_frame = IntProperty(
        name="First Clip Start",
        description=(
            "Source frame where the first marker clip begins; exported "
            "clips are still retimed to start at frame 1"
        ),
        default=1,
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
            "Export only selected objects; Quick Export also includes all "
            "descendants of the selection so skinned meshes are not dropped"
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
    S.m2nla_draco_enable = BoolProperty(
        name="Draco Compression",
        description=(
            "Compress GLB meshes with Draco (KHR_draco_mesh_compression). "
            "The target engine needs a Draco decoder to load the file"
        ),
        default=False,
    )
    S.m2nla_draco_level = IntProperty(
        name="Compression Level",
        description=(
            "Draco compression level (0 = fastest, 6 = smallest; higher "
            "values are currently not supported by the encoder)"
        ),
        default=6,
        min=0,
        max=10,
    )
    for suffix, label, default in _draco_quantization:
        setattr(S, f"m2nla_draco_{suffix}_bits", IntProperty(
            name=f"{label} Bits",
            description=(
                f"Draco quantization bits for {label.lower()} values "
                "(0 = no quantization)"
            ),
            default=default,
            min=0,
            max=30,
        ))
    # During addon enable Blender can expose _RestrictData, which does not
    # provide scene collections. Existing scenes are optional migration only.
    for scene in getattr(bpy.data, "scenes", ()):
        if scene.m2nla_export_path.strip().lower() in {
                "/export", "/export/", "\\export", "\\export\\"}:
            scene.m2nla_export_path = "//Export/"

    # Register UI classes only after every property they draw exists.
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        _unregister_class_if_registered(cls)
    _clear_registered_properties()
    for cls in reversed(_property_classes):
        _unregister_class_if_registered(cls)

