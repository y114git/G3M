# Mod Test Fixtures

This directory contains fixture mods used by integration tests for mod discovery,
config parsing, chapter mapping, and file resolution.

## Included Fixtures

- `test_mod_full_structure`: DELTARUNE fixture with `chapter_0`, `chapter_1`,
  and `chapter_2`
- `test_mod_chapter1_only`: DELTARUNE fixture with only `chapter_1`
- `test_mod_multiple_chapters`: DELTARUNE fixture with multiple chapter folders
- `test_mod_demo`: DELTARUNE Demo fixture
- `test_mod_undertale`: UNDERTALE fixture

## Notes

- `mod_config.json` files are intentionally committed and used directly by tests.
- `data.win`, `data_patched.win`, and `patch.xdelta` files are fixture assets, not junk.
- Keep fixture names and folder layout stable unless tests are updated in the same change.
