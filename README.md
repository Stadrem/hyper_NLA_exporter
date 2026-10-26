🌐 [English](README.md) | 🇰🇷 [한국어](README.ko.md)

# 🎬 Hyper NLA Exporter

A professional, non-destructive animation workflow utility for Blender. Effortlessly split a single timeline animation into multiple distinct clips (Takes/Clips) using timeline **markers** and export them to FBX or GLB in one click—completely bypassing the manual NLA track creation headache.

> [!IMPORTANT]
> **Intended Use Case**: This addon was specifically developed for exporting **Unity FBX Animation Takes** and **Web-based GLB NLA Animations**. We do not guarantee correct operation or support for any other use cases outside of these environments.

<p align="center">
  <img src="https://img.shields.io/badge/Blender-5.1+-306EE8?logo=blender&logoColor=white&style=for-the-badge" alt="Blender Version">
  <img src="https://img.shields.io/badge/Format-FBX%20%2F%20GLB-E04E39?style=for-the-badge" alt="Format support">
  <img src="https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge" alt="License">
</p>

---

## 🌟 Key Features

* ⚡ **Marker-Based Auto-Splitting**: Define clip names and end frames using standard timeline markers. Set **First Clip Start** in the panel, and the addon calculates every segment automatically.
* 🚀 **One-Click Quick Export**: Automatically split, retime to frame 1, export, and clean up temporary tracks in a single operation.
* 💾 **Auto Export (Auto Save)**: Skip the file browser and save a predictable, overwrite-ready FBX or GLB beside your `.blend` file (or in a folder you choose). A failed export never replaces the previous file.
* 🔄 **Non-Destructive Design**: Keeps your active action and workspace entirely untouched. All splitting, retiming, and NLA generation are handled in temporary memory.
* 📐 **Boundary Curve Preservation**: Inserts missing segment boundaries, trims Bezier handles, keeps automatic handles of keys that sit on a marker, and bakes cut easing curves per frame, so both poses and curve motion remain faithful across splits.
* ✅ **Export Safety**: Checks duplicate or blank clip names, clips shorter than 2 frames, markers sharing a frame, invalid markers, missing Action Slots/F-Curves, empty clip ranges, and skinned meshes outside the export selection. An Action with no keyframes is ignored instead of counting as an export target. Existing NLA tracks on every object and Shape Key in the export scope are temporarily isolated during Quick Export and restored afterward, including owners that have NLA but no active Action.
* 📂 **Open Export Folder**: Opens the containing folder automatically after a successful FBX/GLB export.
* ⚙️ **Advanced Manual NLA Tools**: Easily convert timeline markers to permanent NLA tracks, merge NLA tracks back into a single Action, or run selective cleanups.

---

## 🛠️ Panel Interface Overview

Located in the 3D Viewport > Sidebar (N-Panel) > **K-Quick Tools** tab under the **Hyper NLA Exporter** panel:

```
┌──────────────────────────────────────────┐
│ ▼ 🎬 Hyper NLA Exporter                  │
├──────────────────────────────────────────┤
│ ┌─ Marker Segments ──────────────────┐   │
│ │ First Clip Start: [ 1 ]            │   │
│ │ 👁 [▶] [ Walk       ] 1~60 (60f) 🗑 │   │
│ │ 👁 [▶] [ Run        ] 61~120(60f) 🗑 │   │
│ │ [Reset Range]                      │   │
│ └────────────────────────────────────┘   │
│                                          │
│ ┌─ Targets: 1 Objects ───────────────┐   │
│ │  Active Action: Rig_Action         │   │
│ └────────────────────────────────────┘   │
│                                          │
│ ┌─ Settings ─────────────────────────┐   │
│ │ [ ] Only Deform Bones              │   │
│ │ [x] Create Boundary Keys           │   │
│ │ [x] Selected Only                  │   │
│ │ [x] Open Folder After Export       │   │
│ └────────────────────────────────────┘   │
│                                          │
│ ┌─ Quick Export (Marker Split) ──────┐   │
│ │    [Check FBX]      [Check GLB]     │   │
│ │      [   FBX   ]      [   GLB   ]      │   │
│ │ FBX: One rig only · GLB: Multi-rig │   │
│ └────────────────────────────────────┘   │
│                                          │
│ [▶ Manual NLA Tools]                     │
└──────────────────────────────────────────┘
```

