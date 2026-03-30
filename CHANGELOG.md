### Version 3.0.0 — 30.03.26

- **DELTAHUB is now G3M (GameMaker Mod Manager)**

  - DELTAHUB is now **G3M**.
  - The application name, branding, icons, links, and one-click install format were updated for the new name.
  - `g3m://` one-click install links are now supported as the main format.
  - Older `deltahub://` links are still recognized, and the app can move your old DELTAHUB data into the new G3M folder on first launch.

- **Profiles system**

  - G3M now supports full **profiles** for your library.
  - Each profile keeps its own active mods and launch settings, so you can separate different playstyles, setups, or test environments.
  - Profiles can be created, duplicated, renamed, deleted, reordered, exported, and imported.
  - Switching between profiles is now part of the normal library workflow instead of something you have to manage manually.

- **Game Manager and Custom Games**

  - G3M now includes a proper **Game Manager**.
  - Built-in games can be shown or hidden, and the visible game order can be changed.
  - You can add your own **custom games/fangames** directly inside the app.
  - Custom games can define their executable, target DATA file, optional Steam identifier, and optional GameBanana identifier.
  - This means custom games can become real first-class entries in the launcher instead of awkward manual workarounds.
  - Custom games can also be edited or removed later.
  - When removing a custom game, G3M can also clean up related profile references and saved game versions tied to it.

- **PizzaOven and CYOP/AFOM mods support**

  - PizzaOven support was expanded into a much more exact workflow instead of treating every PizzaOven package like the same type of mod.
  - G3M now inspects a PizzaOven archive first and checks what kind of PizzaOven mod it actually is.
  - For PO mods, G3M makes a temporary copy of your Pizza Tower files, applies the PizzaOven mod there, compares the changed result against the original game, and then rebuilds that result as a normal G3M mod.
  - Because of this, the final converted mod is based on the real in-game file changes produced by the PizzaOven mod, not just on blindly copying files into a new archive.
  - If the PizzaOven mod changes `data.win`, G3M can keep that result as a proper patch or as a full file when needed.
  - If the PizzaOven mod changes other files, those changes are also collected and saved into the final G3M mod as normal extra files.
  - After conversion, the result is much easier to manage inside G3M as a regular Pizza Tower mod.
  - Mods whose authors explicitly disabled PizzaOven one-click integration are not force-converted by this workflow.
  - **GMLoader mods are detected separately and are not supported** 
  - G3M now also supports **CYOP/AFOM-style Pizza Tower mods**, but this support works differently from PizzaOven conversion.
  - CYOP/AFOM archives are recognized from their own folder layout and level `.ini` data.
  - When such an archive is imported, G3M converts it into a Pizza Tower mod that keeps the required `towers` content in the right structure.
  - During use and launch, that `towers` content is then copied to `AppData/Roaming/PizzaTower_GM2/towers/`.
  - A dedicated **CYOP/AFOM** tag/filter was also added, so these mods are easier to identify in the browser and library.
  - You can also create **CYOP/AFOM** yourself! You can add extra file (Folder or Archive) with `towers` in name and if it's Pizza Tower mod, everything from this folder will be copied to `AppData/Roaming/PizzaTower_GM2/towers/`.

- **Built-in Mod Editor**

  - The separate **Mod Editor plugin** was removed. Its functionality is now built directly into the main app.
  - You can now create and edit local mods without installing any extra plugin first.
  - Extra files, folders, and archives are handled more cleanly, which makes it easier to build larger mods without awkward setup.
  - Exporting a local mod is now part of the same workflow, so creating, editing, and sharing a mod feels like one system instead of separate tools.

- **Mod Versions**

  - Mods can now keep their own **saved versions**.
  - You can save the current state of a mod as a version snapshot before making changes.
  - You can switch a mod back to any saved version at any time.
  - Old versions can be deleted when you no longer need them.
  - A version can be imported from a file instead of rebuilding it by hand.
  - If you import a mod that already exists in your library, G3M now keeps it as a **new version of that mod** instead of simply colliding with the existing copy.
  - For mods linked to GameBanana, versions can also be downloaded directly from GameBanana into the version manager.

