"""Hyper NLA Exporter package entry point."""

bl_info = {
    "name": "Hyper NLA Exporter",
    "author": "Kim Dongsu",
    "version": (2, 4, 1),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > K-Quick Tools",
    "description": (
        "Place timeline markers to define animation clips, "
        "then export FBX/GLB with automatic split – no NLA hassle"
    ),
    "category": "Animation",
}

# Compatibility exports: keep helper access used by existing scripts/tests.
from .action_utils import (
    _ensure_channelbag,
    _get_channelbag,
    _get_fcurves,
    _preserve_static_transforms,
    copy_segment_to_action,
    merge_nla_to_action,
)
from .clips import get_marker_segments
from .export_utils import (
    _default_export_name,
    _export_directory,
    _get_quick_export_targets,
    _invoke_export_browser,
    _invoke_quick_export,
    _open_export_folder,
    _preflight_allows_export,
    _prepare_export_destination,
    _remember_export_directory,
    _set_auto_export_filepath,
    _split_allows_export,
    _with_descendants,
    collect_export_issues,
    collect_split_issues,
)
from .nla_split import _temporary_nla_split
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
from .registration import register, unregister
from .ui import MARKERNLA_PG_ui_state, MARKERNLA_PT_panel

if __name__ == "__main__":
    register()
