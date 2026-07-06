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

* ⚡ **Marker-Based Auto-Splitting**: Define clip names and end frames using standard timeline markers. The addon automatically calculates starts and ends.
* 🚀 **One-Click Quick Export**: Automatically split, retime to frame 1, export, and clean up temporary tracks in a single operation.
* 🔄 **Non-Destructive Design**: Keeps your active action and workspace entirely untouched. All splitting, retiming, and NLA generation are handled in temporary memory.
* 📐 **Boundary Key Evaluation**: Evaluates curve values at segment starts/ends to insert missing boundaries, preserving perfect poses across splits.
* ⚙️ **Advanced Manual NLA Tools**: Easily convert timeline markers to permanent NLA tracks, merge NLA tracks back into a single Action, or run selective cleanups.

---

## 🛠️ Panel Interface Overview

Located in the 3D Viewport > Sidebar (N-Panel) > **K-Quick Tools** tab under the **Hyper NLA Exporter** panel:

```
┌──────────────────────────────────────────┐
│ ▼ 🎬 Hyper NLA Exporter                  │
├──────────────────────────────────────────┤
│ ┌─ Marker Segments ──────────────────┐   │
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
│ └────────────────────────────────────┘   │
│                                          │
│ ┌─ Quick Export (Marker Split) ──────┐   │
│ │      [   FBX   ]      [   GLB   ]      │   │
│ └────────────────────────────────────┘   │
│                                          │
│ [▶ Manual NLA Tools]                     │
└──────────────────────────────────────────┘
```

* **Marker Segments**: Displays parsed timeline markers and provides inline management.
  * *Mute Toggle (Eye Icon)*: Exclude specific clips from Quick Export without deleting the marker.
  * *Preview (Play Icon)*: Set the timeline playback range to this segment for a quick preview.
  * *Rename/Delete*: Rename markers inline via the text field or delete them instantly via the trash icon.
  * *Reset Range*: Restores the timeline playback range to cover the entire animation (from frame 0 to the last marker).
* **Targets**: Displays how many active animated objects will be processed and the active action name.
* **Settings**:
  * *Only Deform Bones*: Automatically strips out control bones during export, optimizing the file size for game engines.
  * *Create Boundary Keys*: Evaluates curve endpoints and keys missing frames to prevent pose drift.
  * *Selected Only*: Processes only active selection.
* **Quick Export (Marker Split)**:
  * *FBX*: Splits and exports as separate takes in a single `.fbx` file.
  * *GLB*: Splits and exports as separate clips in a single `.glb` file.
* **Manual NLA Tools (Foldout)**: Contains permanent conversion actions (`Markers → NLA` and `NLA → Action`), existing NLA exporters, and cleanups.

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
   * **Marker Name** = Clip/Take Name.
   * **Marker Frame** = End frame of the clip.
   * *Example*: Marker `Walk` at frame 60 and `Run` at frame 120 splits the timeline into `1-60` (Walk) and `61-120` (Run).
4. Open the N-Panel, click **K-Quick Tools** > **Hyper NLA Exporter**.
5. Click **FBX** or **GLB** under Quick Export and select your save location. Your animations are instantly split, retimed from frame 1, and exported!

---

## ⚠️ Technical Notes & Constraints

1. **GLB/glTF Hierarchy Flattening & Scale Preservation**:
   * The `Quick Export GLB` function forces `use_selection=False` internally.
   * This is required by Blender's glTF exporter to correctly resolve and flatten skeletal mesh parent-child hierarchies in NLA mode. Forcing selection breaks this, causing mesh duplication or misplaced attachments.
   * It also automatically disables `export_rest_position_armature` to preserve the active pose bone scale (e.g. 100x scales), preventing joints from resetting to a 1.0 scale during export.
2. **Blender 5.1 Layered Action Architecture**:
   * Fully compatible with Blender 5.x's Slot, Layer, Strip, and Channelbag systems to prevent naming conflicts across multiple characters.

---

## 📁 File Structure

* `__init__.py`: Handles addon registration, bl_info metadata definition, and module reloading.

---

## 📄 License

This project is licensed under the GNU GPL v3.0 License. See the [LICENSE](file:///c:/Users/user/AppData/Roaming/Blender%20Foundation/Blender/5.1/scripts/addons/hyper_NLA_exporter/LICENSE) file for details.
