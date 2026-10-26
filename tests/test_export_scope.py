"""Regression coverage for hierarchy-wide marker exports in Blender."""

from pathlib import Path
import sys
import tempfile

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hyper_NLA_exporter as addon
from hyper_NLA_exporter.export_utils import (
    _get_export_scope, _get_quick_export_targets,
)
from hyper_NLA_exporter.nla_split import _temporary_nla_split
from hyper_NLA_exporter.operators import _POPUP_OBJECT_LIMIT, _draw_preflight
from test_blender_exports import read_glb, read_accessor


def make_object(name, parent=None, animated=True):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    if animated:
        for frame, value in ((1, 0), (10, 9), (11, 100), (20, 109)):
            obj.location.x = value
            obj.keyframe_insert('location', index=0, frame=frame)
        for curve in addon._get_fcurves(obj.animation_data.action):
            for point in curve.keyframe_points:
                point.interpolation = 'LINEAR'
    return obj


def check_glb(path, expected_objects):
    document, binary = read_glb(path)
    animations = {a['name']: a for a in document['animations']}
    assert set(animations) == {'Walk', 'Run'}, animations.keys()
    for name, animation in animations.items():
        channels = animation['channels']
        assert {document['nodes'][c['target']['node']]['name']
                for c in channels} == expected_objects
        for channel in channels:
            sampler = animation['samplers'][channel['sampler']]
            values = read_accessor(document, binary, sampler['output'])
            expected = (0, 9) if name == 'Walk' else (100, 109)
            assert abs(values[0][0] - expected[0]) < 1e-5, values
            assert abs(values[-1][0] - expected[1]) < 1e-5, values


class FakeLayout:
    """Record what the preflight popup draws."""

    def __init__(self, root=None):
        self.root = root or self
        if root is None:
            self.labels = []
            self.boxes = []
        self.alert = False

    def label(self, text="", icon='NONE'):
        self.root.labels.append(text)

    def row(self):
        return FakeLayout(self.root)

    def box(self):
        box = FakeLayout(self.root)
        self.root.boxes.append(box)
        return box

    def separator(self):
        pass


def check_popup_caps_flagged_objects():
    """Only objects with problems get a box, and only a few of them."""
    clips = [{'name': name, 'severity': 'OK', 'message': 'Track/Strip OK'}
             for name in ('Walk', 'Run')]
    objects = []
    for index in range(10):
        broken = dict(clips[1], severity='WARNING',
                      message='track was not created')
        objects.append({'name': f'Broken{index}', 'actual_track_count': 1,
                        'expected_track_count': 2,
                        'clips': [dict(clips[0]), broken]})
    objects += [{'name': f'Fine{index}', 'actual_track_count': 2,
                 'expected_track_count': 2,
                 'clips': [dict(clip) for clip in clips]}
                for index in range(20)]
    split_result = {'actual_track_count': 50, 'expected_track_count': 60,
                    'expected_clip_names': ['Walk', 'Run'],
                    'objects': objects}
    issues = [('WARNING', f'issue {index}') for index in range(30)]
    layout = FakeLayout()
    _draw_preflight(layout, issues, split_result, [])
    assert len(layout.boxes) == _POPUP_OBJECT_LIMIT, len(layout.boxes)
    assert '20 object(s): all 2 clip(s) Track/Strip OK' in layout.labels
    assert any(text.startswith('… 18 more') for text in layout.labels)
    assert any(text.startswith('… 4 more object(s)') for text in layout.labels)
    # OK clips of a flagged object are left out of its box.
    assert not any('Walk' in text for text in layout.labels), layout.labels