- **Built-in Modding Tools**

  - The separate **Xdelta Patcher plugin** was removed. Its functionality is now built directly into the main app.
  - A new **Modding Tools** window brings patch-related tools together in one place.
  - You can create patches, apply patches, merge multiple patches, inspect patch information, and compare two files with a visual diff report.
  - Diff reports can be exported, which is useful when you need to study exactly what changed.
  - DATA patch conversion is now built in as a proper workflow, so existing patch-based mods can be converted into other usable mod versions more easily.
  - This makes patch work much less dependent on separate external tools and much easier to keep inside one app workflow.

- **Downloads Queue**

  - G3M now has a full **Downloads** window instead of treating every download like a one-off action.
  - Downloads from GameBanana, external links, one-click protocol links, and local imports can now go through one queue.
  - Each item shows clear status, including downloading, installing, ready to install, conflict, manual install required, installed, failed, and cancelled.
  - You can retry, cancel, reinstall, overwrite, continue setup, or delete individual download entries.
  - Downloaded files can be kept for later reuse instead of immediately disappearing.
  - New download settings let you stop automatic installation after download.
  - New download settings let you delete downloaded files after use.
  - New download settings let you keep local imports in Downloads history.
  - External one-click installs are now confirmed before download starts.

- **Game Versions and Restore Points**

  - You can now save full **game versions** as restore points for supported games.
  - A saved game version can be applied back to the game folder later, exported as an archive, or deleted when no longer needed.
  - Imported game version archives are also supported.
  - When creating a game version, you can save the current game state as-is or save a version tied to a selected profile setup.
  - There is also an option for a more complete restore that removes files not present in the saved version, which is useful when you want a cleaner rollback.

- **Catalog, New Plugin Management and Plugin API**

  - Plugins are no longer just a local list. G3M now has an **online catalog** inside the app.
  - Plugins can be filtered more clearly, including an installed-only view and tag-based filtering.
  - Plugin cards now show clearer status, including enabled, incompatible, and local-only states.
  - Each plugin now has a more complete details view with version, author, status, homepage, update action, settings access, and delete action.
  - Local plugins are now clearly marked when they exist only on your machine and are not part of the online catalog.
  - Now it's more easier to make plugins to G3M, check Wiki for more info.

- **DR Save Manager Catalog Release**

  - **DR Save Manager** existed before, but it is now available through the plugin catalog as a proper downloadable plugin.
  - This makes it easier for players to find, install, update, and manage it like other optional features.
  - The plugin now comes as a more complete catalog release with its own translated interface.
  - Save collection handling remains a core part of the plugin, including choosing which collection to use for a session, renaming collections, deleting them, and importing or exporting saves.
  - The save editor is now split into **Simple mode** and **Advanced mode**.
  - **Simple mode** is designed more like a classic player-friendly editor in the style of Spamton/Tenna save editors, with cleaner grouped categories and easier-to-understand values.
  - **Advanced mode** remains available for users who want direct access to a much wider range of save values and flags.

- **Mods Browser and Library Improvements**

  - Mod cards and mod details were heavily upgraded.
  - The details view is now richer and easier to browse, with better presentation for screenshots, descriptions, readmes, and metadata.
  - You can now open screenshot images in the browser, copy images, or copy image URLs more easily.
  - Readmes have their own dedicated view, so longer mod instructions are easier to read.
  - Search and library pages now support more polished placeholders, cleaner empty states, and a more consistent layout.
  - Search filters and library presentation were reorganized to make large mod lists easier to manage.
  - If needed, the **Mods Browser** tab or the **Library** tab can now be hidden from settings.

- **Blocklist Manager**

  - G3M now includes a dedicated **Blocklist Manager** for the Mods Browser.
  - You can hide specific mods from search results instead of having to ignore them manually every time.
  - Blocking can be done by **ID**, **name**, or **category**, depending on how specific you want the filter to be.
  - The blocklist can be set for one game only or used globally across the browser.
  - This is especially useful if you want to hide joke mods, NSFW content, low-quality uploads, duplicate pages, or categories you simply never use.

- **Manual Install, Import, and Conversion Improvements**

  - Manual installation was expanded again and is now easier to continue from the Downloads system when a mod cannot be installed automatically.
  - DATA files and extra files are assigned through a clearer setup flow.
  - Additional Xdelta patches for other game files can now be configured more explicitly, including the target path inside the game folder.
  - Deltamod import and conversion support was also strengthened, especially when archives are packed in unusual ways or when a mod with the same ID already exists.

