# Mocha Flame Export
# Copyright (c) 2026 Michael Vaglienty
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
#
# License:       GNU General Public License v3.0 (GPL-3.0)
#                https://www.gnu.org/licenses/gpl-3.0.en.html

"""
Script Name: Mocha Flame Export
Script Version: 1.0.0
Written by: Michael Vaglienty
Creation Date: 10.04.26
Update Date: 10.04.26

License: GNU General Public License v3.0 (GPL-3.0) - see license file for details

Description:

    Import Mocha's rendered output to Flame to either a Library or the open Batch.

    Export Mocha's roto shapes to Flame as a GMask Tracer node.

    Export Mocha's mesh tracks to Flame as an Alembic (.abc) file in an Action node.

    macOS only. Linux is not supported yet. This has only been tested with
    Mocha 2026.5 on macOS.

Requires:

    Flame 2025.2 or later.
    Mocha 2026.5 or later.
    Logik Backdoor 1.0.0 or later.

Usage:

    Requires the Logik Backdoor to be installed and running in Flame.

    After installing the module, restart Mocha if it is already running.

    To import exported Mocha renders to Flame:

      In Mocha, go to File -> Flame Export and check:Import to Flame after export.

      Then in the same menu select the destination in Flame (Library or Batch) and
      set the name of the destination. 

      Export clips normally as you would in Mocha. Once the export is complete,
      the clips will be imported into the selected destination in Flame.

    To export roto shapes to Flame as a Gmask Tracer node:

        In Mocha, go to the Track tab, in the Flame Export column, click the 
        Export GMask button. A Gmask tracer node will be created in Flame 
        with roto shapes loaded.

    To export mesh tracks to Flame as an Alembic (.abc) file in an Action node:

        In Mocha, go to the Track tab, in the Flame Export column, click the 
        Export Alembic button. A Save window asks where to save the Alembic
        (.abc) file. It opens in the folder last saved to; the first time, in
        the footage's folder (standalone Mocha only), else Mocha's output
        folder, the Mocha project's folder, or your home folder. The file is
        imported into a new Action
        node in Flame. The camera in the action node will be set to the new
        Mocha camera. The action background resolution will be set to the same
        resolution as the Mocha clip. Keep the .abc file where it is, as the
        Action keeps reading it.

        With the Mocha OFX plugin, the Action node will not appear in Flame
        until you exit Mocha.

To install:

    Install the Logik Backdoor in Flame first. 

    Logik Backdoor can be found in the Logik Portal Flame app or here:
    https://logik-portal.com/scripts/#logik_backdoor

    Run install.py in this folder (or double-click install.command on macOS).

    Restart Mocha afterwards. See install.py and readme.md for details.

Notes:

    ML mask layers cannot be exported through GMask Tracer. Their shapes are
    raster based, not vector, so Mocha itself refuses shape-data export for them.

Updates:

    v1.0.0 10.04.26
        - Initial release.
"""

# ==============================================================================
# [Imports]
# ==============================================================================
 
import json
import math
import os
import re
import sys
import threading
import time
import uuid

# ==============================================================================
# [Constants]
# ==============================================================================

SCRIPT_NAME = 'Mocha Flame Export'
SCRIPT_VERSION = 'v1.0.0'

# Absolute path to the installed logik_backdoor folder (the one containing
# logik_backdoor_client.py). The installer rewrites this line to the path the
# user provides, so keep it on its own line exactly in this form.
LOGIK_BACKDOOR_DIR = '/opt/Autodesk/shared/python/logik_backdoor'

# The Mocha flavours this install is for, one or both of 'standalone' and
# 'plugin'. The installer rewrites this line to the flavours the user chose, so
# keep it on its own line exactly in this form. install() runs in every Mocha
# that loads the module (the MOCHA_INIT_SCRIPT variable is global), so it checks
# the running flavour against this set and does nothing for a flavour the user
# did not opt into -- the strict per-flavour opt-out.
ENABLED_FLAVOURS = ('standalone', 'plugin')

# Default name for the Flame Library or Batch reel Mocha imports into. The same
# name is used for both; the artist can override it from the submenu.
DEFAULT_DESTINATION_NAME = 'Mocha_Imports'

# Where the last import choices are remembered. Kept in the user's home so it
# survives Mocha updates, which use a fresh settings file per version.
PREFS_FILE = os.path.expanduser('~/.mocha_flame_export.json')

# Startup diagnostics, appended here so a silently-swallowed init.py error is
# recoverable after the fact. Mocha sends print() from init.py to stdout, which
# is invisible when Mocha is launched from Finder.
LOG_FILE = os.path.expanduser('~/.mocha_flame_export.log')

# Once LOG_FILE passes this size it is moved to LOG_FILE + '.1' (replacing any
# older one) and a fresh log is started, so it never grows without limit.
LOG_MAX_BYTES = 1024 * 1024

# Object names of the File menu and the export actions we wrap, as Mocha builds
# them. Verified live on Mocha Pro 2025.5 and 2026.5. Export Rendered Clip
# ('FileSaveClip') writes the processed footage; Export Rendered Shapes
# ('ExportRenderedShapes') writes the roto mattes. Both write image sequences,
# and we import whatever either one just wrote.
FILE_MENU_NAME = 'MenuFile'
EXPORT_ACTION_NAMES = ('FileSaveClip', 'ExportRenderedShapes')

# Mocha records the export folder and format under an ImgSeq group whose full
# QSettings key path differs by version and by which export ran (verified live
# in the plists):
#   2025.5:         ImgSeq/Directory,                     ImgSeq/Format
#   2026.5 clip:    ExportClip/ExportTo/ImgSeq/Directory,   .../ImgSeq/Format
#   2026.5 shapes:  ExportShapes/ExportTo/ImgSeq/Directory, .../ImgSeq/Format
# so keys are matched by their trailing 'ImgSeq/Directory' / 'ImgSeq/Format'.
# Every matching folder is a candidate; the one that gained files after the
# export trigger is the one imported. The file base name is the clip chosen in
# the dialog and is not stored, so the written files are found by mtime.
EXPORT_DIR_SUFFIX = 'imgseq/directory'
EXPORT_FORMAT_SUFFIX = 'imgseq/format'

# Mocha writes frames as <clip name>_<index>.<ext>. The head must end in a
# non-digit so the whole trailing number is taken as the frame index.
FRAME_PATTERN = re.compile(r'^(.*\D)?(\d+)(\D*)\.([A-Za-z0-9]+)$')

# If the File menu is not built yet when init.py runs, try again this often,
# this many times, before giving up.
MENU_RETRY_MS = 1000
MENU_RETRIES = 10

# Mocha's export writes its frames in the background and the menu action returns
# before they are all on disk, so after an export the module polls the output
# folder and waits until the file count stops growing before importing. Poll
# every SETTLE_POLL_MS; consider the export finished once the count has held
# steady for SETTLE_SECONDS. If nothing appears within NOTHING_SECONDS the export
# was cancelled; IMPORT_TIMEOUT_SECONDS caps a very long render. Polling is done
# with a QTimer so Mocha's UI stays responsive while frames are still writing.
SETTLE_POLL_MS = 500
SETTLE_SECONDS = 2.0
NOTHING_SECONDS = 6.0
IMPORT_TIMEOUT_SECONDS = 900.0

# Mocha's tracking-data exporter that writes a layer's mesh track as one animated
# Alembic mesh (its sibling 'alembic_2D_vertex' writes one point per vertex)
ALEMBIC_EXPORTER = 'alembic_2D_mesh'

# The Track tab's Motion 'Mesh' checkbox, and our Export Alembic button, which is
# enabled only while that box is checked. Mocha rebuilds its Track tab widgets,
# so the button state is re-synced on a short timer rather than via a signal.
MESH_CHECKBOX_NAME = 'chkbxMotionModelMesh'
ALEMBIC_BUTTON_NAME = 'btnFlameExportAlembic'

# In the OFX plugin, Flame holds an Alembic import until the artist returns to
# Flame (clicks it or closes Mocha). If Flame has not replied after this many
# seconds, a note says so.
WAIT_HINT_SECONDS = 2.0
WAIT_HINT_TEXT = (
    'Sent to Flame.\n\n'
    'The Action node will appear in Flame once you exit Mocha.'
    )
ALEMBIC_SYNC_MS = 250

# Everything that must outlive install(): the submenu, its actions, the
# ActionTriggerHandlers, and the post-export poll timer. A collected object takes
# its hook/timer with it, so these are held here for the Mocha session.
_STATE = {
    'menu': None,
    'handlers': [],
    'poll_timer': None,
    'progress_window': None,
    'flame_export_timer': None,
    'alembic_sync_timer': None,
    'alembic_busy': False,
    'name': DEFAULT_DESTINATION_NAME,
    }

# ==============================================================================
# [Qt]
# ==============================================================================

