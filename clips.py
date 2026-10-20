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
    
    # The first source segment is configurable, while exported clips are
    # still retimed to the standard 1-based animation range.
    seg_start = int(getattr(scene, "m2nla_start_frame", 1))

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


def get_shared_frame_markers(scene):
    """Return ``(frame, [names])`` for clip markers that share a frame.

    Only one marker per frame can end a segment, so get_marker_segments
    drops the others and their clips would vanish from the export without
    a word. Frames where every marker is muted cannot lose a clip.
    """
    first_clip_start = int(getattr(scene, "m2nla_start_frame", 1))
    by_frame = {}
    for marker in scene.timeline_markers:
        if marker.frame >= first_clip_start:
            by_frame.setdefault(marker.frame, []).append(marker)
    return [
        (frame, [marker.name or "<unnamed>" for marker in markers])
        for frame, markers in sorted(by_frame.items())
        if len(markers) > 1 and not all(
            getattr(marker, "m2nla_muted", False) for marker in markers)
    ]


# ============================================================