- **GameBanana Improvements**

  - GameBanana integration was expanded across the app.
  - Mod details, file picking, downloads, and version handling now work together much more cleanly.
  - File selection gives clearer information when a GameBanana post has multiple possible downloads.
  - GameBanana-linked mods can work with the new version system, which is useful when a mod has multiple downloadable builds.
  - Better error handling was added for rate limits and failed requests, so the app behaves more predictably when GameBanana is slow or temporarily restricted.

- **Themes, Settings, and Interface Options**

  - Settings were reorganized into clearer sections such as General, Game, Appearance, Library, Mods Browser, and Plugins.
  - Theme management was improved with a clearer summary of what your current theme actually changes.
  - Built-in themes are now included directly with the app.
  - Theme import, export, apply, save, and delete actions were polished into a cleaner workflow.
  - More appearance controls were added or expanded, including UI scale, border radius, custom hover/select colors, and theme-related media options.
  - The old animated splash screen is no longer used. Because of that, the old **Disable splash** setting was removed. In its place, there is now a **Disable startup sound** option for users who want a quieter startup without changing the rest of the interface.
  - There is now a dedicated option to keep the app window visible while the game is running.
  - Anonymous analytics is now opt-in and clearly presented as optional help for improving the project.

- **New Menu bar at the top and Help tab**

  - G3M now uses a new **top menu bar**, which makes important app-level actions easier to find.
  - A dedicated **Help** menu was added instead of scattering these actions around the interface.
  - From the Help menu, users can quickly open the built-in **Changelog** window and the **About** window.
  - The built-in changelog viewer makes it easier to check what changed without leaving the app.
  - The About window gives quick access to releases, wiki, issues, and the G3M data folder.

- **Compatibility, Launch, and Quality-of-Life Improvements**

  - Launch flow is now clearer when using Steam together with mods, especially in cases where Steam may start the game from a different folder than the one configured in the app.
  - This is particularly helpful for Steam Deck and other setups where the real launch path may differ from the obvious one.
  - Shortcut creation was improved and now presents a clearer summary of what the shortcut will launch.
  - Archive support was expanded further, including broader support for `.tar`, `.tar.bz2`, `.tar.xz`, `.tgz`, `.tbz2`, and `.txz` packages.
  - `.rar` handling is more reliable thanks to bundled extraction support.
  - Better warnings were added for patch/file mismatches, missing original files, and partial patching situations, so players get more understandable prompts instead of silent failures.

### Version 2.4.7 — 16.01.26

- **Major Mod Merge Improvements**

  - Full support for creating NEW resources that don't exist in the base game. Previously, mods could only modify existing assets. Now mods can add completely new Sounds, Fonts, Paths, AudioGroups, Timelines, Extensions, Shaders, and Rooms.
  - Fixed critical bug with font registration that caused game crashes when mods added new fonts.
  - Fixed import order: all resource types (fonts, sounds, rooms, etc.) are now imported BEFORE GML code, ensuring the compiler correctly recognizes new resources.

- **Custom Logo Support**

  - You can now set a custom logo for DELTAHUB! Find the new option in the customization settings.

- **Archive Extraction Fixes**

  - Fixed .7z archive extraction that was failing due to incorrect argument handling.
  - Improved .rar archive extraction reliability.

- **Manual Installation Improvements**

  - Fixed bug that prevented manual mod installation when there is no DATA file but Extra files are present.

- Also, you can scroll chat horizontally (ye).

### Version 2.4.6 — 11.01.26

- **Additional xdelta patches for Manual installation**

  - If mod have more than 1 .xdelta patch, then you can now write path to file that you want patch with it.

- **Optimization and Fixes**

  - Optimized assets exporting, increasing merging speed.
  - Fixed bugs with manual installation and etc.
  - Fixed bug with mod list flickering.
  - Fixed crash when deleting mods or creating modpacks under certain circumstances.

### Version 2.4.5 — 07.01.26

- **Manual Install Functionality**

  - DELTAHUB now supports downloading ANY mod, even if it's not in compatible format. New manual install feature will allow you to configure mod files so now you don't have to use deltapatcher all time or create mods in Mod Editor.