def _diag(message: str) -> None:
    """
    Diag
    ====

    Append a timestamped diagnostic line to LOG_FILE, swallowing any failure.
    Rolls LOG_FILE over to LOG_FILE + '.1' once it passes LOG_MAX_BYTES.

    Args
    ----
        message (str):
            Line to record.
    """

    try:
        if os.path.getsize(LOG_FILE) > LOG_MAX_BYTES:
            os.replace(LOG_FILE, LOG_FILE + '.1')
    except OSError:
        pass

    try:
        with open(LOG_FILE, 'a') as handle:
            handle.write(time.strftime('%Y-%m-%d %H:%M:%S ') + message + '\n')
    except OSError:
        pass

def _flavour() -> str:
    """
    Flavour
    =======

    Report which Mocha this is running inside: 'standalone', 'plugin', or 'unknown'.

    Keys on mocha.APPLICATION_NAME, which is 'mochapro' in standalone Mocha and
    'mochaui' in the OFX plugin (verified live on 2025.5 and 2026.5, and free of
    version numbers). Falls back to the executable / registry-name path, which
    carries 'Plugin' only for the plugin, in case APPLICATION_NAME is ever absent.

    Returns
    -------
        str: 'standalone', 'plugin', or 'unknown'.
    """

    app = ''
    try:
        import mocha

        app = (getattr(mocha, 'APPLICATION_NAME', '') or '').lower()
    except Exception:
        app = ''

    if app == 'mochapro':
        return 'standalone'
    if app == 'mochaui':
        return 'plugin'

    # Fallback: the plugin's paths carry 'plugin'; standalone's do not.
    hay = (sys.executable or '').lower()
    try:
        import mocha

        hay += ' ' + str(getattr(mocha, 'REGISTRY_APPLICATION_NAME', '') or '').lower()
    except Exception:
        pass
    if 'plugin' in hay:
        return 'plugin'
    if 'mocha' in hay:
        return 'standalone'

    return 'unknown'

def _qt() -> tuple:
    """
    Qt
    ==

    Return the Qt classes this module uses, from whichever PySide Mocha ships.

    Mocha 2025.5 bundles PySide2, 2026.5 bundles PySide6, and one init.py serves
    every version. QAction and QActionGroup moved from QtWidgets to QtGui
    between the two, so the lookup is done here rather than at import time.

    Returns
    -------
        tuple: (QtCore, QtWidgets, QAction, QActionGroup).
    """

    try:
        from PySide6 import QtCore, QtGui, QtWidgets

        return QtCore, QtWidgets, QtGui.QAction, QtGui.QActionGroup
    except ImportError:
        from PySide2 import QtCore, QtWidgets

        return QtCore, QtWidgets, QtWidgets.QAction, QtWidgets.QActionGroup

def _main_window():
    """
    Main Window
    ===========

    Return Mocha's main window, or None if it cannot be found.

    Dialogs in the plugin must be parented to it or they open behind Mocha's
    window, where the artist cannot reach them.

    Returns
    -------
        QMainWindow | None: Mocha's main window.
    """

    try:
        from mocha.ui import get_widgets

        return get_widgets()['MainWindow']
    except Exception:
        return None

def _warn(text: str) -> None:
    """
    Warn
    ====

    Show a warning message box and return, never raising.

    Every non-fatal failure in this module ends the same way: the artist is
    told what went wrong in a dialog and Mocha carries on.

    Args
    ----
        text (str):
            Message to show the artist.
    """

    _, QtWidgets, _, _ = _qt()

    QtWidgets.QMessageBox.warning(_main_window(), SCRIPT_NAME, text)

