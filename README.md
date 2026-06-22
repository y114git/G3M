<!-- markdownlint-disable MD013 MD033 MD041 -->

<a id="readme-top"></a>

<p align="center">
  <img src="src/assets/images/logo.png" alt="G3M logo" width="500">
</p>

<h1 align="center">G3M</h1>
<p align="center">
  Desktop mod manager for GameMaker games, with built-in discovery, library management, patching tools, profiles, and plugins.
</p>

<p align="center">
  <a href="https://github.com/y114git/G3M/releases/latest"><img src="https://img.shields.io/github/v/release/y114git/G3M?style=for-the-badge" alt="Latest release"></a>
  <a href="https://github.com/y114git/G3M/releases"><img src="https://img.shields.io/github/downloads/y114git/G3M/total?style=for-the-badge" alt="Total downloads"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/y114git/G3M?style=for-the-badge" alt="License"></a>
  <img src="https://img.shields.io/badge/Python-3.14%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.14+">
  <img src="https://img.shields.io/badge/Desktop-Windows%20%7C%20macOS%20%7C%20Linux-4B5563?style=for-the-badge" alt="Desktop platforms">
</p>

<p align="center">
  <a href="https://github.com/y114git/G3M/releases/latest">Download</a>
  ·
  <a href="https://g3m.gitbook.io/g3m-wiki">Wiki</a>
  ·
  <a href="https://github.com/y114git/G3M/issues">Issues</a>
  ·
  <a href="CHANGELOG.md">Changelog</a>
  ·
  <a href="https://discord.gg/2MFdvFfD9a">Discord</a>
  ·
  <a href="https://t.me/y_maintg">Telegram</a>
</p>

<details>
<summary><strong>Table of Contents</strong></summary>