- **Hide Mods without Files Feature**

  - You can now enable this feature to hide every mod that you can't download (Because there is no download files), for example Wip mods.

- **Custom exe Rework**

  - Custom executable checkbox was removed and now there is unique button for each game, so you can choose any executable you want without problem! Also if you had problems with game folder validation, just use Custom exe feature, choose .exe in your game folder and there will be no more problems with it!

### Version 2.4.4 — 06.01.26

- **Sugary Spire Support**

  - DELTAHUB now supports the Pizza Tower fan game, Sugary Spire!

- **Bug Fixes**

  - Fixed a bug with local mod icons render in the library
  - Some text has been slightly tweaked to make it easier to understand

### Version 2.4.3 — 05.01.26

- **Small update with bugfixes**

  - Fixed search bug, autoupdating bug and splash screen stuck bug.

### Version 2.4.2 — 01.01.26

- **Small update with bugfixes**

  - Lot of minor bugfixes and one major bugfix with merging and pizzaoven.
  - Added support to Wip mods.

### Version 2.4.1 — 21.12.25

- **New resource support and bug fixes**

  - DELTAHUB now supports merging Extensions, Audio Groups, Paths, and Timelines.
  - Bugs that caused crashes when deleting mods and importing mods have been fixed.

### Version 2.4.0 — 13.12.25

- **Full Support for Pizza Tower and Pizza Oven**

  - DELTAHUB now supports Pizza Tower! No differences from other games in the program, browse mods, download and explore them right in DH, and play with mods as if nothing happened!
  - Also, since almost all mods for Pizza Tower are created for Pizza Oven, DELTAHUB also supports this format, so there should be no problems with it, but I want to note that unlike, for example, Deltamod, Pizza Oven uses a format without a config file, it simply iterates through files and determines where to place them itself. To avoid breaking the logic and not struggling with adaptation, I simply adapted this format, and now the application has 2 mod formats for Pizza Tower - pizzatower (standard for DELTAHUB, with a config file) and pizzaoven (uses Pizza Oven logic). Both fall under Pizza Tower and will work. If you discover any bugs, please report them through the new "Report a Bug" button.

- **"Report a Bug" Button Instead of "Help and Info"**

  - No more struggling with finding logs, trying to contact administration in a separate place, and so on. Now you simply click on the new "Report a Bug" button, fill out a maximally convenient form, and after sending, your report will be sent directly to me and will be fixed even faster!
  - The "Help and Info" button was removed as unnecessary.

