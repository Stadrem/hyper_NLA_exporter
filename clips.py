"""Timeline marker parsing for animation clips."""

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