def _progress_window(text: str) -> tuple:
    """
    Progress Window
    ===============

    Show a small non-modal status window and return (window, label).

    Non-modal on purpose: the post-export poll timer runs on the Qt event loop,
    which a modal dialog would block. Returns (None, None) if it cannot be built,
    so the import proceeds regardless.

    Args
    ----
        text (str):
            Initial message to show.

    Returns
    -------
        tuple: (QDialog, QLabel), or (None, None) on failure.
    """

    try:
        QtCore, QtWidgets, _, _ = _qt()

        window = QtWidgets.QDialog(_main_window())
        window.setWindowTitle(SCRIPT_NAME)
        window.setModal(False)

        # Keep it above Mocha without stealing focus from the render.
        window.setWindowFlags(window.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        layout = QtWidgets.QVBoxLayout(window)
        label = QtWidgets.QLabel(text)
        label.setMargin(16)
        layout.addWidget(label)

        window.resize(380, 100)
        window.show()
        window.raise_()
        _STATE['progress_window'] = window

        return window, label
    except Exception as error:
        _diag(f'progress window failed: {error}')

        return None, None

# ==============================================================================
# [Logik Backdoor]
# ==============================================================================

def _has_backdoor(folder: str) -> bool:
    """
    Has Backdoor
    ============

    Report whether a folder holds logik_backdoor_client.py.

    Args
    ----
        folder (str):
            Candidate folder path, possibly empty.

    Returns
    -------
        bool: True if folder is set and contains logik_backdoor_client.py.
    """

    return bool(folder) and os.path.isfile(os.path.join(folder, 'logik_backdoor_client.py'))

def _resolve_backdoor_dir():
    """
    Resolve Backdoor Dir
    ====================

    Return the folder holding logik_backdoor_client.py, or None if it cannot be found.

    The installer bakes the path into LOGIK_BACKDOOR_DIR, so that is tried first
    and is the normal case. Only when it does not hold the client -- a moved
    install, or a machine the installer never touched -- does the artist get a
    one-off folder picker. A picked folder is deliberately not persisted: the
    installer is the persistence mechanism, and this picker only rescues the
    current import.

    Returns
    -------
        str | None: The validated folder, or None if it could not be resolved.
    """

    _, QtWidgets, _, _ = _qt()

    # The path the installer wrote is authoritative when it is actually there.
    if _has_backdoor(LOGIK_BACKDOOR_DIR):
        return LOGIK_BACKDOOR_DIR

    # The baked path is wrong. Let the artist point at the real folder just for
    # this import rather than failing outright.
    picked = QtWidgets.QFileDialog.getExistingDirectory(_main_window(), 'Locate the Logik Backdoor folder')
    if _has_backdoor(picked):
        return picked

    return None

def flame_status() -> tuple:
    """
    Flame Status
    ============

    Report whether a Flame/Flare session is reachable, and its version, silently.

    Reads the session metadata the backdoor already records, so the version is
    had without a round-trip to the running app. When more than one session is
    open it reports the newest, which is the one an import would target. It never
    shows a dialog and never raises: a bad backdoor path, a client that will not
    import, or no live session all read as not running.

    Returns
    -------
        tuple: (running, version) -- a bool and the version string, or
        (False, None) when nothing is reachable.
    """

    if not _has_backdoor(LOGIK_BACKDOOR_DIR):
        return (False, None)

    # Make the client importable, then read its live sessions.
    if LOGIK_BACKDOOR_DIR not in sys.path:
        sys.path.insert(0, LOGIK_BACKDOOR_DIR)

    try:
        import logik_backdoor_client as backdoor

        found = backdoor.sessions()
        if found:
            return (True, found[0].get('version'))

        return (False, None)
    except Exception:
        return (False, None)

# ==============================================================================
# [Export Files]
# ==============================================================================

def _norm_key(key: str) -> str:
    """
    Norm Key
    ========

    Lower-case a settings key with separators flattened, for matching.

    Args
    ----
        key (str): Settings key, e.g. 'ExportClip/ExportTo/ImgSeq/Directory'.

    Returns
    -------
        str: The key lower-cased, with '/' and '\\' turned into '.'.
    """

    return key.replace('/', '.').replace('\\', '.').lower()

def _export_settings() -> tuple:
    """
    Export Settings
    ===============

    Return the candidate export folders and the extension Mocha last used.

    The export dialogs write both to Mocha's settings, so reading them after the
    export tells us where it wrote. The full key path differs by version and by
    export type (see EXPORT_DIR_SUFFIX), so keys are matched by their trailing
    'ImgSeq/Directory' / 'ImgSeq/Format', with the '/' and '.' separators treated
    alike. Every matching folder is returned as a candidate -- there may be one
    for Export Rendered Clip and one for Export Rendered Shapes -- and the caller
    picks the one with freshly written files.

    Returns
    -------
        tuple: (directories, extension) -- a list of candidate folder paths and
        the extension string ('' if unset).
    """

    from mocha import Settings

    settings = Settings()
    dir_suffix = _norm_key(EXPORT_DIR_SUFFIX)
    fmt_suffix = _norm_key(EXPORT_FORMAT_SUFFIX)

    directories = []
    extension = ''
    for key in settings.allKeys():
        norm = _norm_key(key)
        if norm.endswith(dir_suffix):
            value = str(settings.value(key) or '')
            if value:
                directories.append(value)
        elif norm.endswith(fmt_suffix) and not extension:
            extension = str(settings.value(key) or '')

    return directories, extension

def _files_written_since(directory: str, extension: str, since: float) -> list:
    """
    Files Written Since
    ===================

    Return the names of files in a folder modified at or after a moment in time.

    Mocha overwrites an existing export in place, so the modification time is
    the only reliable sign of what this export wrote. The moment is rounded
    down to a whole second because some filesystems store no finer than that.

    Args
    ----
        directory (str):
            Folder to look in.

        extension (str):
            Extension to accept, e.g. '.tif'. Blank accepts any file.

        since (float):
            Time (as from time.time()) the export was triggered.

    Returns
    -------
        list: Sorted file names.
    """

    threshold = math.floor(since)
    extension = extension.lower()
    names = []

    for name in os.listdir(directory):
        if extension and not name.lower().endswith(extension):
            continue
        path = os.path.join(directory, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) >= threshold:
                names.append(name)
        except OSError:
            continue

    return sorted(names)

def _flame_paths(directory: str, names: list) -> list:
    """
    Flame Paths
    ===========

    Turn exported file names into paths Flame can import.

    Frames that share a base name become one Flame bracket path,
    base_[first-last].ext, which Flame imports as a single clip. A file with no
    frame number passes through as itself.

    Args
    ----
        directory (str):
            Folder the files are in.

        names (list):
            File names from _files_written_since.

    Returns
    -------
        list: Sorted absolute paths, one per clip.
    """

    sequences = {}
    paths = []

    # Group frames by everything except the number.
    for name in names:
        match = FRAME_PATTERN.match(name)
        if not match:
            paths.append(os.path.join(directory, name))
            continue
        head, number, tail, ext = match.groups()
        sequences.setdefault((head or '', tail, ext, len(number)), []).append(int(number))

    # One bracket path per group. A lone frame is imported as itself.
    for (head, tail, ext, width), frames in sequences.items():
        first, last = min(frames), max(frames)
        if first == last:
            name = f'{head}{first:0{width}d}{tail}.{ext}'
        else:
            name = f'{head}[{first:0{width}d}-{last:0{width}d}]{tail}.{ext}'
        paths.append(os.path.join(directory, name))

    return sorted(paths)

# ==============================================================================
# [Flame Export]
# ==============================================================================

def send_to_flame(paths: list, target: str, name: str = None) -> None:
    """
    Send To Flame
    =============

    Import Mocha's exported clip(s) into a running Flame session.

    Locates the logik_backdoor client, imports it, confirms a Flame session is
    live, then asks it to bring the media into a Library or the open Batch. The
    result is reported to the artist in a message box either way. This function
    never raises into Mocha: every failure becomes a dialog.

    Args
    ----
        paths (list):
            Paths for the exported file(s) or sequence(s), as from _flame_paths.

        target (str):
            'Library' to import into a Library, or 'Batch' to import onto a reel
            in the open Batch.

        name (str):
            Destination name to use. Blank falls back to DEFAULT_DESTINATION_NAME.
            (Default: None)
    """

    # Find the client. A None here means the baked path is bad and the artist
    # cancelled or mis-picked the folder, so just skip the import.
    backdoor_dir = _resolve_backdoor_dir()
    if backdoor_dir is None:
        _warn('Logik Backdoor not found -- import skipped. Re-run the Mocha Flame Export installer to set the path.')

        return

    # Put the resolved folder on sys.path so the import resolves to this
    # install. A missing or broken client is a skipped import, not a crash.
    if backdoor_dir not in sys.path:
        sys.path.insert(0, backdoor_dir)

    try:
        import logik_backdoor_client as backdoor
    except ImportError as error:
        _warn(f'Could not load Logik Backdoor -- import skipped.\n\n{error}')

        return

    # No point sending anything if nothing is listening.
    if not backdoor.available():
        _warn('No running Flame session found -- is Flame open with Logik Backdoor installed?')

        return

    # Hand the paths to the matching tool. A blank name falls back to the shared
    # default for either destination.
    destination = name or DEFAULT_DESTINATION_NAME
    _diag(f'send_to_flame: target={target} dest={destination!r} paths={paths}')
    if target == 'Batch':
        result = backdoor.call('import_image_to_batch', timeout=600, path=paths, reel_name=destination)
    else:
        result = backdoor.call('import_image_to_library', timeout=600, path=paths, library_name=destination)
    _diag(f'send_to_flame result: {result}')

    _, QtWidgets, _, _ = _qt()

    # Turn the tool's reply into a dialog. On success, name the destination and
    # the clips that landed; on failure, surface the error the tool reported.
    if result.get('ok'):
        clips = result.get('clips') or []
        names = '\n'.join(clips) if clips else '(no clip names returned)'
        QtWidgets.QMessageBox.information(
            _main_window(),
            SCRIPT_NAME,
            f'Flame Export Complete\n\nImported into {destination}:\n\n{names}',
            )
    else:
        QtWidgets.QMessageBox.critical(
            _main_window(),
            SCRIPT_NAME,
            f'Import failed:\n\n{result.get("error")}',
            )

def _new_files_by_dir(started: float) -> dict:
    """
    New Files By Dir
    ================

    Return {directory: [file names]} written at or after the export trigger.

    Looks in every candidate export folder (Export Rendered Clip and Export
    Rendered Shapes may each have their own). The stored format string does not
    always match the real filenames ('.tiff' recorded, '.tif' written), so the
    extension is only a first filter; when it excludes everything the folder is
    rescanned without it, since the modification time is the real discriminator.

    Args
    ----
        started (float):
            Time the export action was triggered.

    Returns
    -------
        dict: Candidate folders that gained files, each mapped to its file names.
    """

    directories, extension = _export_settings()
    if extension and not extension.startswith('.'):
        extension = ''

    found = {}
    for directory in directories:
        if not os.path.isdir(directory):
            continue
        names = _files_written_since(directory, extension, started)
        if not names and extension:
            names = _files_written_since(directory, '', started)
        if names:
            found[directory] = names

    return found

def _do_import(found: dict, target: str, name: str) -> None:
    """
    Do Import
    =========

    Send the files found by _new_files_by_dir to Flame, as one clip per folder.

    Args
    ----
        found (dict):
            {directory: [file names]} from _new_files_by_dir.

        target (str):
            'Library' or 'Batch'.

        name (str):
            Destination name.
    """

    for directory, names in found.items():
        _diag(f'import: {directory!r} -> {len(names)} file(s)')
        send_to_flame(_flame_paths(directory, names), target, name)

def _import_after_export(started: float, target: str, name: str) -> None:
    """
    Import After Export
    ===================

    Wait for Mocha to finish writing the export, then import it into Flame.

    Mocha's export action returns before its frames are all on disk, so this
    polls the output folder with a QTimer (keeping the UI responsive) and imports
    only once the file count has held steady for SETTLE_SECONDS. If nothing
    appears within NOTHING_SECONDS the export was cancelled; IMPORT_TIMEOUT_SECONDS
    caps a very long render.

    Args
    ----
        started (float):
            Time the export action was triggered.

        target (str):
            'Library' or 'Batch'.

        name (str):
            Destination name.
    """

    QtCore, _, _, _ = _qt()

    # A small non-modal window tells the artist the export is being picked up and
    # counts frames as they land. It must be non-modal: a modal dialog would
    # block the event loop the poll timer runs on.
    window, window_label = _progress_window('Exporting frames from Mocha...')

    state = {'prev': -1, 'changed_at': time.time(), 'start': time.time()}
    timer = QtCore.QTimer()
    timer.setInterval(SETTLE_POLL_MS)

    def finish(found: dict, total: int) -> None:
        """Stop polling, close the window, and import (or report a cancel)."""

        timer.stop()
        _STATE['poll_timer'] = None
        if window is not None:
            window.close()
        _STATE['progress_window'] = None
        if total > 0:
            _diag(f'export settled: {total} file(s) after {time.time() - state["start"]:.1f}s')
            try:
                _do_import(found, target, name)
            except Exception as error:
                _diag(f'import error: {error}')
                _warn(f'Flame import failed:\n\n{error}')
        else:
            _diag('import: nothing written (cancelled, or unknown export folder)')

    def check() -> None:
        """Count the frames written so far and finish once the count settles."""

        found = _new_files_by_dir(started)
        total = sum(len(names) for names in found.values())
        now = time.time()

        if total != state['prev']:
            state['prev'] = total
            state['changed_at'] = now

        if window_label is not None:
            if total:
                window_label.setText(f'Exporting frames from Mocha...\n{total} frame(s) written -- importing to Flame when done.')
            else:
                window_label.setText('Waiting for Mocha to export...')

        settled = total > 0 and (now - state['changed_at']) >= SETTLE_SECONDS
        gave_up = total == 0 and (now - state['start']) >= NOTHING_SECONDS
        timed_out = (now - state['start']) >= IMPORT_TIMEOUT_SECONDS

        if settled or gave_up or timed_out:
            finish(found, total)

    timer.timeout.connect(check)

    # Hold the timer so it is not garbage-collected while polling.
    _STATE['poll_timer'] = timer
    timer.start()

# ==============================================================================
# [Preferences]
# ==============================================================================

def _load_prefs() -> dict:
    """
    Load Prefs
    ==========

    Read the remembered import choices, or an empty dict if none are saved.

    Returns
    -------
        dict: Saved preferences, possibly empty. Never raises.
    """

    try:
        with open(PREFS_FILE, 'r') as handle:
            data = json.load(handle)

        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def _save_prefs(enabled: bool, destination: str, name: str) -> None:
    """
    Save Prefs
    ==========

    Remember the current import choices for next time. Never raises.

    Other saved keys, such as the last Alembic folder, are kept.

    Args
    ----
        enabled (bool):
            Whether 'Import to Flame after export' is ticked.

        destination (str):
            The chosen destination, 'Library' or 'Batch'.

        name (str):
            The destination name.
    """

    prefs = _load_prefs()
    prefs.update({'enabled': bool(enabled), 'destination': str(destination), 'name': str(name)})
    try:
        with open(PREFS_FILE, 'w') as handle:
            json.dump(prefs, handle)
    except OSError:
        pass

def _save_alembic_folder(folder: str) -> None:
    """
    Save Alembic Folder
    ===================

    Remember the folder an Alembic file was last saved to. Never raises.

    Other saved keys, such as the menu's import choices, are kept.

    Args
    ----
        folder (str):
            The folder the .abc was saved in.
    """

    prefs = _load_prefs()
    prefs['alembic_folder'] = folder
    try:
        with open(PREFS_FILE, 'w') as handle:
            json.dump(prefs, handle)
    except OSError:
        pass

# ==============================================================================
# [Menu]
# ==============================================================================

def _build_menu() -> bool:
    """
    Build Menu
    ==========

    Add the Flame Export submenu to the File menu and hook the export actions.

    Returns False if Mocha's File menu or neither export action is there yet, so
    the caller can try again once the GUI is up.

    Returns
    -------
        bool: True once the submenu is in place.
    """

    QtCore, QtWidgets, QAction, QActionGroup = _qt()
    from mocha.ui import get_menus, ActionTriggerHandler

    # Already built: init.py is run once per session, but guard anyway.
    if _STATE['menu'] is not None:
        return True

    file_menu = get_menus().get(FILE_MENU_NAME)
    if file_menu is None:
        return False

    actions = file_menu.actions()
    export_actions = [a for a in actions if a.objectName() in EXPORT_ACTION_NAMES]
    if not export_actions:
        return False

    def remember() -> None:
        """Save the current choices."""

        _save_prefs(enabled_action.isChecked(), 'Batch' if batch_action.isChecked() else 'Library', _STATE['name'])

    def rename() -> None:
        """Ask for a new destination name."""

        text, ok = QtWidgets.QInputDialog.getText(
            _main_window(),
            SCRIPT_NAME,
            'Flame destination name (Library or Batch reel):',
            QtWidgets.QLineEdit.Normal,
            _STATE['name'],
            )
        if ok:
            _STATE['name'] = text.strip() or DEFAULT_DESTINATION_NAME
            name_action.setText(f'Destination Name: {_STATE["name"]}...')
            remember()

    def refresh() -> None:
        """Update the status lines and what the artist may change."""

        installed = _has_backdoor(LOGIK_BACKDOOR_DIR)
        running, version = flame_status()

        backdoor_status.setText('Logik Backdoor: ' + ('Found' if installed else 'Not found'))
        if not installed:
            flame_status_action.setText('Flame: unknown')
        elif running:
            flame_status_action.setText(f'Flame: Running ({version})' if version else 'Flame: Running')
        else:
            flame_status_action.setText('Flame: Not running')

        # The option is only usable when both are good; the destination and its
        # name matter only once the box is ticked.
        usable = installed and running
        enabled_action.setEnabled(usable)
        active = usable and enabled_action.isChecked()
        for action in (library_action, batch_action, name_action):
            action.setEnabled(active)

    def after_export(run_original) -> None:
        """Run Mocha's export, then wait for it to finish and import what it wrote."""

        started = time.time()
        run_original()

        try:
            _diag(f'export fired: enabled={enabled_action.isEnabled()} checked={enabled_action.isChecked()}')
            if not (enabled_action.isEnabled() and enabled_action.isChecked()):
                return
            _import_after_export(started, 'Batch' if batch_action.isChecked() else 'Library', _STATE['name'])
        except Exception as error:
            _warn(f'Flame import failed:\n\n{error}')

    prefs = _load_prefs()
    _STATE['name'] = str(prefs.get('name') or DEFAULT_DESTINATION_NAME)

    # ------------------------------------------------------------------------------
    # [Menu Elements]
    # ------------------------------------------------------------------------------

    # Submenu
    submenu = QtWidgets.QMenu('Flame Export', file_menu)

    # Toggle
    enabled_action = QAction('Import to Flame after export', submenu)
    enabled_action.setCheckable(True)
    enabled_action.setChecked(bool(prefs.get('enabled', False)))

    # Destination, one of two
    destination_group = QActionGroup(submenu)
    destination_group.setExclusive(True)
    library_action = QAction('Destination: Library', destination_group)
    library_action.setCheckable(True)
    batch_action = QAction('Destination: Batch', destination_group)
    batch_action.setCheckable(True)
    if prefs.get('destination') == 'Batch':
        batch_action.setChecked(True)
    else:
        library_action.setChecked(True)

    # Destination name
    name_action = QAction(f'Destination Name: {_STATE["name"]}...', submenu)

    # Status lines, read-only
    flame_status_action = QAction('Flame: checking...', submenu)
    flame_status_action.setEnabled(False)
    backdoor_status = QAction('Logik Backdoor: checking...', submenu)
    backdoor_status.setEnabled(False)

    # Signals
    enabled_action.toggled.connect(lambda *_: (remember(), refresh()))
    library_action.toggled.connect(lambda *_: remember())
    batch_action.toggled.connect(lambda *_: remember())
    name_action.triggered.connect(rename)
    submenu.aboutToShow.connect(refresh)

    # ------------------------------------------------------------------------------
    # [Menu Layout]
    # ------------------------------------------------------------------------------

    submenu.addAction(enabled_action)
    submenu.addSeparator()
    submenu.addAction(library_action)
    submenu.addAction(batch_action)
    submenu.addAction(name_action)
    submenu.addSeparator()
    submenu.addAction(flame_status_action)
    submenu.addAction(backdoor_status)

    # Directly above the first export action (Export Rendered Clip): insertMenu
    # puts the submenu before the given action. actions is in menu order, so
    # export_actions[0] is the topmost of the two.
    file_menu.insertMenu(export_actions[0], submenu)

    # Hook every export action with the same handler. The handlers are kept in
    # _STATE so they are never collected -- a dropped handler loses its hook.
    handlers = []
    for action in export_actions:
        handler = ActionTriggerHandler(action)
        handler.handler = after_export
        handlers.append(handler)

    _STATE['menu'] = submenu
    _STATE['handlers'] = handlers
    refresh()

    return True

def _try_build(retries_left: int) -> None:
    """
    Try Build
    =========

    Build the menu now, or schedule another attempt if the GUI is not up yet.

    Args
    ----
        retries_left (int):
            Attempts remaining after this one.
    """

    try:
        if _build_menu():
            _diag('menu built: Flame Export submenu added to the File menu.')
            print(f'{SCRIPT_NAME}: Flame Export submenu added to the File menu.')

            return
    except Exception:
        import traceback

        _diag(f'menu build FAILED:\n{traceback.format_exc()}')
        print(f'{SCRIPT_NAME}: could not add the Flame Export submenu (see {LOG_FILE})')

        return

    if retries_left <= 0:
        _diag('gave up: File menu / export action not found after all retries.')
        print(f'{SCRIPT_NAME}: File menu not found -- giving up.')

        return

    _diag(f'File menu not ready yet -- retrying ({retries_left} left).')
    QtCore, _, _, _ = _qt()
    QtCore.QTimer.singleShot(MENU_RETRY_MS, lambda: _try_build(retries_left - 1))

# ==============================================================================
# [Track Tab Export]
# ==============================================================================

def _ensure_flame_export_column() -> None:
    """
    Ensure Flame Export Column
    ==========================

    Add the Flame Export group to Mocha's Track tab, once it is present.

    Mocha builds the Track tab ('TrackPage') and its 'Export Data' group box
    ('grpbxExport') only when a project is open, and tears them down when it
    closes, so this cannot be injected once at startup. A QTimer calls this every
    couple of seconds instead: it injects only when both the page and the export
    group exist and our own group ('grpbxFlameExport') does not, which makes it a
    no-op on every tick after the first successful add and after the tab is gone.
    Everything is swallowed so a UI change in a future Mocha never reaches Mocha
    as an exception.
    """

    try:
        QtCore, QtWidgets, _, _ = _qt()
        Qt = QtCore.Qt

        for widget in QtWidgets.QApplication.allWidgets():
            if widget.objectName() != 'TrackPage':
                continue

            layout = widget.layout()
            if layout is None:
                continue

            # Find the 'Export Data' group and its grid cell so the new group
            # can sit in the column immediately to its right.
            export_group = None
            cell = None
            for index in range(layout.count()):
                child = layout.itemAt(index).widget()
                if child is not None and child.objectName() == 'grpbxExport':
                    export_group = child
                    cell = layout.getItemPosition(index)
                    break
            if export_group is None:
                continue

            # Idempotent: our group is already in this layout, so leave it be.
            already = any(
                layout.itemAt(i).widget() is not None
                and layout.itemAt(i).widget().objectName() == 'grpbxFlameExport'
                for i in range(layout.count())
                )
            if already:
                continue

            row, col, rspan, cspan = cell

            # Match the export group's width so the two columns line up.
            group = QtWidgets.QGroupBox('Flame Export', widget)
            group.setObjectName('grpbxFlameExport')
            group.setFixedWidth(export_group.width())

            box = QtWidgets.QVBoxLayout(group)
            tracer_button = QtWidgets.QPushButton('Export GMask', group)
            alembic_button = QtWidgets.QPushButton('Export Alembic', group)
            alembic_button.setObjectName(ALEMBIC_BUTTON_NAME)
            alembic_button.setToolTip('Sends the selected layer\'s mesh track to Flame. Enabled when Mesh is checked under Motion.')
            alembic_button.setEnabled(False)
            box.addWidget(tracer_button)
            box.addWidget(alembic_button)
            box.addStretch(1)

            # Wire to the module-level handlers so the buttons keep working after
            # this function returns and its locals go away.
            tracer_button.clicked.connect(export_tracer)
            alembic_button.clicked.connect(export_alembic)

            layout.addWidget(group, row, col + cspan, rspan, 1, Qt.AlignLeft | Qt.AlignTop)
            group.show()
    except Exception as error:
        _diag(f'flame export column injection failed: {error}')

def _sync_alembic_button() -> None:
    """
    Sync Alembic Button
    ===================

    Enable Export Alembic only while the Track tab's Mesh box is checked and no
    Alembic export is waiting for Flame.

    Looks both widgets up afresh on every call, because Mocha replaces its Track
    tab widgets (verified live) and a connection to the old checkbox would go
    quiet. Widgets Mocha has already deleted can still appear in the widget list
    and raise when touched, so each one is guarded. Called by a timer; never raises.
    """

    try:
        _, QtWidgets, _, _ = _qt()

        mesh_checked = False
        buttons = []
        for widget in QtWidgets.QApplication.allWidgets():
            try:
                name = widget.objectName()
                if name == MESH_CHECKBOX_NAME:
                    mesh_checked = mesh_checked or widget.isChecked()
                elif name == ALEMBIC_BUTTON_NAME:
                    buttons.append(widget)
            except RuntimeError:
                continue

        # Also kept off while an Alembic export waits for Flame, so it cannot be
        # sent twice.
        enabled = mesh_checked and not _STATE['alembic_busy']
        for button in buttons:
            if button.isEnabled() != enabled:
                button.setEnabled(enabled)
    except Exception as error:
        _diag(f'alembic button sync failed: {error}')

def _start_flame_export_timer() -> None:
    """
    Start Flame Export Timer
    ========================

    Start the QTimer that keeps the Flame Export group present on the Track tab.

    The timer is held in _STATE so it is not garbage-collected while it runs; a
    dropped timer stops firing and the group would never reappear after a project
    is opened. Called once from install(); guards against starting twice.
    """

    try:
        QtCore, _, _, _ = _qt()

        if _STATE['flame_export_timer'] is not None:
            return

        timer = QtCore.QTimer()
        timer.setInterval(2000)
        timer.timeout.connect(_ensure_flame_export_column)
        _STATE['flame_export_timer'] = timer
        timer.start()

        # A faster timer keeps Export Alembic in step with the Mesh checkbox.
        sync = QtCore.QTimer()
        sync.setInterval(ALEMBIC_SYNC_MS)
        sync.timeout.connect(_sync_alembic_button)
        _STATE['alembic_sync_timer'] = sync
        sync.start()
    except Exception as error:
        _diag(f'flame export timer failed to start: {error}')

def _shape_scope_dialog(tracer_default: str):
    """
    Shape Scope Dialog
    ==================

    Ask the artist which layers to export, returning the choice or None.

    Modal on purpose: the export that follows is synchronous and quick, so there
    is no event loop to keep alive as there is during the import poll. Returns
    None if the artist cancels, or on any failure, so the caller simply stops.

    Args
    ----
        tracer_default (str):
            The 'flame_tracer_*' exporter to pre-select in the dialog's 'Tracer
            output' choice of Basic vs Shape & Axis.

    Returns
    -------
        dict | None: {'scope': 'selected'|'visible'|'all'|'single',
        'layer_name': str | None, 'tracer_variant': str}, or None if
        cancelled. 'tracer_variant' is the chosen 'flame_tracer_*' exporter name.
    """

    try:
        QtCore, QtWidgets, _, _ = _qt()
        import mocha.project

        # The layer names feed the single-layer picker. A failure here just
        # leaves the combo empty; the other scopes still work.
        names = []
        try:
            project = mocha.project.get_current_project()
            names = [layer.get_name() for layer in project.layers]
        except Exception as error:
            _diag(f'scope dialog: could not read layers: {error}')

        # ------------------------------------------------------------------------------
        # [Window Elements]
        # ------------------------------------------------------------------------------

        # Dialog
        dialog = QtWidgets.QDialog(_main_window())
        dialog.setWindowTitle(SCRIPT_NAME)
        layout = QtWidgets.QVBoxLayout(dialog)

        # Scope radios, mutually exclusive with 'All layers' the default
        selected_radio = QtWidgets.QRadioButton('Selected Layers', dialog)
        visible_radio = QtWidgets.QRadioButton('All visible layers', dialog)
        all_radio = QtWidgets.QRadioButton('All layers', dialog)
        single_radio = QtWidgets.QRadioButton('Single layer', dialog)
        all_radio.setChecked(True)

        # Single-layer picker, live only while 'Single layer' is chosen
        layer_combo = QtWidgets.QComboBox(dialog)
        layer_combo.addItems(names)
        layer_combo.setEnabled(False)
        single_radio.toggled.connect(layer_combo.setEnabled)

        # Tracer output variant. The two radios map to Mocha's two Flame Tracer
        # exporters.
        basic_radio = QtWidgets.QRadioButton('Basic', dialog)
        axis_radio = QtWidgets.QRadioButton('Shape && Axis', dialog)
        if tracer_default == 'flame_tracer_basic':
            basic_radio.setChecked(True)
        else:
            axis_radio.setChecked(True)

        # OK / Cancel
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            dialog,
            )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        # ------------------------------------------------------------------------------
        # [Widget Layout]
        # ------------------------------------------------------------------------------

        layout.addWidget(selected_radio)
        layout.addWidget(visible_radio)
        layout.addWidget(all_radio)
        layout.addWidget(single_radio)
        layout.addWidget(layer_combo)
        layout.addWidget(QtWidgets.QLabel('Tracer Shape Output:', dialog))
        layout.addWidget(basic_radio)
        layout.addWidget(axis_radio)
        layout.addWidget(buttons)

        # Twice the natural width so the scope options and layer names read clearly.
        dialog.setMinimumWidth(dialog.sizeHint().width() * 2)

        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None

        if selected_radio.isChecked():
            scope = 'selected'
        elif visible_radio.isChecked():
            scope = 'visible'
        elif single_radio.isChecked():
            scope = 'single'
        else:
            scope = 'all'

        layer_name = layer_combo.currentText() if scope == 'single' else None

        tracer_variant = 'flame_tracer_basic' if basic_radio.isChecked() else 'flame_tracer_shape_and_axis'

        return {'scope': scope, 'layer_name': layer_name, 'tracer_variant': tracer_variant}
    except Exception as error:
        _diag(f'scope dialog failed: {error}')

        return None

