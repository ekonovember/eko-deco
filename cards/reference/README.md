# Reference material — cited, not redistributed

This directory holds no files in git. Vendor documentation used to verify the
printed runtime format is **cited here and fetched locally**, never committed:
a manual is someone else's copyrighted work, and committing one puts it in the
history permanently, where "delete it later" does not undo publication.

Drop a downloaded copy in this directory if you want it to hand — `.gitignore`
keeps it out of the repo.

## MultiDeco-X1 user manual v5.14 — HHS Software Corp.

| | |
|---|---|
| Source | <https://www.hhssoftware.com/multideco-x1/MultiDeco-X1.pdf> |
| File | `MultiDeco-X1-user-manual-v5.14.pdf` |
| Size | 2 016 368 bytes |
| SHA-256 | `a76a3436b2fe172e041603bc5915f091bcd9d4f7c7c8a0a4ad43345b5bbb2f63` |
| Checked | 2026-08-05 (URL live, byte-identical to the above) |

```bash
curl -O https://www.hhssoftware.com/multideco-x1/MultiDeco-X1.pdf
sha256sum MultiDeco-X1.pdf     # expect a76a3436…2f63
```

**What was taken from it:** p. 66 "Dive planning" — the `depth / stop / rt` plan
screen that the `DEPTH · GAS · STOP · RUN` column order follows, and the note
that MultiDeco's planned gas volumes carry **no reserve** (ours add rock bottom
explicitly). Both are recorded in [`../README.md`](../README.md) in our own
words, with the citation. No text, table or figure was copied out of it.

**It is no longer the primary evidence.** Two complete MultiDeco 4.24 plan
exports live in [`../../examples/`](../../examples/), and they pin the format
directly — the leave-at runtimes, the leg-not-hold stop times, the first-stop
padding and the lost-gas column layout — under test in
`tests/test_multideco_scenarios.py`. The manual is corroboration now, not the
source, so nothing here depends on having the file.
