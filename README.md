# Mocha Pro → Flame Export

Adds a **Flame Export** option to Mocha Pro, so a matte exported with
**File > Export Rendered Clip** or **File > Export Rendered Shapes** drops
straight into a running Autodesk Flame or Flare session — into a Library or the
open Batch — as soon as the export finishes.

Works with the Mocha Pro **plugin** (as used from Flame) and with **standalone**
Mocha Pro. Mocha's own export dialogs are untouched; the option lives in a small
**File > Flame Export** submenu directly above Export Rendered Clip.

It also adds a **Flame Export** column to Mocha's **Track** tab, with an
**Export GMask** button that sends the roto **shapes** to Flame as a GMask Tracer
node, and an **Export Alembic** button that sends a layer's **mesh track** to
Flame as an Action. See **Exporting roto shapes** and **Exporting a mesh track**
below.

## Requirements

- **Mocha Pro 2026.5 or later**, plugin or standalone.
- **Autodesk Flame or Flare 2025.2 or later.**
- **Logik Backdoor 1.0.0 or later**, installed in your Flame — see below. This
  is required; the import talks to Flame through it.

**macOS only.** Linux is not supported yet. So far this has only been
tested with **Mocha Pro 2026.5 on macOS**, and it may not work with earlier
versions of Mocha.

## Logik Backdoor (Required)

This is required to allow this tool to 'talk' to Flame. 

- Download it from the **Logik Portal** 
  website: <https://logik-portal.com/scripts/logik_backdoor>, or
- Get it from the **Logik Portal** app inside Flame
  (Flame main menu → **Logik → Logik Portal**), listed under the Python scripts.

Follow Logik Backdoor's own install instructions. Once installed it loads
automatically every time Flame or Flare starts — nothing else to launch. By
default it lives at `/opt/Autodesk/shared/python/logik_backdoor`, which is the
path the installer offers by default.

## Install

Run Mocha Pro (or the Mocha Pro plugin) at least once first, so its settings
folder exists. Then, on **macOS**, double-click `install.command` or run:

```bash
python3 install.py
```

If macOS refuses to open `install.command` because it is from an unidentified
developer, right-click it and choose **Open**, or run `python3 install.py` from
Terminal in this folder instead.

The installer needs `python3`. A Mac without Apple's Command Line Tools will
offer to install them the first time `python3` is run; accept, then run the
installer again.

The installer finds things for you and only asks when it has to:

- **Logik Backdoor** — if not found in the default location you will be prompted 
  for the path.  `/opt/Autodesk/shared/python/logik_backdoor`
- **Which Mocha to set up** — it asks *"Install for standalone Mocha Pro?"* and
  *"Install for the OFX plugin?"*, defaulting to Yes for whichever it detects.
  Answer for one or both.

**Restart Mocha** (and Flame, for the plugin) to see the new submenu.

macOS only for now. Linux uses a different startup mechanism.

### Updating

Just **re-run the installer** — it replaces the earlier install cleanly. No need
to uninstall first.

### Uninstall

```bash
python3 install.py --uninstall
```

This removes the integration from both flavours and the added module.

## Using it

In Mocha's **File** menu, a **Flame Export** submenu appears directly above
**Export Rendered Clip**:

![The Flame Export submenu in Mocha's File menu](images/Mocha%20Menu.png)

| Item | What it shows / does |
| --- | --- |
| **Import to Flame after export** | Tick to import automatically when an export finishes. |
| **Destination: Library / Batch** | Import into a Media Panel library, or onto a reel in the open Batch. |
| **Destination Name: …** | Name of the library or reel to import into. Created if it does not exist. |
| **Flame** | `Running (version)` when a Flame/Flare session is open, else `Not running`. |
| **Logik Backdoor** | `Found` when the bridge is installed, else `Not found`. |

Tick the box, choose the destination and name, then use **File > Export Rendered
Clip** or **File > Export Rendered Shapes** exactly as before. A small window
appears showing the frame count as the export writes; when it finishes, the clip
lands in Flame and a confirmation appears. Cancelling the export imports nothing.

- Both **Export Rendered Clip** (the processed footage) and **Export Rendered
  Shapes** (the roto mattes) are supported.
- An exported image sequence is imported as **one clip**, whatever its length —
  the tool waits for all frames to finish writing first.
- The toggle **greys out** unless both Flame/Flare *and* Logik Backdoor are
  detected — so you can only tick it when it will actually work.
- Your last choices (toggle, destination, name) are **remembered** between
  Mocha sessions and versions.

## Exporting to GMask Tracer

Besides the rendered-media import above, the tool can send the **roto shapes**
straight to Flame as a Gmask Tracer node.

On Mocha's **Track** tab, a **Flame Export** column is added beside Export Data.
Its **Export GMask** button makes a **GMask Tracer** node named
`mocha_gmask_tracer` in Flame, loaded with a `.mask` setup. Choose **Basic** or
**Shape & Axis** output in the dialog.

![The Flame Export column on Mocha's Track tab](images/Mocha%20Track%20Tab.png)

If Flame isn't running, or Logik Backdoor can't be found, you're told as soon as
you press the button, before choosing any layers. If the Batch already has a node
with that name, a number is added (`mocha_gmask_tracer1`).

Clicking it asks which layers to export — **Selected**, **All visible**,
**All layers**, or a **single layer** — then exports the shapes and creates the node
in the open Batch.

**Mask ML layers are not supported for GMask Tracer export.** 
Mocha's AI-based Mask ML shapes cannot be exported as a GMask Tracer. They
have to be rendered out and exported. 

## Exporting a mesh track via Alembic

The **Flame Export** column's second button, **Export Alembic**, sends a layer's
**mesh track** to Flame as animated geometry in an Action node.

1. Track the layer with **Mesh** checked under **Motion** on the Track tab. The
   button is only enabled while Mesh is checked.
2. Select that one layer and press **Export Alembic**.

Mocha writes the mesh track as an Alembic file, and Flame creates an **Action**
named `mocha_alembic` in the open Batch with:

- the animated mesh imported as Action objects,
- the Action's resolution set to the Mocha clip's, and the clip's frame rate,
- the **Mocha camera** as the Action's Result camera.

**In the Mocha OFX plugin, the Action/GMask Tracer nodes won't appear in Flame until 
you exit Mocha.** Flame holds the import while the plugin is open. Standalone Mocha 
isn't affected in this way.

## License

GPL-3.0-or-later.
