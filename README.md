# DELTAHUB - The ultimate Mod manager

![GitHub release (latest by date)](https://img.shields.io/github/v/release/y114git/DELTAHUB?style=for-the-badge) ![GitHub all releases](https://img.shields.io/github/downloads/y114git/DELTAHUB/total?style=for-the-badge) ![Discord](https://img.shields.io/discord/1389372598260858950?label=Discord&logo=discord&style=for-the-badge) [![Telegram Channel](https://img.shields.io/badge/Telegram-t.me/y_maintg-2EA3D2?style=for-the-badge&logo=Telegram&logoColor=white)](https://t.me/y_maintg)

---

**DELTAHUB (DH)** is a cross-platform, universal, and extremely convenient Mod Manager, Saves Manager, and multi-functional manager for games such as **DELTARUNE**, **DELTARUNEdemo**, **UNDERTALE**, **UNDERTALE Yellow**, and **Pizza Tower**. In the future, it will support other games made with GameMaker.

---

## 🌟 DELTAHUB FEATURES

### Mod Management

- **Mod Search:** Browse a huge number of diverse mods. You can view their details and install with a single click! Filter mods by downloads, creation/update date, specific games, tags, and even by name or description. You can also install mods directly from GameBanana! Customize how many mods you want to see per page for optimal search experience.

- **Mod Library:** All your installed mods are here! Simply click on a mod to use it. Select multiple mods at once and play with them simultaneously! After exiting, all original files are restored, so DH will never damage your game files.

- **Multi-Mod System:** Play with multiple mods at once! When selecting 2+ mods, configure their priority to control which mod's changes take precedence when mods conflict. Higher priority mods are merged last, so their changes will be the final ones applied. Create modpacks to instantly launch your favorite mod combinations without waiting for merging each time!

- **Chapter-by-Chapter Mode:** For the full version of DELTARUNE, you can select mods for each chapter separately, allowing you to play with different mod combinations per chapter.

- **Direct Launch:** Double-click on the desired chapter slot and enable direct launch. This will allow you to launch the desired chapter directly when starting the game, bypassing the chapter selection menu.

- **Mod Import/Export:** Import mods from files or URLs, and export them in DELTAHUB format. Share your mods easily with others! DELTAHUB automatically detects and converts mods from Deltamod and PizzaOven formats.

- **Deltamod compatibility:** DH features built-in compatibility with the Deltamod format. More about this you can read from [Wiki](https://github.com/y114git/DELTAHUB/wiki/Deltamod-Compatibility).

- **PizzaOven compatibility:** DH also supports automatic conversion of PizzaOven mods for Pizza Tower. PizzaOven mods are automatically detected and converted when imported.

### Game and Save Management

- **Support for Multiple Games:** DH allows you to install mods for **DELTARUNE**, **DELTARUNEdemo**, **UNDERTALE**, **UNDERTALE Yellow**, and **Pizza Tower**! For free games like DELTARUNEdemo and UNDERTALE Yellow, DH has the ability to directly download the game itself with up-to-date files, eliminating the need to visit separate websites.

- **Save Manager (Plugin):** Solve the problem of not having enough save slots! The Save Manager plugin lets you create an endless number of additional save collections. Copy and export them wherever you want, even to an external source. Double-clicking on a save slot allows you to edit it. The Save Manager is now a plugin, so you can install it if you need it!

### Creation & Customization

- **Localization:** DH supports multiple languages (English, Russian, Chinese Simplified, Chinese Traditional, Spanish, and more). If you want to translate DH into your language (or just edit langs for fun), all the necessary files and instructions are in `src/assets/lang` and the [project Wiki](https://github.com/y114git/DELTAHUB/wiki/Localization-and-Lang-system-Guide).

- **Create Mods:** You can create and modify your own mods. DH has its own very simple structure for mods. The Mod Editor is now a plugin - install it if you need to create or edit mods!
  - **Public Mods:** After verification, a public mod will appear on the mods page for anyone to download.
  - **Local Mods:** A local mod will not appear on the mods page, but can be created without an internet connection and easily shared with friends or published on a separate website.

- **File Management, Auto-updates, and Other Mod Actions:** Configure necessary files for each chapter or game. Divide them into components with versions, so users only need to download updated components. Add and manage screenshots for your mod, which users will see directly in DH! You can also hide a mod, delete it, and more.

- **Plugin System:** Extend DELTAHUB's functionality with plugins! Browse, install, enable/disable, and import plugins. The Save Manager, Mod Editor, and XDELTA Patcher are now separate plugins that you can install if needed. Create your own plugins to add custom functionality! Plugins can be downloaded from [DH Plugins List](https://github.com/y114git/ylauncherdata/blob/main/PLUGINS.md) More details in the [Plugins Guide](https://github.com/y114git/DELTAHUB/wiki/Plugins-Guide).

- **Built-in Chat:** Chat with other DELTAHUB users! The chat is completely anonymous and supports 5 different language channels. Switch between channels for your preferred language.

- **Built-in Patching (Plugin):** The XDELTA Patcher is now a plugin! Create patches without needing separate programs. The process is no different from other patching GUIs. Install the plugin if you need patching functionality.

- **1-Click Installation & External Sources:** Install mods from external sources by creating an archive and providing a direct download link like this: `deltahub://{URL}`. When a user enters this link in their browser, DH will install the mod automatically. This works for both public and local mods, as well as plugins. Details are on the Wiki.

- **Create SHORTCUTS:** Create a shortcut for your game with desired settings and mods. Launching it will immediately start the game with your chosen configuration, even without running DH first.

- **Customize DH as you wish:** Change game and mods folders, create your own themes, add background music, or even change the intro sound! And if you want - share with your themes with friends! Quickly access your DELTAHUB folder (where mods, settings, plugins, and language files are stored) with a single button in settings.

- **Steam Integration:** Enable an option to launch the game through Steam, ensuring all your achievements and other Steam features work. You can also select a separate game executable file if needed.

- **PortProton Support (Linux):** On Linux, you can use PortProton instead of Wine to run Windows executables. PortProton provides better compatibility for games.

---

### 💻 Download & Support

- **How to download?:** Just download installer or binaries from [releases](https://github.com/y114git/DELTAHUB/releases) and launch them.

- **Bugs & Issues:** DH will be updated many more times with new games and features. Please report all bugs and other issues [on this page](https://github.com/y114git/DELTAHUB/issues).

- **Wiki:** For detailed info on "How to properly create mods," "How to change something," etc., please visit the [Wiki](https://github.com/y114git/DELTAHUB/wiki).