def _gather_layers(project, scope: str, layer_name) -> list:
    """
    Gather Layers
    =============

    Return the project layers that match the chosen scope.

    Args
    ----
        project (Project):
            The current Mocha project.

        scope (str):
            One of 'selected', 'visible', 'single', or 'all'.

        layer_name (str | None):
            The layer to match for the 'single' scope; ignored otherwise.

    Returns
    -------
        list: The matching layer objects, possibly empty.
    """

    layers = list(project.layers)

    if scope == 'selected':
        return [layer for layer in layers if layer.get_selected()]
    if scope == 'visible':
        return [layer for layer in layers if layer.get_visibility()]
    if scope == 'single':
        return [layer for layer in layers if layer.get_name() == layer_name]

    return layers

def _connect_backdoor():
    """
    Connect Backdoor
    ================

    Find and import the logik_backdoor client and confirm a Flame session is live.

    Called the moment a shape-export button is pressed, before the scope dialog
    and the export, so a missing backdoor or a closed Flame is reported straight
    away instead of after the artist has already chosen layers. Each failure is a
    warning dialog and a None return, never an exception.

    Returns
    -------
        tuple | None: (client module, backdoor folder), or None if the export
        should stop.
    """

    # Find the client. A None here means the baked path is bad and the artist
    # cancelled or mis-picked the folder, so just skip the export.
    backdoor_dir = _resolve_backdoor_dir()
    if backdoor_dir is None:
        _warn('Logik Backdoor not found -- export skipped. Re-run the Mocha Flame Export installer to set the path.')

        return None

    # Put the resolved folder on sys.path so the import resolves to this install.
    if backdoor_dir not in sys.path:
        sys.path.insert(0, backdoor_dir)

    try:
        import logik_backdoor_client as backdoor
    except ImportError as error:
        _warn(f'Could not load Logik Backdoor -- export skipped.\n\n{error}')

        return None

    # No point exporting anything if nothing is listening.
    if not backdoor.available():
        _warn('No running Flame session found -- is Flame open with Logik Backdoor installed?')

        return None

    return (backdoor, backdoor_dir)