- **Complete Merge System Rework and Fast Merge Function**

  - Before this update, it turns out the merge system had so many bugs and logical problems that the number of successful merges was less than 1% (and besides code and sprites, other resources weren't even being merged)! However, 3 weeks of fixes and reworks have paid off. Now the merge system COMPLETELY and perfectly merges all selected mods without any problems! You won't even notice any difference. This applies to fonts, sounds, rooms, and so on. Of course, if several mods modify the same resource, then depending on priority, only one will make it into the game for now, but this is much better than before! Also, smart code merging will be released soon, which still needs some refinement, but thanks to it, the number of successful merges will increase even more!
  - Also, to speed up the merge process, a fast merge function has been added, which allows the process to handle mods not one by one, but simultaneously, saving a lot of time, especially when selecting multiple mods.

- **Huge Number of Bugfixes and Optimizations**

  - Many bugs have been fixed, and YOU reported many of them to me! For which I am very grateful!
  - The most annoying bug has been fixed, when at program startup, during mod loading, there was some strange flickering or rapid appearance of small windows. Now the problem is resolved.
  - When you were browsing mods, you might have noticed that some mods move to previous pages. This was due to auto-sorting, which automatically sorted mods so they were in the right places. Now auto-sorting is disabled by default, you can enable it by clicking the checkbox to the right of the field for entering the maximum number of mods per page.
  - Fixed the issue where when importing mods created on the DELTAHUB-MCE website, you would get an "Invalid mod format" error.
  - You can now create modpacks in xdelta format, instead of data.win/ios
  - Now the buttons for specifying the path to the game folder are located in the library, not in settings.
  - Many more small and even larger optimizations have been made for the interface, process handling, and game, bugfixes, and so on, so in this update, the application should feel much more pleasant.

### Version 2.3.4 — 27.11.25

- **Mod search page optimization and bug fixes**

  - Now you can only select one game on the mod search page, and mods are loaded for it, not for all games at once, which will noticeably speed up their loading and optimize many aspects. You can no longer select all mods at once, but it's not needed anyway.
  - Fixed bugs with freezes when broken mods are present, cleaned up code from unnecessary clutter, and fixed many instances where the background flickered. Also fixed some artifacts and sped up mod loading.

### Version 2.3.3 — 25.11.25

- **Improved optimization and fixed some bugs**

  - Improved launcher optimization, fixed some bugs.

### Version 2.3.2 — 19.11.25

- **Bugfixes and icons relative paths**

  - Fixed some bugs and also, now you can either in mod_config.json write in icon relative path like modfolder/icon.png and DELTAHUB will use icon from this path.

### Version 2.3.1 — 17.11.25

- **Improved deltahub:// URL Support**

  - The deltahub:// protocol handler has been significantly improved. Now it automatically detects the content type (mod, plugin, or theme) and installs it accordingly. You can now install mods, plugins, and themes directly via deltahub:// links without worrying about what type of content it is (Just make sure to follow the rules described in the Wiki).

- **GameBanana File Selection Dialog**

  - When installing a mod from GameBanana that has multiple compatible files, a new dialog will now appear allowing you to choose which file to install. You'll be able to see detailed information about each file, including version, size, format, security status, and description, helping you make the best choice for your needs.

- **Better GameBanana Installation**

  - Improved compatibility checking for GameBanana mods; you'll immediately see if a mod is compatible or not, even before clicking the install button.
  - Better progress tracking during GameBanana mod installation, with real-time updates in the search interface.

- **Fixes and Improvements**

  - Improved search page loading logic for GameBanana mods, making pagination and mod discovery more efficient.
  - Better handling of mod installation states and button updates throughout the interface.

### Version 2.3.0 — 16.11.25

- **Full Support for All Resource Types**

  - When merging mods, in addition to code and textures, fonts, rooms, shaders, sounds, and tilesets are now also merged.

- **Merge Conflict Warnings**

  - When merging multiple mods, if conflicts are detected between them (when different mods modify the same resources), a special dialog will now be shown with information about the conflicts. You'll be able to see which mods conflict with each other, and optionally open detailed logs for a more detailed study of the problem.

- **Fixes and Improvements**

  - Fixed an issue with pagination on the mod search page; page navigation now works correctly.
  - Improved cleanup of temporary files after mod merging, which should slightly speed up the launcher and free up more disk space.

### Version 2.2.0 — 11.11.25

- **Complete Library Rework + Multi-Mod System**

  - The library no longer has slots, now you simply click on a mod and use it. Thanks to the multi-mod system, you can select multiple mods at once. This works through step-by-step merging of mod files, but be warned: some mods may override each other. To avoid this, when selecting 2+ mods, you can configure priority for mods. Those with higher priority will be merged last, meaning if several mods affect the same point, the final change will come from the mod with the highest priority.
  - Also, to avoid waiting a long time for mod merging, I recommend creating a modpack after selecting your mods. When launching a modpack, the game will start instantly with the selected mods and priority set during modpack creation. You can now also import (even via URL) or export mods (in both DELTAHUB and DELTAMOD formats).

- **Search Page Rework + GameBanana Mod Support**

  - Now on the mod search page, you can also install mods directly from GameBanana (and from other sources in the future). While you'll see all mods, if a mod wasn't created for the DELTAHUB format or at least DELTAMOD format, it won't be possible to install it automatically (though you can still view all the necessary information about it). You'll need to contact the author and ask them to add DELTAHUB support.
  - You can now also choose the number of mods per page. The more you specify, the wider the search will be, but the load will also be higher.

- **Undertale Yellow Support**

  - Rejoice, Yellow fans! You can now launch Undertale Yellow in DELTAHUB, download mods for it, and if you haven't installed it before, you can use the full installation function to download it immediately (just like for DELTARUNEdemo). After installation, all paths will be automatically set, and you'll only need to launch the game.

- **Plugin System + Migration of Save Manager, Mod Editor, and XDELTA Patcher to Plugin Format**

  - For those who wanted to extend DELTAHUB's functionality, a convenient plugin system has been added, along with a Plugins page where you can configure plugins, enable/disable them, download and import them (even via URL). All details about this system are here: <https://github.com/y114git/DELTAHUB/wiki/Plugins-Guide.md>.
  - Also, the built-in functions of Mod Management, XDELTA Patcher, and Save Manager are now separate plugins. The migration was made because not everyone needed these functions, and for some they were just clutter on the screen. Now you can choose and download what you need yourself.

- **Built-in Chat**

  - Instead of the button to go to the save manager at the bottom right, there's now a Chat button. The chat is completely anonymous, and you can switch between 5 different channels for your languages. In the future, this function might also become a plugin, and instead there will be a button that you can configure to do anything (for example, the same Chat, some tab, game launch, or a plugin).

- **PortProton Support**

  - Now, if you're using Linux, you can enable an option to use PortProton instead of Wine.

- **Spanish Language Support**

  - Spanish language has been added to DELTAHUB! A huge thank you to the Spanish community for their support.

- **Bug Fixes, Optimization, and Other Minor Changes**

  - In settings, you can now open the DELTAHUB folder with a single button, where mods, settings, plugins, and localization files are stored.
  - Everything that could be optimized has been maximally optimized, caching and asynchrony have been added everywhere possible. Using the program should now be much easier and more pleasant.
  - This update can rightfully be called the biggest bug-fixing update. You may never know this, but during the development of this update, more than 47 bugs were fixed, from minor to truly major ones (for which a separate patch could have been released). Huge work was done, and I hope my efforts won't disappoint you!

### Version 2.1.2/3 — 13.10.25

- **Library Filters!**

  - Now you can filter mods not only on the main page but also in the library! In addition to the main tags, you can now also sort mods based on whether they are local or not.

- **Save Collection Selection and Management**

  - If you've created at least one save collection, you can now choose exactly which collection to play with when launching the game. After you finish playing, all your saved actions will be automatically saved back into the collection you selected.

- **Linux Launch Fix**

  - Now, if you are launching the game without Steam, the launcher will immediately attempt to start it using Wine. Please make sure you have it installed.

### Version 2.1.1 — 03.10.25

- **GameBanana URL > External URL**
  - The "GameBanana URL" field has been replaced by "External URL," allowing links to any site (itch.io, ModDB, etc.). For better security, a new validation check blocks direct download links. The banana icon 🍌 has also been removed.

- **Versioning for Lang files**
  - Language files now can have a version number. If you manually edit one of default lang files, you must also increase its version inside the file. Otherwise, the launcher will restore the original file to prevent issues. This does not affect custom/fan-made language files.

### Version 2.1.0 — 03.09.25

- **Complete Localization System Remake + Chinese Language Support**
  - Previously, you could only use the languages built into the launcher, and you had to restart the launcher to switch, plus there were a lot of bugs. However, the era of localization has now arrived! From now on, languages are stored in the `lang` folder, next to the `settings` and `mods` folders. In addition to the official languages (A huge thank you to the Chinese community for their support), you can now add your own fan translations or even make FUNNY translations (WHAT?!). What's more, you can now choose the font for the launcher yourself by simply editing the lang file. In the `font` field, specify the name of the font file, which must be in the same folder as the language file! All other details are [HERE](https://github.com/y114git/DELTAHUB/wiki/Localization-and-Lang-system-Guide).

- **Deltamod Compatibility + .LZMA and .TAR.GZ Support**
  - In addition to supporting two new archive formats, you can now literally drop a mod created for the Deltamod format into the `mods` folder (regardless of whether it's an archive or a folder) and DELTAHUB will automatically convert it to the local mod format for DH! Downloading via links (`deltahub://`) is also fully supported, so mod developers won't have to worry either. More details [HERE](https://github.com/y114git/DELTAHUB/wiki/Deltamod-compatibility).

- **Theme Manager**
  - You can now **import and export** your launcher's appearance settings! A new button has appeared in the customization settings that allows you to save your colors, background image, music, and sounds into a single `.dhtheme` file and share it with friends.

- **Beta Updates**
  - An option has been added to the settings to receive **experimental beta versions** of the launcher. Turn it on if you want to be the first to try new features!

- **Full Screen Mode**
  - For full immersion, a checkbox has been added to the settings to launch the application in **full screen mode**.

- **_icon for Local Mods**
  - The issue with icon display for local mods has been fixed. Also, for a local mod to have an icon, an `_icon` file (`.png`, `.jpg`, etc.) must be in the mod's folder, next to `config.json`.

- **Against Piracy!**
  - Now, when you try to disable Xdelta mode when creating or editing a mod, or when installing a mod that uses file replacement, you will receive a warning. You can only continue to use or create such a mod if you agree to the terms and take full responsibility.

- **Offline Interface**
  - Now you can create local mods even without an internet connection (this should have been the case before, but there was a small bug).

- The code has been greatly cleaned up, and the launcher's performance has been slightly accelerated (if anyone cares).

### Version 2.0.0 Alpha — 16.08.25

- **YLauncher is now DELTAHUB!** This is more than just a name change — the launcher has been rebranded and is now a full-fledged platform for not only translations, but for any mods. You now have a huge library with a convenient search function at your disposal.

- **A completely new interface!** The launcher has received a fully redesigned look that is more modern and convenient. Finally!
  - **Updated startup screen:** Now, when you launch the launcher, you are greeted not by just an icon, but by an animated splash screen. You can turn it off in the settings.
  - **Built-in mod library:** All your installed mods are now in one place, where you can configure anything you want, such as whether to launch a mod immediately without any extra settings, or to set up mods for each chapter separately. Also, the DEMO VERSION checkbox has been moved from the settings to the library.

- **Complete mod management**
  - Now you can create your own mods and publish them. You can update them yourself, customize them, and have full control over them.
  - Now, if you need to update a file, you can update just one of the mod's components, and users will no longer need to reinstall the entire mod from scratch, as was the case before. It will be enough to simply update only the changed components.
  - You can also add your own local mods and now, you can even edit them!

- **Full launcher customization and other changes:**
  - You can now customize the launcher to suit your preferences — ABSOLUTELY EVERYTHING! The background music, the splash screen sound, the background, the color of backgrounds, the color of text and other elements, and so on!
  - The launcher now runs even faster. The basic initialization has been sped up many times over, and you can make the launcher start even faster by disabling the splash screen in the settings.
  - The button to update the interface and mod information is now located to the right of the Settings button.
  - The Erase button is gone; in its place, the save manager has been moved from the settings.
  - Now, when you launch the game with a mod, the files are no longer mindlessly copied into the game folder. Instead, the original files are moved to a temporary folder while the game is running, and when the game ends, the mod files are deleted from the game folder, and the original files are returned to their place.
  - Many other minor changes, which I advise you to check out for yourself :)

### Version 1.7.4 — 23.07.25

- Minor bug fixes + fixes for MacOS issues.

### Version 1.7.3 — 19.07.25

- Minor bug fixes.

### Version 1.7.2 — 18.07.25

- **A few bug fixes!**

- Now, each time you launch, it will not constantly ask you to re-select the game folder.
- The online counter used to jump around like crazy, but now it shouldn't.
- The launcher window should now always appear on top of the screen, and you don't have to constantly click on it in the taskbar to open it.

### Version 1.7.1 — 16.07.25

- **Micro-update!**

- For some, the launcher did not start properly after the last patch, and for others, the launcher could freeze almost every 5 seconds. In this update, I tried to fix this.
- Now, while the launcher is starting, you can look at a cool icon that appears in the center of the screen (Ahahahah).
- Now, when exporting save slots, if they were completed, not only the main file is exported, but also the completion file associated with it.

### Version 1.7.0 — 15.07.25

- **Full support for the Deltarune demo version!**

- Now you can launch and manage the demo version of the game directly from the launcher — without any extra hassle!
- If you haven't installed the DEMO version yet, you can download it from scratch in the launcher thanks to the Full Installation feature!
- Automatic search and installation of the demo version, including downloading the latest build directly from the interface.
- Fully compatible with Steam.

- **Improved translation manager:**

- New "Backup Server" feature — now, even if the main servers are unavailable, you can always download the translation you need.
- Support for new archive formats: now the launcher works easily not only with ZIP, but also with RAR files.
- Improved system for searching and downloading translations — faster, more convenient, more stable!

- **Interface updates:**

- An online counter has been added, which displays the number of players who launched the game through the launcher.
- The launcher's interface has become even more user-friendly, and compatibility with Linux and macOS has been improved.
- Advanced dialogues for saving and managing translations.
- Improved adaptability, new tips, and quick access to the necessary functions.

- **Additional improvements and fixes:**

- Optimized work with the Internet and temporary files, fixed rare errors when downloading translations.
- Builds on MacOS are now immediately signed, and you do not need to constantly run them from the console.
- Increased stability on all supported systems.
- Improved support for custom executable files for advanced users.

### Version 1.6.0 - 12.07.25

* New feature: Save Manager! Now you can manage your saves directly in the launcher.

- How to open: Go to "Settings" and click the new "Saves✨" button.

- Collections: Create separate "collections" of saves for each chapter. This is ideal for storing saves from different playthroughs (for example, "pacifist" and "genocide") and not getting confused.

- Backup: Easily copy saves from the main slots to any collection and back. You can copy one selected slot or all three at once.

- Direct editing: For advanced users! Just double-click on an occupied slot to open a simple editor and manually change the values in the save file. Soon there will be a much more convenient and understandable editor!

Interface and usability improvements:

- The launcher window can now be stretched, and its size is saved after closing.

- Completely redesigned appearance: navigation through chapters is moved to the center, and the Telegram and Discord buttons are now always at hand on the main screen.

- The "Forced launch" checkbox has been removed. Now the launcher itself understands when to launch the game without changes.

- Added support for animated .gif as a background.

Other changes:

- The auto-update logic has been slightly updated and minor bugs have been fixed.

### Version 1.5.3 - 06.07.25

- More extensive support for MacOS systems (Supports all architectures, but only if the version is above 11.0), visual bugs with local translations have been fixed.

### Version 1.5.2 - 05.06.25

- Minor fixes and bug fixes, especially with the fact that translations were not shown on the first installation.

### Version 1.5.1 - 30.06.25

- For those who received an error about a lack of access rights to the game folder, the launcher now tries to fix this automatically, and if it fails, it displays a message asking you to run as an administrator or manually change the folder rights.

### Version 1.5.0 - 28.06.25

- **2 New features: Direct launch and Your own translation!** By enabling direct launch, when you launch the game through the launcher, selecting the desired chapter (Chapter tab), the game will start immediately from that chapter, without the need to first select the chapter separately in the main menu of the game. Due to technical problems, it only works on Windows/Linux, and is also not compatible with launching through Steam.
- **The second feature is Your own translation**, now you can add your own translation/mod/changes for each chapter separately, your added translation is saved in the list and you can select several custom translations and switch between them, if you are too lazy to add a translation for each chapter, you can take an archive that contains everything you need, and also in the folders with chapters, and just add the translation specifically through the Main menu of the game tab (Since everything there works on the root folder). You can give any name to your translation separately, and the most interesting thing is that you can add your own translation directly from a URL without the need to download anything separately.
- Now the No Changes option is grayer, local translations (Which you added) are always yellow and at the top of the list, and the main translations are white if they have not yet been downloaded, green if they have been downloaded and do not need to be updated, and orange if they have been downloaded but need to be updated.
- A little more compatibility with MacOS has been added, and problems with a lack of rights for some users have been fixed.
- Several critical bugs that could lead to the launcher freezing or incorrect operation have been fixed.
- All new features are fully compatible with each other, including Shortcuts.

### Version 1.4.2/1.4.3 - 23.06.25

- The problem with the normal display of text in descriptions has been fixed.
- Several more critical bugs have been fixed.

### Version 1.4.0/1.4.1 - 23.06.25

- **New feature: Shortcuts! (Hey!)** Now you can create a shortcut to launch with your settings. Just set everything up as you like, click "Shortcut", and the launcher will create a special launch file. When you click on it, the game will start with the selected translations and settings, and the launcher itself will not even appear on the screen.
- The "Update" button has been replaced with "Shortcut". The list of translations is now updated automatically on launch. However, you can now perform a Check for Updates, right from the settings menu.
- The launcher's core has been changed, which made it much more stable and pleasant.
- Now by default the launcher has a new beautiful Deltarune theme, but in the settings you can still choose the Legacy Theme, which will return the old, good look of the launcher up to 1.4.0
- "Change log" has been added.
- A check and a warning have been added when selecting a chapter folder instead of a game folder.
- 2 critical bugs have been fixed, one of which did complete nonsense when the data.win file was missing in the game folder.
