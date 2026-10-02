"""Regression coverage for hierarchy-wide marker exports in Blender."""

from pathlib import Path
import sys
import tempfile

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hyper_NLA_exporter as addon
from hyper_NLA_exporter.export_utils import _get_quick_export_targets
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
    addon.unregister()
    print('HYPER_NLA_EXPORT_SCOPE_TESTS_OK')


if __name__ == '__main__':
    main()