def _slip_tracer_keys(setup_path: str, offset: int) -> int:
    """
    Slip Tracer Keys
    ================

    Move every keyframe in a GMask Tracer '.mask' setup by a number of frames.

    Mocha's Flame Tracer export writes its keys one frame early for Flame, so the
    setup is fixed here, before Flame loads it. Each key in a '.mask' is a
    'Key <n>' block whose first 'Frame <value>' line is the key's frame; only that
    line is changed, for every channel in the file.

    Args
    ----
        setup_path (str):
            Path to the written '.mask' setup. It is rewritten in place.

        offset (int):
            Frames to add to each key, e.g. 1 to move keys one frame later.

    Returns
    -------
        int:
            The number of keys moved.
    """

    with open(setup_path, 'r', encoding='latin-1', newline='') as handle:
        lines = handle.readlines()

    key_line = re.compile(r'^\s*Key\s+\d+\s*$')
    frame_line = re.compile(r'^(\s*Frame\s+)(-?\d+(?:\.\d*)?)(\s*)$')

    moved = 0
    in_key = False
    for index, line in enumerate(lines):
        if key_line.match(line):
            in_key = True
            continue

        match = frame_line.match(line) if in_key else None
        if match:
            # Keep the number's form: an integer frame stays an integer.
            value = match.group(2)
            new_value = str(int(value) + offset) if value.lstrip('-').isdigit() else repr(float(value) + offset)
            lines[index] = f'{match.group(1)}{new_value}{match.group(3)}'
            moved += 1
            in_key = False

    with open(setup_path, 'w', encoding='latin-1', newline='') as handle:
        handle.writelines(lines)

    return moved

