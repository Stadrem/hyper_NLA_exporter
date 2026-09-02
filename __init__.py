"""Hyper NLA Exporter package entry point."""

bl_info = {
    "name": "Hyper NLA Exporter",
    "author": "Kim Dongsu",
    "version": (2, 4, 3),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > K-Quick Tools",
    "description": (
        "Place timeline markers to define animation clips, "
        "then export FBX/GLB with automatic split – no NLA hassle"
    ),
    "category": "Animation",
}

# Convenience re-exports for the local Blender test scripts and any helper
# script that drives the addon directly. Everything else stays inside its
# own module; registration imports the operator and panel classes itself.
from .action_utils import (
    _ensure_channelbag,
    _get_fcurves,
    copy_segment_to_action,
    merge_nla_to_action,
)
from .clips import get_marker_segments
from .export_utils import collect_export_issues, collect_split_issues
from .nla_split import _temporary_nla_split
from .registration import register, unregister

if __name__ == "__main__":
    register()