- [What Is G3M](#what-is-g3m)
- [Highlights](#highlights)
- [Features](#features)
- [Supported Games](#supported-games)
- [Plugins](#plugins)
- [Build From Source](#build-from-source)
- [Development and Tests](#development-and-tests)
- [Customization and Localization](#customization-and-localization)
- [Legal](#legal)

</details>

## What Is G3M

G3M *(Formerly DELTAHUB)* is a desktop manager for GameMaker mod workflows. It combines GameBanana browsing, local library management, profile switching, mod and game versioning, patch utilities, custom game support, and optional plugins in one PyQt6 application.

The current codebase is focused on DELTARUNE, DELTARUNE Demo, UNDERTALE, UNDERTALE Yellow, Pizza Tower, Sugary Spire, and FRICKBEARS3, while also allowing custom games to be added through the in-app Game Manager.

## Highlights

- Built for both players and modders. G3M covers browsing, installing, launching, editing, converting, and packaging without splitting those workflows across multiple tools.
- Profiles are first-class. Each profile keeps its own library state and launch-related settings, so you can maintain separate playthrough, testing, or modpack setups.
- The built-in toolset is broader than a typical mod manager. Mod editing, manual install setup, patch creation and application, merge tools, diff viewing, and conversion workflows are part of the main app.
- Plugin support is real, not placeholder UI. G3M can load local or catalog plugins, validate API compatibility, expose plugin settings and views, and run lifecycle hooks.
- Recovery workflows are built in. Downloads history, mod versions, and game restore points make it easier to experiment without losing track of what changed.

## Features

### Discovery and installation

- Browse supported GameBanana games directly in the app, with metadata, screenshots, descriptions, and per-post file selection when a page has multiple compatible downloads.
- Install from GameBanana, external URLs, local archives, or one-click protocol links. `g3m://` is the primary scheme, legacy `deltahub://` links are still accepted, and external protocol downloads go through an explicit confirmation step.
- Use manual install when an archive is not ready for automatic conversion. The manual flow can map DATA files, extra files, and additional xdelta patches to explicit target paths.
- Hide unwanted browser results with the blocklist manager. Entries can be scoped globally or per game, and can block by mod ID, name, or category.

### Library, profiles, and versions

- Manage installed mods in a local library with drag-and-drop import and export, local README viewing, and richer mod details for screenshots and metadata.
- Create multiple library profiles with their own active mod selections and profile-scoped settings. Profiles can be created, renamed, duplicated, deleted, reordered, exported, and imported.
- Save per-mod version snapshots in each mod folder. Versions can be created locally, imported from archives, switched back in place, deleted, and downloaded from GameBanana for supported linked mods.
- Save full game versions as restore points. Game versions can be created from the live game or a profile-backed state, then applied, exported, imported, or removed later.

### Mod creation, editing, and conversion

- Create and edit local mods with the built-in Mod Editor. It supports game-aware file structures, extra files, metadata editing, icons, screenshots, and local export.
- Convert Deltamod packages into G3M mods during import. The converter keeps game mappings and patch layouts instead of treating Deltamod archives as opaque files.
- Convert PizzaOven packages for Pizza Tower into standard G3M mods when the source layout is eligible. GMLoader-style packages are explicitly rejected instead of being installed incorrectly.
- Import CYOP/AFOM-style Pizza Tower archives through a dedicated conversion path. Converted mods keep the required `towers` data and are tagged as `CYOP/AFOM`.
- These archive detection and conversion paths are shared across local import, Downloads auto-use, one-click installs, and supported mod version archive flows, so the same formats are not documented differently depending on entry point.

### Patching and modding tools

- Use the built-in Modding Tools window to create patches, apply patches, merge patch sets, inspect patch info, compare files, and export diff reports.
- Convert DATA-based mod content between supported patch formats inside the same toolset, instead of relying on separate patcher plugins.
- Launch multi-mod setups and create packaged modpacks. The patching layer also preserves extra-file overrides and game-specific file handling during use.

### Launch and compatibility

- Launch supported games with or without mods, including Steam launch handoff when a game has a configured Steam App ID.
- Create standalone shortcuts that embed the current launch configuration. Shortcuts can run headlessly through `--shortcut` without opening the full UI first.
- Use direct-launch chapter selection where the selected game supports it. DELTARUNE keeps its chapter-aware workflow separate from single-tab games.
- Enable PortProton on Linux instead of the default launch path when that setup is available and Steam launch is not taking over the session.

### Downloads and recovery

- Track downloads in a dedicated queue instead of one-off install prompts. Records move through queued, downloading, downloaded, ready, using, overwrite-pending, manual-required, failed, or cancelled states.
- Retry, cancel, install, overwrite, continue manual setup, or delete entries from the downloads window as needed.
- Control download behavior from settings. G3M supports disabling automatic use after download, deleting downloaded files after use, and keeping local imports in download history.

### Plugins and extra tools

- Load plugins from an online catalog or from local archives and folders. Installed plugins are scanned, validated for manifest shape, hooks, tags, relations, and file safety, then marked as installed, enabled, broken, local-only, or update-available.
- Toggle plugins on and off, open plugin settings, and surface plugin-provided main views and hooks through the runtime service.
- The bundled catalog currently exposes `DR Save Manager` for DELTARUNE save collection management and `Custom Saves Folders` for per-game, per-profile, or per-mod save folder switching.

### Interface, help, and privacy

- Open built-in About and Changelog dialogs without leaving the app. The About dialog links to releases, wiki, issues, the local G3M data folder, Discord, and Telegram.
- Switch between bundled themes or import and export theme archives. Theme packages can include color settings, media assets, and custom fonts.
- Change UI scale, border radius, theme colors, background media, startup sound behavior, and related appearance options from settings.
- Hide the Library tab if you want a slimmer layout for browsing and tool-focused use.
- Use bundled language packs or add external language files. G3M currently ships with English, Russian, Spanish, Korean, Japanese, Chinese Simplified, and Chinese Traditional.
- Anonymous analytics use two tiers. A small aggregate tier is always recorded; the extra-detail tier is disabled unless the local opt-in flag is enabled.

## Supported Games

| Game | Browser / GameBanana | Library / Launch | Notes |
| --- | --- | --- | --- |
| DELTARUNE | Yes | Yes | Full chapter-aware workflow, Steam App ID, direct-launch restrictions handled in-app. |
| DELTARUNE Demo | No (Download from DELTARUNE) | Yes | Supports local use and has a built-in full-install. |
| UNDERTALE | Yes | Yes | Includes Steam App ID support. |
| UNDERTALE Yellow | Yes | Yes | Includes a built-in full-install. |
| Pizza Tower | Yes | Yes | Includes PizzaOven conversion and CYOP/AFOM handling. |
| Sugary Spire | Yes | Yes | Included in the built-in registry and marked for full-install support. |
| FRICKBEARS3 | Yes | Yes | Included in the built-in registry and marked for full-install support. |

Custom games can be added in the Game Manager. A custom game can define its executable, DATA filename, optional Steam App ID, and optional GameBanana ID, and visible custom games can participate in search when a valid GameBanana ID is provided.

## Plugins

G3M has a plugin catalog service, install service, runtime loader, persistent plugin state, API compatibility checks, localization merge support, and hook execution for settings views, main views, lifecycle events, and game/session-related callbacks.

Plugin manifests can also declare required or conflicting plugins, and the runtime enforces those relations when enabling plugins.

The catalog committed in this repository currently contains two published plugins:

- `DR Save Manager` for DELTARUNE save collections and save editing.
- `Custom Saves Folders` for switching save folders by game, profile, or selected mods.

Local plugins are also supported. Manual installs are marked separately from catalog-backed installs so the UI can distinguish local-only plugins from catalog entries.

## Build From Source

G3M requires Python 3.14 or newer (project uses latest versions, edit pyproject.toml if you need compatibility changes).

```bash
git clone https://github.com/y114git/G3M.git
cd G3M
python -m pip install -e ".[dev,test,build]"
python src/main.py
```

Extras defined in `pyproject.toml`:

- `.[build]` installs PyInstaller.
- `.[test]` installs `pytest`, `pytest-qt`, coverage helpers, and related test tools.
- `.[dev]` installs Ruff.

The repository includes a PyInstaller spec at `builds/G3MExecutable.spec`:

```bash
pyinstaller builds/G3MExecutable.spec
```

That spec packages `src/main.py`, bundles the `src/` tree into the frozen app, and includes macOS bundle URL scheme metadata for both `g3m` and `deltahub`. A Windows installer script also exists at `builds/G3MWindowsInstaller.iss`.

## Development and Tests

Run the full automated suite with:

```bash
pytest
```

Useful local commands:

```bash
ruff check src tests
pytest tests/unit
pytest tests/integration
pytest tests/ui
```

The repository includes unit, integration, and Qt UI coverage for core areas such as protocol handling, downloads, profiles, plugin services, GameBanana integration, patching, game versions, dialogs, and widgets.

## Customization and Localization

Bundled themes live in `src/assets/themes/`, and bundled language packs live in `src/assets/lang/`. Theme import and export are archive-based, and localization supports external `lang_*.json` files plus per-language custom fonts loaded from the same directory as the language file.

If you want implementation details or contributor-facing guides for themes, localization, plugins, or mod formats, the README intentionally keeps those out of the main flow. The [G3MWiki](https://g3m.gitbook.io/) is the better place for step-by-step documentation.

## Legal

- [License](LICENSE)
- [Security Policy](SECURITY.md)
- [Third-Party Notices](THIRD_PARTY_NOTICES.md)

<p align="right"><a href="#readme-top">Back to top</a></p>