def _clear_tracer_clip_names(setup_path: str) -> int:
    """
    Clear Tracer Clip Names
    =======================

    Remove the footage names from a GMask Tracer '.mask' setup.

    Mocha's Tracer template fills each layer's 'FrontClipName' and
    'MatteClipName' with the Mocha clip's name. Flame then shows that footage as
    missing in the node. Emptying the names ('""', as Flame's own Tracer preset
    has them) loads the node with no footage listed, whatever the clip is called.

    Args
    ----
        setup_path (str):
            Path to the written '.mask' setup. It is rewritten in place.

    Returns
    -------
        int:
            The number of clip names cleared.
    """

    with open(setup_path, 'r', encoding='latin-1', newline='') as handle:
        lines = handle.readlines()

    name_line = re.compile(r'^(\s*(?:Front|Matte)ClipName\s+)"[^"]+"(\s*)$')

    cleared = 0
    for index, line in enumerate(lines):
        match = name_line.match(line)
        if match:
            lines[index] = f'{match.group(1)}""{match.group(2)}'
            cleared += 1

    with open(setup_path, 'w', encoding='latin-1', newline='') as handle:
        handle.writelines(lines)

    return cleared

def _call_without_blocking(backdoor, tool: str, timeout: float, wait_message: str = '', **arguments) -> dict:
    """
    Call Without Blocking
    =====================

    Call a backdoor tool while keeping Mocha's event loop running.

    backdoor.call() waits for Flame's reply. Run in the OFX plugin, Flame's
    Alembic import stalled until the artist clicked Flame (2026-10-04), most
    likely because Flame was waiting on the Mocha node while Mocha was blocked
    waiting on Flame. So the call runs on a worker thread and a local event loop
    keeps Mocha answering until the reply arrives. That did not cure the stall
    (Flame waits for the artist to return to it), but Mocha stays usable, and
    wait_message tells the artist what Flame is waiting for.

    Args
    ----
        backdoor (module):
            The logik_backdoor client, as returned by _connect_backdoor.

        tool (str):
            The backdoor tool to call, e.g. 'import_alembic'.

        timeout (float):
            Seconds to wait for Flame's reply.

        wait_message (str):
            Shown in a small window if Flame has not replied after
            WAIT_HINT_SECONDS, and closed when it does. Empty shows nothing.
            (Default: '')

        **arguments:
            The tool's arguments.

    Returns
    -------
        dict: The tool's reply, or {'ok': False, 'error': ...} if the call raised.
        If Mocha is closed before Flame replies, the loop ends early and the
        reply is {'ok': False, 'pending': True, ...}: the request is already
        with Flame, which still carries it out.
    """

    QtCore, QtWidgets, _, _ = _qt()

    reply = {}

    def worker():
        try:
            reply['result'] = backdoor.call(tool, timeout=timeout, **arguments)
        except Exception as error:
            reply['result'] = {'ok': False, 'error': str(error)}

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    # Non-modal and parented to Mocha, so it stays in front of Mocha's window
    # without blocking it. Created up front, shown only if Flame is slow.
    note = None
    if wait_message:
        note = QtWidgets.QMessageBox(_main_window())
        note.setWindowTitle(SCRIPT_NAME)
        note.setText(wait_message)
        note.setModal(False)
    started = time.monotonic()
    shown = []

    # Shown once only, so clicking OK dismisses it for good.
    def check():
        if not thread.is_alive():
            loop.quit()
        elif note is not None and not shown and time.monotonic() - started >= WAIT_HINT_SECONDS:
            note.show()
            shown.append(True)

    # Leave the loop once the worker is done; check every 100 ms.
    loop = QtCore.QEventLoop()
    timer = QtCore.QTimer()
    timer.timeout.connect(check)
    timer.start(100)
    loop.exec()
    timer.stop()

    if note is not None:
        note.close()
        note.deleteLater()

    # Closing Mocha ends the loop while the worker still waits for Flame.
    if 'result' not in reply:
        return {'ok': False, 'pending': True, 'error': 'Mocha closed before Flame replied.'}

    return reply['result']

def _frame_nodes_in_flame(backdoor, node_names: list) -> None:
    """
    Frame Nodes In Flame
    ====================

    Frame Flame's Batch view on the nodes just created, so the artist sees them.

    Depending on where the Batch view is, a new node can land off screen. A
    failure is only logged: the nodes are already in the Batch.

    Skipped in the OFX plugin: Flame crashed twice (2026-10-04) seconds after
    framing an Alembic Action while the Mocha plugin was open inside Flame.

    Args
    ----
        backdoor (module):
            The logik_backdoor client, as returned by _connect_backdoor.

        node_names (list):
            Names of the new nodes, as the backdoor returned them.
    """

    if _flavour() == 'plugin':
        _diag(f'frame_node skipped in the plugin: {node_names}')

        return

    result = backdoor.call('frame_node', timeout=30, node_names=node_names)
    _diag(f'frame_node result: {result}')

