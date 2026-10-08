#!/usr/bin/env python3
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
Creation Date: 09.16.26
Update Date: 10.04.26

License: GNU General Public License v3.0 (GPL-3.0) - see license file for details

Module: Installer
Flame Version: 2025.2
Runs In: Standalone

Description:

    Installs the Mocha Flame Export integration into Mocha Pro 2026.5 and later,
    standalone and/or the OFX plugin used in Flame.

    Mocha is a compiled application with no source to patch; it loads a Python
    startup script. The two flavours load it differently:

        - The OFX plugin runs a Scripts/init.py from its application-data folder.
        - Standalone Mocha does NOT run that init.py -- it only honours the
          MOCHA_INIT_SCRIPT environment variable.

    So the installer asks which flavours to set up (defaulting to the ones it
    detects) and, per flavour:

        - Standalone: loads the module via MOCHA_INIT_SCRIPT, set at login by a
          per-user LaunchAgent (and set immediately, so no logout is needed).
        - Plugin: writes a marked loader block into its Scripts/init.py, so a
          plugin-only install needs no login item.

    The module is copied once into a private folder with its LOGIK_BACKDOOR_DIR
    and ENABLED_FLAVOURS baked in. Because MOCHA_INIT_SCRIPT is global, the
    module self-gates on the running flavour: it does nothing in a Mocha whose
    flavour was not selected -- a strict per-flavour opt-out.

    Paths are auto-detected. The installer prompts for a path only when it is not
    found where expected; a found default is used without asking. --backdoor-dir
    and --plugin-scripts override without prompting.

    macOS only for now. Linux uses a different startup mechanism.

Usage:

    Double-click 'install.command', or from a terminal:

        python3 install.py                       # install (interactive)
        python3 install.py --uninstall           # reverse everything
        python3 install.py --backdoor-dir PATH   # override, no prompt
        python3 install.py --plugin-scripts PATH # override, no prompt

    Restart Mocha (and Flame, for the plugin) afterwards.

Updates:

    v1.0.0 10.04.26
        - Initial release. Per-flavour opt-in with auto-detected paths, strict
          opt-out via runtime flavour gating.
