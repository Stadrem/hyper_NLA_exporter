# Goal Description

Implement three new workflow enhancements to the Hyper NLA Exporter addon:
1. **Mute/Ignore Clips**: Add a toggle to skip specific clips during export.
2. **Only Deform Bones**: Add a setting to optimize exports by excluding non-deforming bones (e.g., controllers).
3. **Inline Marker Management**: Allow users to rename and delete markers directly from the addon UI panel without navigating the timeline.

## User Review Required
No breaking changes. The UI will be slightly updated to accommodate the new buttons.

## Proposed Changes

### `__init__.py`

#### 1. Mute/Ignore Clips Toggle
* **Registration**: Add a custom property `m2nla_muted = BoolProperty()` to `bpy.types.TimelineMarker` during addon registration.
* **Segment Parsing**: Update `get_marker_segments` to include the actual `TimelineMarker` object in the returned dictionary.
* **NLA Split Logic**: In `_temporary_nla_split`, add a check: `if seg['marker'].m2nla_muted: continue`. This ensures muted segments are completely skipped during action splitting and NLA track creation.

#### 2. Game Optimization: Only Deform Bones
* **Property**: Add `m2nla_only_deform_bones = BoolProperty(default=False)` to `bpy.types.Scene`.
* **Export Logic**: 
  * In FBX export kwargs, set `use_armature_deform_only = scene.m2nla_only_deform_bones`.
  * In GLB export kwargs, set `export_def_bones = scene.m2nla_only_deform_bones`.
* **UI**: Add a checkbox for `Only Deform Bones` in the **Settings** box.

#### 3. Inline Marker Renaming & Deletion
* **New Operator**: Create `MARKERNLA_OT_delete_marker` which takes a `marker_name` property and removes the corresponding marker from `scene.timeline_markers`.
* **UI Panel Update (`MARKERNLA_PT_panel`)**: Redesign the marker segment row to display the following inline controls:
  1. `[Eye Icon]` Mute Toggle (`marker.m2nla_muted`)
  2. `[Play Icon]` Preview Segment Button
  3. `[Text Field]` Marker Name (allows direct typing/renaming)
  4. `[Text Label]` Frame Range & Duration
  5. `[Trash Icon]` Delete Marker Button

## Verification Plan

### Manual Verification
- **UI Test**: Verify that the marker rows render correctly with icons, text fields, and delete buttons.
- **Rename Test**: Type a new name in the UI text field and ensure the marker on the timeline updates immediately.
- **Delete Test**: Click the trash icon and ensure the marker is deleted.
- **Mute Test**: Toggle the eye icon on a segment and run Quick Export GLB/FBX. Verify that the exported file does not contain the muted clip.
- **Deform Bones Test**: Enable "Only Deform Bones" and export. Check the resulting file in a 3D viewer or engine to confirm controller bones are stripped out.