* **Marker Segments**: Displays parsed timeline markers and provides inline management.
  * *First Clip Start*: Sets the source frame where the first marker clip begins. The default is frame 1; exported clips are still retimed to begin at frame 1.
  * *Mute Toggle (Eye Icon)*: Exclude specific clips from Quick Export without deleting the marker.
  * *Preview (Play Icon)*: Set the timeline playback range to this segment for a quick preview.
  * *Rename/Delete*: Rename markers inline via the text field or delete them instantly via the trash icon.
  * *Reset Range*: Restores the timeline playback range from **First Clip Start** to the last marker.
* **Targets**: Displays how many active animated objects will be processed and the active action name.
* **Settings**:
  * *Export Path*: Sets the FBX/GLB output folder. The default `//Export/` means an `Export` folder beside the saved `.blend` file; the folder is created automatically.
  * *Auto Export (Auto Save)*: Skips the file browser and overwrites `<blend filename>.fbx` or `<blend filename>.glb` directly in **Export Path**. Save the `.blend` file first: its filename determines the export name, and relative paths such as `//Export/` are resolved beside it. This option applies to **Quick Export (Marker Split)**; turn it off to choose a filename and location in the normal file browser.
  * Every export is first written to a temporary folder beside the target. It replaces the existing file only if Blender's exporter reports success and the new file is not empty, so a cancelled or failed export keeps the last good file.
  * *Only Deform Bones*: Automatically strips out control bones during export, optimizing the file size for game engines.
  * *Create Boundary Keys*: Evaluates curve endpoints and keys missing frames to prevent pose drift. With it off, every FBX/GLB clip still spans its full marker segment; curves hold their first/last key value up to the clip edges.
  * *Selected Only*: Processes only the active selection. For Quick Export, all descendants of the selected objects are temporarily included so the skinned hierarchy remains complete in both FBX and GLB.
  * *Open Folder After Export*: Opens the exported file's containing folder after a successful export.
  * *GLB Draco Compression*: Compresses GLB meshes with Draco (`KHR_draco_mesh_compression`) and exposes the compression level and quantization bits. Applies to every GLB export (Quick Export and Export existing NLA); FBX is unaffected. The target engine needs a Draco decoder (e.g. glTFast with the Draco package in Unity). If Blender's Draco library is missing, the GLB is exported uncompressed with a warning.
* **Quick Export (Marker Split)**:
  * The format note below the buttons warns in red when the current export scope contains multiple animated targets. FBX supports one animated rig; GLB supports multi-rig scenes.
  * *Check FBX / Check GLB*: Performs a temporary NLA split and shows expected/created track counts. Objects whose clips are all fine collapse into one `✓` line; only objects with problems get a box listing their `⚠` or `✗` clips. Long lists are capped in the popup, and the full list is printed to the System Console. It validates Action/Strip content, names, frame ranges, Action Slots, keyframes, and hierarchy, then removes all temporary data. Hard errors also block Quick Export. Objects with no keys inside a clip (e.g. Empties that move in only some clips) are summarized once per clip: as information while Create Boundary Keys holds their pose, and as a warning when it is off, because those objects are then left out of that clip.
  * *FBX*: Splits one animated object into separate takes in a single `.fbx` file. Select the animated rig plus any non-animated mesh hierarchy; multiple objects with active Actions are blocked because Blender's FBX exporter does not merge their same-named takes safely.
  * *GLB*: Splits and exports as separate clips in a single `.glb` file, including multiple animated rigs in the same scene.
* **Manual NLA Tools (Foldout)**: Contains permanent conversion actions (`Markers → NLA` and `NLA → Action`), existing NLA exporters, and cleanups.
  * *NLA → Action*: Merges the selected objects into one Action with a Slot per object. Strips with the same name form one clip; clips stacked on the same frames (for example Yes/No variants) are placed one after another, and each clip gets one marker at its end so `Markers → NLA` can split it again. Each strip range is copied like an exported clip, so a curve whose keys end early holds its value until the clip ends instead of easing into the next clip. Muted (unchecked) NLA tracks are skipped.