"""

# ==============================================================================
# [Imports]
# ==============================================================================

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

# ==============================================================================
# [Constants]
# ==============================================================================

SCRIPT_NAME = 'Mocha Flame Export'
SCRIPT_VERSION = 'v1.0.0'

# The module and the init entry that loads it, and where they are installed.
MODULE_NAME = 'mocha_flame_export.py'
INIT_NAME = 'mocha_init.py'
INSTALL_DIR = os.path.expanduser('~/Library/Application Support/Logik Mocha Flame Export')

# The environment variable Mocha reads for its startup script, and the
# LaunchAgent that sets it at login.
ENV_VAR = 'MOCHA_INIT_SCRIPT'
AGENT_LABEL = 'com.logik.mocha-flame-export'
AGENT_PLIST = os.path.expanduser(f'~/Library/LaunchAgents/{AGENT_LABEL}.plist')

# Default logik_backdoor folder.
BACKDOOR_DIR_DEFAULT = '/opt/Autodesk/shared/python/logik_backdoor'
BACKDOOR_CLIENT = 'logik_backdoor_client.py'

# Where each flavour is looked for, and the plugin's Scripts folder.
BORISFX_APPDATA = os.path.expanduser('~/Library/Application Support/BorisFX')
STANDALONE_APP_GLOB = '/Applications/BorisFX/Mocha Pro *.app'
PLUGIN_OFX_GLOB = '/Library/OFX/Plugins/BorisFX/MochaPro*'
PLUGIN_SCRIPTS_DEFAULT = os.path.join(BORISFX_APPDATA, 'Mocha Pro Plugin', 'Scripts')

# Markers bracketing the plugin's Scripts init.py loader block.
MARKER_BEGIN = '# [logik_backdoor] Mocha Flame Export -- begin'
MARKER_END = '# [logik_backdoor] Mocha Flame Export -- end'

# The init entry Mocha runs via MOCHA_INIT_SCRIPT. Adds the install folder to
# sys.path and loads the module, which self-gates on the running flavour.
INIT_ENTRY = '''# Mocha Flame Export -- loaded via MOCHA_INIT_SCRIPT. Safe to ignore.
import sys, traceback
_install_dir = {install_dir!r}
if _install_dir not in sys.path:
    sys.path.insert(0, _install_dir)
try:
    import mocha_flame_export
    mocha_flame_export.install()
except Exception:
    traceback.print_exc()
'''

# The plugin Scripts init.py block, the same loader keyed off the install folder.
INIT_BLOCK = '''{begin}
import sys as _sys, traceback as _tb
_install_dir = {install_dir!r}
if _install_dir not in _sys.path:
    _sys.path.insert(0, _install_dir)
try:
    import mocha_flame_export
    mocha_flame_export.install()
except Exception:
    _tb.print_exc()
{end}'''

# The LaunchAgent that exports the variable at login.
AGENT_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/launchctl</string>
        <string>setenv</string>
        <string>{var}</string>
        <string>{value}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
'''

# ==============================================================================
# [Argument Parsing]
# ==============================================================================

def parse_args() -> argparse.Namespace:
    """
    Parse Args
    ==========

    Parse the command-line arguments.

    Returns
    -------
        argparse.Namespace: uninstall (bool), backdoor_dir (str|None),
        plugin_scripts (str|None).
    """

    parser = argparse.ArgumentParser(description='Install (or uninstall) the Mocha Pro Flame import integration.')
    parser.add_argument('--uninstall', action='store_true', help='Reverse the install.')
    parser.add_argument('--backdoor-dir', default=None, help='Logik Backdoor folder (skips the prompt).')
    parser.add_argument('--plugin-scripts', default=None, help="Plugin's Scripts folder (skips the prompt).")

    return parser.parse_args()

# ==============================================================================
# [Prompts]
# ==============================================================================

def ask_yes_no(question: str, default: bool) -> bool:
    """
    Ask Yes No
    ==========

    Prompt a yes/no question with a default taken on a blank line.

    Args
    ----
        question (str):
            The question, without the trailing choice hint.

        default (bool):
            The answer used when the user just presses Return.

    Returns
    -------
        bool: The user's choice.
    """

    hint = '[Y/n]' if default else '[y/N]'
    while True:
        answer = input(f'{question} {hint}: ').strip().lower()
        if not answer:
            return default
        if answer in ('y', 'yes'):
            return True
        if answer in ('n', 'no'):
            return False
        print("  Please answer 'y' or 'n'.")

def resolve_backdoor_dir(override) -> str:
    """
    Resolve Backdoor Dir
    ====================

    Return a validated logik_backdoor folder, prompting only when needed.

    An --backdoor-dir override is validated and used. Otherwise, if the client
    is at the default location it is used without asking. Only when neither holds
    does the installer prompt.

    Args
    ----
        override (str | None):
            Value of --backdoor-dir, or None.

    Returns
    -------
        str | None: A folder holding the client, or None if the user aborted.
    """

    if override:
        expanded = os.path.abspath(os.path.expanduser(override))
        if os.path.isfile(os.path.join(expanded, BACKDOOR_CLIENT)):
            return expanded
        print(f'ERROR: no {BACKDOOR_CLIENT} in {expanded}')

        return None

    # Found at the default: use it silently.
    if os.path.isfile(os.path.join(BACKDOOR_DIR_DEFAULT, BACKDOOR_CLIENT)):
        print(f'Logik Backdoor: found at {BACKDOOR_DIR_DEFAULT}')

        return BACKDOOR_DIR_DEFAULT

    # Not at the default: prompt.
    while True:
        entered = input(
            'Logik Backdoor folder not found at the default.\n'
            "  Enter the path to it, or 'q' to quit: "
            ).strip()
        if entered.lower() == 'q':
            return None
        if not entered:
            continue
        expanded = os.path.abspath(os.path.expanduser(entered))
        if os.path.isfile(os.path.join(expanded, BACKDOOR_CLIENT)):
            return expanded
        print(f'  No {BACKDOOR_CLIENT} found in: {expanded}')

def resolve_plugin_scripts(override) -> str:
    """
    Resolve Plugin Scripts
    ======================

    Return the plugin's Scripts folder, prompting only when needed.

    A --plugin-scripts override is used as-is. Otherwise, if the default folder
    exists it is used without asking. Only when it is missing does the installer
    prompt, offering the default.

    Args
    ----
        override (str | None):
            Value of --plugin-scripts, or None.

    Returns
    -------
        str: The chosen Scripts folder (created later if absent).
    """

    if override:
        return os.path.abspath(os.path.expanduser(override))

    if os.path.isdir(PLUGIN_SCRIPTS_DEFAULT):
        print(f'Plugin Scripts: found at {PLUGIN_SCRIPTS_DEFAULT}')

        return PLUGIN_SCRIPTS_DEFAULT

    entered = input(f'  Plugin Scripts folder [Return for {PLUGIN_SCRIPTS_DEFAULT}]: ').strip()

    return os.path.abspath(os.path.expanduser(entered)) if entered else PLUGIN_SCRIPTS_DEFAULT

# ==============================================================================
# [Detection]
# ==============================================================================

def detect_standalone() -> bool:
    """
    Detect Standalone
    =================

    Report whether standalone Mocha Pro looks installed.

    Returns
    -------
        bool: True if the app or its app-data folder exists.
    """

    return bool(glob.glob(STANDALONE_APP_GLOB)) or os.path.isdir(os.path.join(BORISFX_APPDATA, 'Mocha Pro'))

def detect_plugin() -> bool:
    """
    Detect Plugin
    =============

    Report whether the Mocha Pro OFX plugin looks installed.

    Returns
    -------
        bool: True if the OFX bundle or its app-data folder exists.
    """

    return bool(glob.glob(PLUGIN_OFX_GLOB)) or os.path.isdir(os.path.join(BORISFX_APPDATA, 'Mocha Pro Plugin'))

# ==============================================================================
# [Install Folder]
# ==============================================================================

def write_install_dir(script_dir: str, backdoor_dir: str, flavours) -> str:
    """
    Write Install Dir
    =================

    Write the module and init entry into the install folder.

    Copies mocha_flame_export.py into INSTALL_DIR with its LOGIK_BACKDOOR_DIR and
    ENABLED_FLAVOURS lines rewritten, and writes mocha_init.py beside it.

    Args
    ----
        script_dir (str):
            Directory holding this installer and the sibling module.

        backdoor_dir (str):
            Validated logik_backdoor folder.

        flavours (tuple):
            The selected flavours, e.g. ('standalone', 'plugin').

    Returns
    -------
        str: Absolute path of the installed mocha_init.py.

    Raises
    ------
        FileNotFoundError:
            If the sibling mocha_flame_export.py is missing.

        AssertionError:
            If either baked line is not found exactly once.
    """

    source = os.path.join(script_dir, MODULE_NAME)
    if not os.path.isfile(source):
        raise FileNotFoundError(f'Sibling module not found: {source}')

    with open(source, 'r') as handle:
        content = handle.read()

    # Rewrite the two baked lines. Each must appear exactly once.
    content, count = re.subn(r'^LOGIK_BACKDOOR_DIR = .*$', f'LOGIK_BACKDOOR_DIR = {backdoor_dir!r}', content, flags=re.MULTILINE)
    assert count == 1, f'Expected one LOGIK_BACKDOOR_DIR line, found {count}'
    content, count = re.subn(r'^ENABLED_FLAVOURS = .*$', f'ENABLED_FLAVOURS = {tuple(flavours)!r}', content, flags=re.MULTILINE)
    assert count == 1, f'Expected one ENABLED_FLAVOURS line, found {count}'

    os.makedirs(INSTALL_DIR, exist_ok=True)
    with open(os.path.join(INSTALL_DIR, MODULE_NAME), 'w') as handle:
        handle.write(content)

    init_path = os.path.join(INSTALL_DIR, INIT_NAME)
    with open(init_path, 'w') as handle:
        handle.write(INIT_ENTRY.format(install_dir=INSTALL_DIR))

    return init_path

# ==============================================================================
# [Environment Variable / LaunchAgent]
# ==============================================================================

def install_agent(init_path: str) -> None:
    """
    Install Agent
    =============

    Write and load the LaunchAgent, and set the variable now.

    Args
    ----
        init_path (str): Path of the installed mocha_init.py the variable points at.
    """

    os.makedirs(os.path.dirname(AGENT_PLIST), exist_ok=True)
    if os.path.isfile(AGENT_PLIST):
        subprocess.run(['launchctl', 'unload', AGENT_PLIST], check=False, capture_output=True)

    with open(AGENT_PLIST, 'w') as handle:
        handle.write(AGENT_TEMPLATE.format(label=AGENT_LABEL, var=ENV_VAR, value=init_path))

    subprocess.run(['launchctl', 'load', '-w', AGENT_PLIST], check=False)
    subprocess.run(['launchctl', 'setenv', ENV_VAR, init_path], check=False)

def remove_agent() -> str:
    """
    Remove Agent
    ============

    Unload and remove the LaunchAgent, and unset the variable.

    Returns
    -------
        str: What was done, for the summary.
    """

    done = []
    if os.path.isfile(AGENT_PLIST):
        subprocess.run(['launchctl', 'unload', AGENT_PLIST], check=False, capture_output=True)
        os.remove(AGENT_PLIST)
        done.append('LaunchAgent removed')
    else:
        done.append('LaunchAgent not present')

    subprocess.run(['launchctl', 'unsetenv', ENV_VAR], check=False)
    done.append(f'{ENV_VAR} unset')

    return ', '.join(done)

# ==============================================================================
# [Plugin Scripts init.py]
# ==============================================================================

def strip_block(content: str) -> str:
    """
    Strip Block
    ===========

    Remove this installer's marked block from init.py text, if present.

    Args
    ----
        content (str): The init.py text.

    Returns
    -------
        str: The text without the block, ending in one newline, or '' if nothing is left.
    """

    pattern = re.compile(re.escape(MARKER_BEGIN) + r'.*?' + re.escape(MARKER_END) + r'[ \t]*\n?', re.DOTALL)
    stripped = pattern.sub('', content).rstrip()

    return stripped + '\n' if stripped else ''

def patch_plugin_init(scripts_dir: str) -> str:
    """
    Patch Plugin Init
    =================

    Add or refresh the loader block in the plugin's Scripts init.py.

    Args
    ----
        scripts_dir (str):
            The plugin's Scripts folder. Created if absent.

    Returns
    -------
        str: The init.py path, for the summary.
    """

    os.makedirs(scripts_dir, exist_ok=True)
    path = os.path.join(scripts_dir, 'init.py')

    current = ''
    if os.path.isfile(path):
        with open(path, 'r') as handle:
            current = handle.read()

    base = strip_block(current)
    block = INIT_BLOCK.format(begin=MARKER_BEGIN, end=MARKER_END, install_dir=INSTALL_DIR)
    with open(path, 'w') as handle:
        handle.write((base + '\n' if base else '') + block + '\n')

    return path

def unpatch_all_scripts() -> list:
    """
    Unpatch All Scripts
    ===================

    Remove the loader block from every Mocha Scripts init.py.

    Strips the block from both flavours' Scripts init.py (older installs wrote to
    both), leaving any other code, and dropping the file if it becomes empty.

    Returns
    -------
        list: One result line per folder acted on.
    """

    results = []
    for flavour in ('Mocha Pro', 'Mocha Pro Plugin'):
        path = os.path.join(BORISFX_APPDATA, flavour, 'Scripts', 'init.py')
        if not os.path.isfile(path):
            continue
        with open(path, 'r') as handle:
            current = handle.read()
        if MARKER_BEGIN not in current:
            continue
        stripped = strip_block(current)
        if stripped.strip():
            with open(path, 'w') as handle:
                handle.write(stripped)
            results.append(f'block removed from {path}')
        else:
            os.remove(path)
            results.append(f'removed {path}')

    return results

# ==============================================================================
# [Install / Uninstall Flows]
# ==============================================================================

def install(args, script_dir: str) -> int:
    """
    Install
    =======

    Run the install flow.

    Args
    ----
        args (argparse.Namespace):
            Parsed command line.

        script_dir (str):
            Directory holding this installer.

    Returns
    -------
        int: Process exit code (0 on success, 1 on abort).
    """

    print(f'{SCRIPT_NAME} {SCRIPT_VERSION} -- installer')
    print('For Mocha Pro 2026.5 and later: standalone and the OFX plugin (used in Flame).')
    print('')

    if sys.platform != 'darwin':
        print('ERROR: this installer supports macOS only for now.')

        return 1

    # Logik Backdoor: silent if found at the default, else prompt.
    backdoor_dir = resolve_backdoor_dir(args.backdoor_dir)
    if backdoor_dir is None:
        print('Aborted: no Logik Backdoor folder.')

        return 1

    # Which flavours, defaulting to what is detected.
    want_standalone = ask_yes_no('Install for standalone Mocha Pro?', detect_standalone())
    want_plugin = ask_yes_no('Install for the Mocha Pro OFX plugin (used in Flame)?', detect_plugin())

    flavours = tuple(f for f, want in (('standalone', want_standalone), ('plugin', want_plugin)) if want)
    if not flavours:
        print('Aborted: neither flavour selected.')

        return 1

    # Plugin Scripts folder: only asked (and only if missing) when the plugin is
    # selected.
    plugin_scripts = resolve_plugin_scripts(args.plugin_scripts) if want_plugin else None

    # Install the module + init entry with the selections baked in.
    init_path = write_install_dir(script_dir, backdoor_dir, flavours)

    results = []

    # Standalone loads via the global variable + LaunchAgent; if it is not
    # selected, make sure any earlier agent/variable is gone.
    if want_standalone:
        install_agent(init_path)
        results.append(f'standalone: {ENV_VAR} set now and at login (LaunchAgent {AGENT_LABEL})')
    else:
        results.append(f'standalone: {remove_agent()}')

    # The plugin loads via its Scripts init.py; if not selected, strip any block.
    if want_plugin:
        results.append(f'plugin: loader block -> {patch_plugin_init(plugin_scripts)}')
    else:
        removed = unpatch_all_scripts()
        results.append('plugin: ' + ('; '.join(removed) if removed else 'no loader block to remove'))

    print('')
    print('Summary')
    print('=======')
    print(f'  flavours:   {", ".join(flavours)}')
    print(f'  backdoor:   {backdoor_dir}')
    print(f'  installed:  {os.path.join(INSTALL_DIR, MODULE_NAME)}')
    for line in results:
        print(f'  {line}')

    print('')
    print('Install complete. Restart Mocha (and Flame, for the plugin) to see')
    print('File > Flame Export.')

    return 0

def uninstall(args) -> int:
    """
    Uninstall
    =========

    Run the uninstall flow.

    Args
    ----
        args (argparse.Namespace): Parsed command line (unused).

    Returns
    -------
        int: Process exit code.
    """

    print(f'{SCRIPT_NAME} {SCRIPT_VERSION} -- uninstaller')

    results = [f'agent: {remove_agent()}']

    if os.path.isdir(INSTALL_DIR):
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)
        results.append(f'removed {INSTALL_DIR}')
    else:
        results.append(f'{INSTALL_DIR} not present')

    results += unpatch_all_scripts() or ['no Scripts loader block found']

    print('')
    print('Summary')
    print('=======')
    for line in results:
        print(f'  {line}')

    print('')
    print('Restart Mocha for the change to take effect.')

    return 0

# ==============================================================================
# [Entry Points]
# ==============================================================================

def main() -> int:
    """
    Main
    ====

    Entry point: parse the command line and run the install or uninstall flow.

    Returns
    -------
        int: Process exit code.
    """

    args = parse_args()
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if args.uninstall:
        return uninstall(args)

    return install(args, script_dir)

if __name__ == '__main__':
    sys.exit(main())