def _send_setup_to_flame(backdoor, setup_path: str, node_type: str, node_name: str) -> None:
    """
    Send Setup To Flame
    ===================

    Load an exported shape setup into a new Flame node through the backdoor.

    Asks the already-connected client to create the node from the setup. The
    backdoor deletes the temp setup and its folder itself (remove_setup), so this
    module never touches them. A new GMask Tracer is then saved and reloaded in
    Flame (reload_node_setup), which it needs before its matte input works, and
    the Batch view is framed on the new node.
    Reports the outcome in a dialog and never raises.

    Args
    ----
        backdoor (module):
            The logik_backdoor client, as returned by _connect_backdoor.

        setup_path (str):
            Path to the written setup file handed to Flame.

        node_type (str):
            Flame node type to create, e.g. 'GMask Tracer'.

        node_name (str):
            Name for the new node, e.g. 'mocha_gmask_tracer'. The backdoor adds a
            number if the Batch already has one by that name.
    """

    # remove_setup lets the backdoor clean up the temp file and folder once the
    # node has loaded, so this module leaves the temp tree to it.
    _diag(f'create_node: type={node_type} name={node_name} setup={setup_path!r}')
    result = backdoor.call(
        'create_node',
        timeout=120,
        node_type=node_type,
        setup_path=setup_path,
        remove_setup=True,
        node_name=node_name,
        )
    _diag(f'create_node result: {result}')

    # A GMask Tracer loaded from Mocha's setup shows its matte (0M) as missing
    # until Flame has saved and reloaded the setup, so do that for the new node
    # only, by the unique name create_node gave it.
    if result.get('ok') and node_type == 'GMask Tracer':
        reload = backdoor.call('reload_node_setup', timeout=120, node_name=result.get('node'), node_type=node_type)
        _diag(f'reload_node_setup result: {reload}')
        if not reload.get('ok'):
            _warn(
                f'{node_type} node "{result.get("node")}" was added, but its setup could not be reloaded:\n\n'
                f'{reload.get("error")}\n\nSave and reload the node setup in Flame by hand.'
                )

            return

    _, QtWidgets, _, _ = _qt()

    if result.get('ok'):
        _frame_nodes_in_flame(backdoor, [result.get('node')])
        QtWidgets.QMessageBox.information(
            _main_window(),
            SCRIPT_NAME,
            f'{node_type} node "{result.get("node")}" was added to the current Batch in Flame.',
            )
    else:
        _warn(result.get('error') or 'Flame refused the setup import.')

def _export_shapes_to_flame(exporter_name: str, node_type: str, file_name: str, node_name: str) -> None:
    """
    Export Shapes To Flame
    ======================

    Run the full shape-export workflow and hand the result to Flame.

    Checks the backdoor and Flame first, then asks for the scope, gathers the
    layers, exports them with the named Mocha exporter to a unique temp folder
    under the backdoor, then sends the written setup to the running Flame as a
    new node. Every failure becomes a dialog; nothing raises into Mocha.

    Args
    ----
        exporter_name (str):
            Key into AbstractShapeDataExporter.registered_exporters(),
            e.g. 'flame_tracer_shape_and_axis'. It is pre-selected in the scope
            dialog, and the artist's Basic / Shape & Axis choice replaces it.

        node_type (str):
            Flame node type to create from the setup, e.g. 'GMask Tracer'.

        file_name (str):
            Output file name with the extension the exporter writes,
            e.g. 'tracer_export.mask'.

        node_name (str):
            Name for the node created in Flame, e.g. 'mocha_gmask_tracer'.
    """

    try:
        import mocha.project
        import mocha.exporters
    except Exception as error:
        _diag(f'flame export: mocha unavailable: {error}')
        _warn('This action must be run inside Mocha Pro.')

        return

    # 1. Make sure the backdoor is there and Flame is listening before asking
    # the artist anything, so a problem is reported the moment they click.
    connection = _connect_backdoor()
    if connection is None:
        return
    backdoor, backdoor_dir = connection

    # 2. Pick the scope. A cancel stops here. The same dialog also returns the
    # Basic/Shape & Axis choice, which selects the actual exporter.
    choice = _shape_scope_dialog(tracer_default=exporter_name)
    if choice is None:
        return

    exporter_name = choice['tracer_variant']

    # 3. Gather the layers for that scope.
    try:
        project = mocha.project.get_current_project()
    except Exception as error:
        _diag(f'flame export: no current project: {error}')
        _warn('No Mocha project is open.')

        return

    layers = _gather_layers(project, choice['scope'], choice['layer_name'])
    if not layers:
        _warn('No layers matched the chosen scope -- nothing to export.')

        return

    # Mask ML contours cannot be exported as GMask Tracer shape data. Mocha's own
    # dialog refuses them; do_export would silently fall back to the static
    # reference spline (keyframes with no motion). Detect and refuse the same way,
    # naming the offending layers and pointing at the rendered-matte path, which
    # does carry an ML matte.
    view = mocha.project.View(0)
    ml_layers = []
    for layer in layers:
        try:
            frames = {layer.in_point(view), layer.out_point(view)}
            if any(layer.has_maml_contours(float(frame)) for frame in frames):
                ml_layers.append(layer.get_name())
        except Exception as error:
            _diag(f'flame export: Mask ML check failed for a layer: {error}')
    if ml_layers:
        _warn(
            'Exporting shape data from layers with Mask ML contours is not supported:\n\n'
            + '\n'.join(ml_layers)
            + '\n\nFor Mask ML layers, use the rendered-matte import instead '
            '(Export Rendered Shapes).'
            )

        return

    # 4. Export the shapes to a unique temp folder under the backdoor. The unique
    # name keeps concurrent exports from colliding in the shared temp tree.
    try:
        exporter = mocha.exporters.AbstractShapeDataExporter.registered_exporters()[exporter_name]
    except Exception as error:
        _diag(f'flame export: exporter {exporter_name!r} missing: {error}')
        _warn(f'Mocha has no {exporter_name!r} exporter.')

        return

    temp_dir = os.path.join(backdoor_dir, 'config', 'temp', uuid.uuid4().hex)
    try:
        os.makedirs(temp_dir, exist_ok=True)
        out = os.path.join(temp_dir, file_name)
        exported = exporter.do_export(project, layers, out, [mocha.project.View(0)])

        written = []
        for path, data in exported.items():
            with open(path, 'wb') as handle:
                handle.write(bytes(data))
            written.append(path)
    except Exception as error:
        _diag(f'flame export: do_export failed: {error}')
        _warn(f'Shape export failed:\n\n{error}')

        return

    if not written:
        _warn('The exporter wrote no files -- nothing to send to Flame.')

        return

    # Both the gmask and the tracer mask are a single file; the first written
    # path is the setup.
    setup_path = sorted(written)[0]

    # The Tracer export lands its keys one frame early in Flame, so slip them all
    # one frame later before Flame loads the setup. It also names the Mocha clip
    # as the node's footage, which Flame reports as missing, so clear the names.
    if node_type == 'GMask Tracer':
        try:
            moved = _slip_tracer_keys(setup_path, 1)
            _diag(f'flame export: slipped {moved} tracer key(s) by +1')
            cleared = _clear_tracer_clip_names(setup_path)
            _diag(f'flame export: cleared {cleared} tracer clip name(s)')
        except Exception as error:
            _diag(f'flame export: fixing the tracer setup failed: {error}')
            _warn(f'Could not fix the GMask Tracer setup:\n\n{error}')

            return

    # 5. Hand the setup to Flame.
    _send_setup_to_flame(backdoor, setup_path, node_type, node_name)

def export_tracer() -> None:
    """
    Export Tracer
    =============

    Export the chosen layers as a Flame GMask Tracer setup and load it into Flame.

    Uses the 'flame_tracer_shape_and_axis' exporter -- the shape-and-axis variant
    of Mocha's Flame Tracer export -- which writes a '.mask' setup the GMask Tracer
    node loads. Module-level so the Track-tab 'Export GMask' button can connect to
    it. Never raises: the whole workflow is guarded and any failure becomes a dialog.
    """

    try:
        _export_shapes_to_flame(
            'flame_tracer_shape_and_axis',
            'GMask Tracer',
            'tracer_export.mask',
            'mocha_gmask_tracer',
            )
    except Exception as error:
        _diag(f'export_tracer failed: {error}')
        _warn(f'GMask Tracer export failed:\n\n{error}')

def _flame_frame_rate(rate: float) -> str:
    """
    Flame Frame Rate
    ================

    Turn a Mocha clip frame rate into the string Flame's Alembic import expects.

    Whole rates become '24 fps'; others keep up to three decimals with trailing
    zeros dropped, so 23.976 and 29.97 become '23.976 fps' and '29.97 fps'.

    Args
    ----
        rate (float):
            The clip's frame rate, e.g. 23.976023.

    Returns
    -------
        str: The rate in Flame's form, e.g. '23.976 fps'.
    """

    if abs(rate - round(rate)) < 0.001:
        return f'{round(rate)} fps'

    return f'{rate:.3f}'.rstrip('0') + ' fps'