---

## 🚀 Installation

1. Download the repository as a `.zip` file.
2. Open Blender, go to Edit > Preferences > Addons.
3. Click Install... at the top right and select the downloaded `.zip` file.
4. Search for "Hyper NLA Exporter" in the list and check the checkbox to activate it.

---

## 📖 How to Use

1. Save your `.blend` file (relative path resolution).
2. Select your animated rig/object(s).
3. Place timeline markers to define your animation cuts:
   * **First Clip Start** = Source frame where the first clip begins (default: `1`).
   * **Marker Name** = Clip/Take Name.
   * **Marker Frame** = End frame of the clip.
   * *Example*: Marker `Walk` at frame 60 and `Run` at frame 120 splits the timeline into `1-60` (Walk) and `61-120` (Run).
4. Open the N-Panel, click **K-Quick Tools** > **Hyper NLA Exporter**.
5. Set **Export Path** if needed. For repeat exports, enable **Auto Export**: after saving the `.blend`, clicking **FBX** or **GLB** immediately overwrites `<blend filename>.fbx` or `.glb` in that folder. Leave it off to choose a filename and location in the normal file browser.

---

## ⚠️ Technical Notes & Constraints

1. **GLB/glTF Hierarchy Flattening & Scale Preservation**:
   * With `Selected Only` enabled, Quick Export temporarily selects every descendant of the selected objects and exports with `use_selection=True`. This applies to both FBX and GLB, so selecting a rig alone never drops its skinned meshes. Only the objects the addon selected are deselected afterwards, leaving the original selection untouched.
   * Select the rig's root object to include its skinned meshes and attachments, preventing missing hierarchy nodes, duplicated meshes, or misplaced attachments in NLA track mode.
   * With `Selected Only` disabled, the entire scene is exported.
   * It also automatically disables `export_rest_position_armature` to preserve the active pose bone scale (e.g. 100x scales), preventing joints from resetting to a 1.0 scale during export.
2. **Clips must be at least 2 frames long**:
   * A marker placed on **First Clip Start**, or two markers on adjacent frames, produces a 1-frame clip. Blender cannot create a zero-length NLA strip and would widen it to 2 frames, so the exported take would no longer match the marker layout.
   * Preflight reports these clips by name and blocks the export; the panel marks the offending row in red. Move the marker at least one frame later, or mute it with the eye icon.
   * Two markers on the **same** frame cannot both end a clip, so one of them would silently disappear. Preflight and Markers → NLA report the frame and marker names as an error, and the panel lists them in red. Move one marker, or mute both.
3. **Empty Actions are ignored, wrong slots are not**:
   * A skinned mesh that carries a leftover Action with no keyframes is not an export target. Without this, that mesh would count as a second animated object and block FBX Quick Export, even though it contributes nothing.
   * If an Action *does* hold F-Curves but the object points at a slot that has none, the object would export without its animation. That stays a preflight error naming the object and the Action.
4. **The export does not depend on the playhead**:
   * Blender's FBX exporter writes each bone's default `Lcl Translation` / `Lcl Rotation` from the pose evaluated at the current frame. A viewer or engine that falls back to those defaults for a bone would show one clip holding another clip's pose, depending on where the playhead happened to sit at export time.
   * Quick Export pins the playhead to **First Clip Start** *before* it builds the temporary split: the scene is evaluated there once with the existing NLA, and again after that NLA is muted. Constant values the split writes into every clip (un-keyed bone transforms such as a Root scale of 100, driver results, values left by the muted NLA) are therefore read at **First Clip Start**, not at wherever the playhead was. The playhead stays there during export and is restored afterwards, so the same scene always produces the same file.
5. **Blender 5.1 Layered Action Architecture**:
   * Supports Blender 5.x's Slot, Layer, Strip, and Channelbag systems. When multiple objects share one Action, only the F-Curves from each object's assigned Action Slot are split.
