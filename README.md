# G3M - The ultimate Mod manager

![GitHub release (latest by date)](https://img.shields.io/github/v/release/y114git/G3M?style=for-the-badge) ![GitHub all releases](https://img.shields.io/github/downloads/y114git/G3M/total?style=for-the-badge) ![Discord](https://img.shields.io/discord/1389372598260858950?label=Discord&logo=discord&style=for-the-badge) [![Telegram Channel](https://img.shields.io/badge/Telegram-t.me/y_maintg-2EA3D2?style=for-the-badge&logo=Telegram&logoColor=white)](https://t.me/y_maintg)

---

**G3M** is a cross-platform, universal, and extremely convenient Mod Manager, Saves Manager, and multi-functional manager for games such as **DELTARUNE**, **DELTARUNEdemo**, **UNDERTALE**, **UNDERTALE Yellow**, and **Pizza Tower**. In the future, it will support other games made with GameMaker.

---

## 🌟 G3M FEATURES

### Mod Management

- **Mod Search:** Browse a huge number of diverse mods. You can view their details and install with a single click! Filter mods by downloads, creation/update date, specific games, tags, and even by name or description. You can also install mods directly from GameBanana! Customize how many mods you want to see per page for optimal search experience.

- **Mod Library:** All your installed mods are here! Simply click on a mod to use it. Select multiple mods at once and play with them simultaneously! After exiting, all original files are restored, so G3M will never damage your game files.

- **Multi-Mod System:** Play with multiple mods at once! When selecting 2+ mods, configure their priority to control which mod's changes take precedence when mods conflict. Higher priority mods are merged last, so their changes will be the final ones applied. Create modpacks to instantly launch your favorite mod combinations without waiting for merging each time!

- **Chapter-by-Chapter Mode:** For the full version of DELTARUNE, you can select mods for each chapter separately, allowing you to play with different mod combinations per chapter.

- **Direct Launch:** Double-click on the desired chapter slot and enable direct launch. This will allow you to launch the desired chapter directly when starting the game, bypassing the chapter selection menu.

- **Mod Import/Export:** Import mods from files or URLs, and export them in G3M format. Share your mods easily with others! G3M automatically detects and converts mods from Deltamod and PizzaOven formats.

- **Deltamod compatibility:** G3M features built-in compatibility with the Deltamod format. More about this you can read from [Wiki](https://github.com/y114git/G3M/wiki/Deltamod-Compatibility).

- **PizzaOven compatibility:** G3M also supports automatic conversion of PizzaOven mods for Pizza Tower. PizzaOven mods are automatically detected and converted when imported.

### Game and Save Management

- **Support for Multiple Games:** G3M allows you to install mods for **DELTARUNE**, **DELTARUNEdemo**, **UNDERTALE**, **UNDERTALE Yellow**, and **Pizza Tower**! For free games like DELTARUNEdemo and UNDERTALE Yellow, G3M has the ability to directly download the game itself with up-to-date files, eliminating the need to visit separate websites.

- **Save Manager (Plugin):** Solve the problem of not having enough save slots! The Save Manager plugin lets you create an endless number of additional save collections. Copy and export them wherever you want, even to an external source. Double-clicking on a save slot allows you to edit it. The Save Manager is now a plugin, so you can install it if you need it!

### Creation & Customization

- **Localization:** G3M supports multiple languages (English, Russian, Chinese Simplified, Chinese Traditional, Spanish, and more). If you want to translate G3M into your language (or just edit langs for fun), all the necessary files and instructions are in `src/assets/lang` and the [project Wiki](https://github.com/y114git/G3M/wiki/Localization-and-Lang-system-Guide).

- **Create Mods:** You can create and modify your own mods. G3M has its own very simple structure for mods. The Mod Editor is now a plugin - install it if you need to create or edit mods!
  - **Public Mods:** After verification, a public mod will appear on the mods page for anyone to download.
  - **Local Mods:** A local mod will not appear on the mods page, but can be created without an internet connection and easily shared with friends or published on a separate website.

- **File Management, Auto-updates, and Other Mod Actions:** Configure necessary files for each chapter or game. Divide them into components with versions, so users only need to download updated components. Add and manage screenshots for your mod, which users will see directly in G3M! You can also hide a mod, delete it, and more.

- **Plugin System:** Extend G3M's functionality with plugins! Browse, install, enable/disable, and import plugins. The Save Manager, Mod Editor, and XDELTA Patcher are now separate plugins that you can install if needed. Create your own plugins to add custom functionality! Plugins can be downloaded from [G3M Plugins List](https://github.com/y114git/ylauncherdata/blob/main/PLUGINS.md) More details in the [Plugins Guide](https://github.com/y114git/G3M/wiki/Plugins-Guide).

- **Built-in Chat:** Chat with other G3M users! The chat is completely anonymous and supports 5 different language channels. Switch between channels for your preferred language.

- **Built-in Patching (Plugin):** The XDELTA Patcher is now a plugin! Create patches without needing separate programs. The process is no different from other patching GUIs. Install the plugin if you need patching functionality.

- **1-Click Installation & External Sources:** Install mods from external sources by creating an archive and providing a direct download link like this: `g3m://{URL}`. When a user enters this link in their browser, G3M will install the mod automatically. This works for both public and local mods, as well as plugins. Details are on the Wiki.

- **Create SHORTCUTS:** Create a shortcut for your game with desired settings and mods. Launching it will immediately start the game with your chosen configuration, even without running G3M first.

- **Customize G3M as you wish:** Change game and mods folders, create your own themes, add background music, or even change the intro sound! And if you want - share with your themes with friends! Quickly access your G3M folder (where mods, settings, plugins, and language files are stored) with a single button in settings.

- **Steam Integration:** Enable an option to launch the game through Steam, ensuring all your achievements and other Steam features work. You can also select a separate game executable file if needed.

- **PortProton Support (Linux):** On Linux, you can use PortProton instead of Wine to run Windows executables. PortProton provides better compatibility for games.

---

### 💻 Download & Support

- **How to download?:** Just download installer or binaries from [releases](https://github.com/y114git/G3M/releases) and launch them.

- **Bugs & Issues:** G3M will be updated many more times with new games and features. Please report all bugs and other issues [on this page](https://github.com/y114git/G3M/issues).

- **Wiki:** For detailed info on "How to properly create mods," "How to change something," etc., please visit the [Wiki](https://github.com/y114git/G3M/wiki).

## Legal

- [`LICENSE`](LICENSE)
- [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)
- [`SECURITY.md`](SECURITY.md)
