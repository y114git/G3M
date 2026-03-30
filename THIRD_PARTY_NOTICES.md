# Third-Party Notices

G3M is licensed under GPL-3.0-only. See [`LICENSE`](LICENSE).

This project distributes third-party code and binaries. If you redistribute a
release archive, include:

- `LICENSE`
- `THIRD_PARTY_NOTICES.md`
- `SECURITY.md`

## Bundled components

### G3MTool

- Used as a bundled command-line tool for GameMaker file operations.
- Local source path: `G3MTool/`
- License: GPL-3.0-only

### UnRAR

- Used for RAR archive support.
- Bundled binary path: `builds/assets/bin/UnRAR.exe` and
  `src/assets/bin/unrar/UnRAR.exe`
- Upstream project: <https://github.com/pmachapman/unrar>
- License text: see the upstream `license.txt`

## Notes

- G3M also depends on third-party Python and Qt packages listed in
  `pyproject.toml`.
- Those runtime dependencies are covered by the GPL-compatible distribution
  terms of this project and the upstream licenses of the relevant packages.
- Self-contained release archives may include additional upstream notices from
  packaged runtime components.