6. **Hierarchy-wide marker splitting**:
   * Quick Export validates and splits the same visible descendant hierarchy that it exports. Selecting an unanimated parent also finds its animated children. Multiple animated descendants trigger the same FBX single-object restriction as multiple directly selected objects.
7. **F-Curve modifiers**:
   * Active modifiers such as Cycles and Noise, and sampled curves, are evaluated in source time and baked at one-frame intervals. Their clip endpoints are included even with Create Boundary Keys off. Ordinary keyframed curves retain their Bezier interpolation; muted curves and groups are excluded.
   * Easing interpolations (Quad, Sine, Back, Elastic, …) keep their easing, Back, Amplitude, and Period when a whole key interval is inside the clip. A marker that cuts such an interval cannot reuse the easing equation, so only that part is baked at one-frame intervals.
   * Automatic (Auto, Auto Clamped, Vector) handles depend on the neighbouring keys. When a clip drops a key's neighbour, including a key placed exactly on a marker, its handles are frozen to the original curve's coordinates as Free handles. Keys whose neighbours stay in the clip keep their automatic handles. NLA → Action applies the same rule.
   * Channel groups (for example per-bone groups) are copied into every clip.
8. **Shape Key animation uses GLB**:
   * Quick GLB splits Shape Key Actions into the same marker clips as object and bone animation, including shape-only meshes and meshes beneath the selection.
   * To retain morph targets, exports containing Shape Keys use base meshes: non-armature mesh modifiers are not applied anywhere in that export. Preflight warns about affected meshes. Exports without Shape Keys keep applying modifiers as before; skinning remains supported.
   * Quick FBX blocks animated Shape Keys with an explanation because Blender's per-NLA-take exporter does not synchronize their Actions. Use Quick GLB for combined skeletal and facial clips.
9. **Manual tool data preservation**:
   * Markers → NLA builds every requested clip before replacing existing tracks. Empty or failed clips cancel the conversion and preserve the original animation.
   * Converted strips use Extrapolation **Nothing**, so each track only plays inside its own clip and never covers the clips on the tracks below with its first pose.
   * NLA strip names are unique per object. When Clear Existing NLA removes an old strip named like a clip, the new strip takes the clip name back; kept strips with that name force a `.001` suffix, which the operator reports. Quick Export temporarily renames such existing strips so its clips always carry the marker names.
   * Convert, merge, and cleanup protect hand-authored Actions with a Fake User before removing their references, so they survive saving and reopening. Generated Actions are released when no longer needed.
10. **NLA evaluation and constraints**:
   * Quick Export turns NLA evaluation on for each split object while it exports and restores the setting afterwards, so an object whose NLA evaluation is switched off still exports its motion in FBX.
   * Quick GLB samples each object's clip separately, so a constraint that follows **another animated object** (Copy Location, Child Of, an IK target on a different object, …) exports wrong motion, or none for a constraint-only follower. Preflight warns about these pairs. Bake the follower first with **Object > Animation > Bake Action** using *Visual Keying* and *Clear Constraints*. Constraints between bones of the same armature are not affected.

---

## 📁 File Structure

* `__init__.py`: Package entry point, addon metadata, and compatibility exports.
* `action_utils.py`: Blender 5.1 Action, Slot, Channelbag, split, and merge helpers.
* `clips.py`: Timeline marker-to-clip parsing.
* `export_utils.py`: Preflight validation, export paths, and completion helpers.
* `nla_split.py`: Temporary non-destructive NLA construction for Quick Export.
* `operators.py`: Validation, export, conversion, preview, and cleanup operators.
* `ui.py`: 3D View sidebar panel and transient UI state.
* `registration.py`: Blender classes and RNA property registration.
* `tests/`: Blender background smoke and end-to-end export regression tests.

---

## 📄 License

This project is licensed under the GNU GPL v3.0 License. See the [LICENSE](file:///c:/Users/user/AppData/Roaming/Blender%20Foundation/Blender/5.1/scripts/addons/hyper_NLA_exporter/LICENSE) file for details.