def check_keyless_clips(directory):
    """Objects resting in a clip are summarized once per clip.

    A rig-less scene keys Empties that each move in only some clips. With
    boundary keys the resting Empty still holds its pose in the clip, so
    preflight reports it as information instead of one warning per object.
    """
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    movers = [make_object(f'Mover{index}') for index in range(4)]
    resting = []
    for index in range(4):
        obj = bpy.data.objects.new(f'Rest{index}', None)
        bpy.context.scene.collection.objects.link(obj)
        for frame in (1, 10):  # Keys inside Walk only.
            obj.keyframe_insert('location', index=0, frame=frame)
        resting.append(obj)
    for obj in movers + resting:
        obj.select_set(True)

    def keyless_issues():
        return [(level, text) for level, text
                in addon.collect_export_issues(bpy.context, 'GLB')
                if 'without keys' in text]

    scene.m2nla_boundary_keys = True
    issues = keyless_issues()
    assert len(issues) == 1, issues
    level, text = issues[0]
    assert level == 'INFO' and text.startswith('Run: 4 object(s)'), issues
    assert text.endswith(', …)'), text  # Long lists are shortened.

    path = Path(directory) / 'keyless.glb'
    assert bpy.ops.markernla.quick_export_glb(filepath=str(path)) == {'FINISHED'}
    document, _binary = read_glb(path)
    run = next(a for a in document['animations'] if a['name'] == 'Run')
    animated = {document['nodes'][c['target']['node']]['name']
                for c in run['channels']}
    assert {obj.name for obj in resting} <= animated, animated

    # Every object is OK, so the dry run collapses into one line instead of
    # one box per object (a tall popup flows into staircase columns).
    with _temporary_nla_split(_get_export_scope(bpy.context),
                              scene) as split_result:
        split_issues = addon.collect_split_issues(split_result)
        layout = FakeLayout()
        _draw_preflight(layout, issues + split_issues, split_result, [])
    assert not layout.boxes, layout.labels
    assert '8 object(s): all 2 clip(s) Track/Strip OK' in layout.labels, (
        layout.labels)

    scene.m2nla_boundary_keys = False
    issues = keyless_issues()
    assert len(issues) == 1 and issues[0][0] == 'WARNING', issues
    assert 'left out of this clip' in issues[0][1], issues
    scene.m2nla_boundary_keys = True


def main():
    addon.register()
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    scene.m2nla_open_folder = False
    scene.m2nla_selected_only = True
    scene.m2nla_auto_export = False
    scene.timeline_markers.new('Walk', frame=10)
    scene.timeline_markers.new('Run', frame=20)
    parent = make_object('Parent')
    child = make_object('Child', parent)
    parent.select_set(True)
    bpy.context.view_layer.objects.active = parent
    source_actions = {obj: obj.animation_data.action for obj in (parent, child)}
    assert set(_get_quick_export_targets(bpy.context)) == {parent, child}
    issues = addon.collect_export_issues(bpy.context, 'FBX')
    assert any(level == 'ERROR' and 'one animated object' in text
               for level, text in issues), issues
    assert not any(level == 'ERROR' for level, _ in
                   addon.collect_export_issues(bpy.context, 'GLB'))
    with tempfile.TemporaryDirectory(prefix='hyper_nla_scope_') as directory:
        path = Path(directory) / 'hierarchy.glb'
        assert bpy.ops.markernla.quick_export_glb(filepath=str(path)) == {'FINISHED'}
        check_glb(path, {'Parent', 'Child'})
        assert set(bpy.context.selected_objects) == {parent}
        for obj, action in source_actions.items():
            assert obj.animation_data.action == action
            assert not obj.animation_data.nla_tracks

        # Selecting an unanimated container must still find animated children.
        parent.animation_data.action = None
        assert _get_quick_export_targets(bpy.context) == [child]
        path = Path(directory) / 'container.glb'
        assert bpy.ops.markernla.quick_export_glb(filepath=str(path)) == {'FINISHED'}
        check_glb(path, {'Child'})
        assert set(bpy.context.selected_objects) == {parent}
        assert not any(level == 'ERROR' for level, _ in
                       addon.collect_export_issues(bpy.context, 'FBX'))
        check_keyless_clips(directory)
    check_popup_caps_flagged_objects()
    addon.unregister()
    print('HYPER_NLA_EXPORT_SCOPE_TESTS_OK')


if __name__ == '__main__':
    main()