def _alembic_start_folder(project, clip) -> str:
    """
    Alembic Start Folder
    ====================

    Return the folder the Alembic save dialog opens in.

    Tries, in order: the folder an Alembic was last saved to, the folder of the
    clip's footage (standalone only -- in the OFX plugin that is Flame's frame
    cache), Mocha's output folder, the folder of the saved Mocha project, then
    the home folder. Each lookup is guarded, because the plugin may have no
    footage path or project file (Flame keeps the project in the node).

    Args
    ----
        project (Project):
            The current Mocha project.

        clip (Clip):
            The clip the layer is tracked on.

    Returns
    -------
        folder (str): An existing folder.
    """

    import mocha.project

    candidates = [_load_prefs().get('alembic_folder', '')]

    # Footage folder, except in the plugin, where it is Flame's frame cache
    if _flavour() != 'plugin':
        try:
            candidates.append(os.path.dirname(clip.get_info(mocha.project.View(0)).path))
        except Exception as error:
            _diag(f'alembic export: no footage path: {error}')

    # Mocha output folder
    try:
        candidates.append(project.get_output_dir())
    except Exception as error:
        _diag(f'alembic export: no output folder: {error}')

    # Saved project folder
    candidates.append(os.path.dirname(project.project_file or ''))

    for folder in candidates:
        if folder and os.path.isdir(folder):
            return folder

    return os.path.expanduser('~')

def _ask_alembic_path(project, clip, layer_name: str):
    """
    Ask Alembic Path
    ================

    Ask where to save the Alembic file, suggesting the next unused version.

    The chosen folder is remembered for next time. The dialog opens in
    _alembic_start_folder with the name
    <clip>_<layer>_v001.abc, counting up past any that exist there. Qt asks before
    replacing a file the artist picks by hand.

    Args
    ----
        project (Project):
            The current Mocha project.

        clip (Clip):
            The clip the layer is tracked on.

        layer_name (str):
            Name of the layer being exported.

    Returns
    -------
        path (str | None): The chosen .abc path, or None if the dialog was cancelled.
    """

    _, QtWidgets, _, _ = _qt()

    folder = _alembic_start_folder(project, clip)

    # Keep names filesystem-safe: anything but letters, digits, '-' and '_' becomes '_'
    stem = re.sub(r'[^\w-]+', '_', f'{clip.name}_{layer_name}')
    version = 1
    while os.path.exists(os.path.join(folder, f'{stem}_v{version:03d}.abc')):
        version += 1

    path, _ = QtWidgets.QFileDialog.getSaveFileName(
        _main_window(),
        'Save Alembic for Flame',
        os.path.join(folder, f'{stem}_v{version:03d}.abc'),
        'Alembic (*.abc)',
        )
    if not path:
        return None

    if not path.lower().endswith('.abc'):
        path += '.abc'

    # Start here next time
    _save_alembic_folder(os.path.dirname(path))

    return path

def _export_alembic_to_flame() -> None:
    """
    Export Alembic To Flame
    =======================

    Export the selected layer's mesh track as Alembic and load it into Flame.

    Checks the backdoor and Flame first, then takes the one selected layer,
    confirms it has a mesh track, asks where to save the .abc (starting in the
    footage folder), writes it there and asks Flame to import it into a new Action at the
    clip's resolution and frame rate, with the Mocha camera as its Result camera.
    Every failure becomes a dialog; nothing raises into Mocha.
    """

    try:
        import mocha.project
        import mocha.exporters
        import mocha.ui
    except Exception as error:
        _diag(f'alembic export: mocha unavailable: {error}')
        _warn('This action must be run inside Mocha Pro.')

        return

    # 1. Make sure the backdoor is there and Flame is listening before anything
    # else, so a problem is reported the moment the artist clicks.
    connection = _connect_backdoor()
    if connection is None:
        return
    backdoor, _ = connection

    # 2. A project must be open.
    project = mocha.project.get_current_project()
    if project is None:
        _warn('No Mocha project is open.')

        return

    # 3. Exactly one selected layer, and it must carry a mesh track.
    selected = [layer for layer in project.layers if layer.get_selected()]
    if len(selected) != 1:
        _warn('Select one layer to export. Its mesh track is sent to Flame as Alembic.')

        return
    layer = selected[0]

    if layer.mesh is None:
        _warn(f'Layer "{layer.get_name()}" has no mesh track.\n\nTrack it with Mesh turned on under Motion, then export again.')

        return

    # 4. Read the clip's size and rate before writing anything, so a failure
    # here cannot leave an unused .abc behind.
    clip = layer.tracking_input_clip()
    width, height = clip.frame_size
    frame_rate = _flame_frame_rate(clip.frame_rate)

    # 5. Ask where to save it. Cancelling stops quietly.
    path = _ask_alembic_path(project, clip, layer.get_name())
    if path is None:
        return

    # 6. Write the .abc. The exporter returns the file contents; this module
    # writes them, as for the GMask Tracer export.
    try:
        exporter = mocha.exporters.AbstractTrackingDataExporter.registered_exporters()[ALEMBIC_EXPORTER]
        exported = exporter.do_export(project, layer, path, float(mocha.ui.get_current_frame()), mocha.project.View(0), {})
        for written, data in exported.items():
            with open(written, 'wb') as handle:
                handle.write(bytes(data))
    except Exception as error:
        _diag(f'alembic export: do_export failed: {error}')
        _warn(f'Alembic export failed:\n\n{error}')

        return

    if not os.path.isfile(path):
        _warn('The exporter wrote no Alembic file -- nothing to send to Flame.')

        return

    # 7. Hand it to Flame at the clip's size and frame rate.
    arguments = {
        'path': path,
        'frame_rate': frame_rate,
        'resolution': [int(width), int(height)],
        'node_name': 'mocha_alembic',
        }
    _diag(f'import_alembic: {arguments}')
    _STATE['alembic_busy'] = True
    try:
        result = _call_without_blocking(backdoor, 'import_alembic', 300, wait_message=WAIT_HINT_TEXT, **arguments)
    finally:
        _STATE['alembic_busy'] = False
    _diag(f'import_alembic result: {result}')

    # Mocha is closing and Flame still has the request: nothing to report.
    if result.get('pending'):
        return

    # In the plugin, Flame holds the import until Mocha exits, so a long stay in
    # Mocha runs out the wait. Flame already has the request and still creates
    # the Action, so say that rather than report an error.
    if not result.get('ok') and 'did not respond' in (result.get('error') or '') and _flavour() == 'plugin':
        _, QtWidgets, _, _ = _qt()

        QtWidgets.QMessageBox.information(_main_window(), SCRIPT_NAME, WAIT_HINT_TEXT)

        return

    if result.get('ok'):
        _frame_nodes_in_flame(backdoor, [result.get('node')])

        _, QtWidgets, _, _ = _qt()

        QtWidgets.QMessageBox.information(
            _main_window(),
            SCRIPT_NAME,
            f'Alembic mesh from "{layer.get_name()}" was added to the current Batch in Flame as '
            f'Action "{result.get("node")}".\n\nThe file is kept at:\n{path}',
            )
    else:
        _warn(result.get('error') or 'Flame refused the Alembic import.')

def export_alembic() -> None:
    """
    Export Alembic
    ==============

    Export the selected layer's mesh track as Alembic and load it into Flame.

    Module-level so the Track-tab 'Export Alembic' button can connect to it.
    Never raises: the whole workflow is guarded and any failure becomes a dialog.
    """

    try:
        _export_alembic_to_flame()
    except Exception as error:
        _diag(f'export_alembic failed: {error}')
        _warn(f'Alembic export failed:\n\n{error}')

# ==============================================================================
# [Entry Points]
# ==============================================================================

def install() -> None:
    """
    Install
    =======

    Entry point called from Mocha's init.py at startup. Never raises.
    """

    print(f'{SCRIPT_NAME} {SCRIPT_VERSION}')

    # The MOCHA_INIT_SCRIPT variable is global, so this runs in every Mocha that
    # starts, both flavours. Do nothing unless this flavour was opted into at
    # install time -- the strict per-flavour opt-out.
    flavour = _flavour()
    if flavour not in ENABLED_FLAVOURS:
        _diag(f'skipped: flavour {flavour!r} not in enabled {ENABLED_FLAVOURS}')

        return

    # Record that init.py reached us, and under which Python/Qt, so a failure
    # that never surfaces in Mocha's UI is still diagnosable from LOG_FILE.
    try:
        binding = _qt()[2].__module__.split('.')[0]
    except Exception as error:
        binding = f'unknown ({error})'
    _diag(f'install() called: {SCRIPT_VERSION}, {flavour}, Python {sys.version.split()[0]}, Qt {binding}')

    _try_build(MENU_RETRIES)

    # The Track tab comes and goes with the open project, so its Flame Export
    # column is kept in place by a timer rather than injected once here.
    _start_flame_export_timer()
