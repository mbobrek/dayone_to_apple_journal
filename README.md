# Day One JSON → Apple Journal

A cautious, resumable Python wrapper that imports a Day One JSON export into Apple Journal through [apple-journal-cli](https://github.com/omarshahine/apple-journal-cli). It preserves entry dates, promotes an initial Markdown H1 to the title, renders the remaining Markdown as rich text, and attaches exported photos/media.

#### Special Thanks
Special thanks to Omar Shahine for creating the [apple-journal-cli](https://github.com/omarshahine/apple-journal-cli), which provides the underlying Apple Journal integration this project depends on.


> [!WARNING]
> Back up first. Apple provides no public migration API for this workflow. `journal-cli` writes to Apple Journal's private, undocumented data store; a macOS update may break it, and a bad write can affect data that syncs through iCloud. Test with a small disposable journal before migrating an archive.

## What this project does

```text
Day One JSON export + adjacent photos folder
                    ↓
         dayone_to_applejournal.py
                    ↓
              journal-cli
                    ↓
              Apple Journal
```

The script is a parser and migration wrapper. `journal-cli` performs the Apple Journal write, backup, verification, and sync-engine integration.

## Requirements

- A Mac running macOS 14 or later with Apple Journal available
- Python 3.9 or later (the script uses only the standard library)
- [Homebrew](https://brew.sh/) and `journal-cli`
- Full Disk Access for the terminal application used for the migration
- A Day One JSON export with its media folder intact
- A destination journal created in Apple Journal
- Enough local disk and iCloud storage for the imported entries and media

## 1. Back up Apple Journal

In Apple Journal, choose **Journal → Settings → Export Journal Entries…** and save the export somewhere safe. Keep your original Day One export untouched too.

`journal-cli` also creates a timestamped local snapshot in `~/Backups/journal-cli/` before live writes. That snapshot cannot undo data that has already synced to iCloud, so it is not a substitute for your own backup.

## 2. Install the prerequisites

### Install Homebrew

Use the installer shown at [brew.sh](https://brew.sh/):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

At the end, follow Homebrew's printed instructions to add `brew` to your shell. Typical locations are `/opt/homebrew` on Apple silicon and `/usr/local` on Intel Macs. Verify:

```bash
brew --version
```

### Install journal-cli

```bash
brew install omarshahine/tap/journal-cli
```

Upgrade an existing installation with:

```bash
brew update
brew upgrade journal-cli
```

### Grant Full Disk Access

Open **System Settings → Privacy & Security → Full Disk Access**, enable the terminal application you will use, then fully quit and reopen it. Access is granted to the terminal application—not just this Python script. You can remove it after the migration.

Verify access:

```bash
journal-cli doctor
journal-cli journals
```

Do not continue until `doctor` succeeds.

## 3. Export from Day One

Export each Day One journal as **JSON including media**, then extract the archive. Keep the JSON file beside its `photos` directory:

```text
2015 Life Capsule/
├── 2015 Life Capsule.json
└── photos/
    ├── abc123.jpeg
    ├── def456.heic
    └── …
```

Do not move the JSON away from its media. The importer resolves media paths relative to the JSON file.

## 4. Prepare Apple Journal

1. Open Apple Journal and create the destination journal, ideally with the same name as the Day One journal.
2. Let Apple Journal finish any existing iCloud sync.
3. Fully quit Apple Journal before running a live import. `journal-cli` refuses live writes while the app is open.

Journal membership created by `journal-cli` is initially Mac-local staging. After importing, use `journal-cli sync-journals --journal "Name"` to audit the staging and print the current native Apple Journal finalization steps.

## 5. Download and preview

Place `dayone_to_applejournal.py` somewhere convenient. It is dry-run by default:

```bash
python3 dayone_to_applejournal.py \
  "/path/to/2015 Life Capsule.json" \
  --journal "2015 Life Capsule"
```

For a small rehearsal, add `--limit 5`. Dry runs call `journal-cli write --dry-run`, create no entries, and do not update the ledger.

## 6. Run a live import

Quit Apple Journal, then run:

```bash
python3 dayone_to_applejournal.py \
  "/path/to/2015 Life Capsule.json" \
  --journal "2015 Life Capsule" \
  --live
```

On the first live write, `journal-cli` requires its own interactive risk acknowledgment. This script deliberately does not bypass it.

An example using an external drive (change every path and name to match your Mac):

```bash
python3 ~/Downloads/dayone_to_applejournal.py \
  "/Volumes/External Drive/Day One Export/2015 Life Capsule.json" \
  --journal "2015 Life Capsule" \
  --live
```

## Duplicate protection and resumability

After each successful live write, the script appends that Day One UUID to a durable JSON Lines ledger beside the export:

```text
.2015 Life Capsule.apple-journal-ledger.jsonl
```

Rerunning the same command skips completed UUIDs for that destination journal. If an entry has no UUID, the script uses a deterministic SHA-256 fingerprint of its source record. You can choose another location with `--ledger /path/to/ledger.jsonl`.

Keep the ledger with the export. Do not edit or delete it unless you intend to re-import entries. A crash in the tiny interval after Apple Journal accepts an entry but before its ledger record is flushed can still create one duplicate on the next run; spot-check around the interruption point.

## What is imported

| Day One data | Result |
|---|---|
| Entry date | Preserved as a calendar date |
| First `# H1` line | Apple Journal title |
| Markdown body | Journal rich text via `--markdown` |
| Exported photos/media discoverable by filename or ID | Attached |
| Markdown image placeholders | Removed from body to avoid duplicate link text |
| Empty records | Skipped |
| Day One UUID | Stored only in the local ledger |
| Tags, weather, activity, and metadata not listed above | Not imported |
| Exact timestamp/time zone | Not preserved; date only |
| Audio, drawings, PDFs, and Day One-only objects | Not supported by this wrapper |

The upstream project now ships a separate importer that reads Day One's live SQLite store and can preserve more metadata, including original time zones and locations. This repository intentionally supports portable Day One JSON exports and does not access Day One's private database.

## After the import

1. Run the journal-membership audit:

   ```bash
   journal-cli sync-journals --journal "2015 Life Capsule"
   ```

2. Follow the native finalization steps it prints.
3. Open Apple Journal on the Mac and inspect entries from the beginning, middle, and end of the date range. Check titles, bodies, media, dates, and journal assignment.
4. Leave the Mac awake and on power while Apple Journal/iCloud syncs.
5. Check the iPhone or iPad only after the Mac settles. Counts may appear before media and journal assignments finish reconciling.
6. Keep the Day One export, migration ledger, and backups until all devices agree.
7. Optionally remove Full Disk Access from the terminal application.

## Troubleshooting

### `brew: command not found`

Complete the shell setup command printed by the Homebrew installer, open a new terminal window, and rerun `brew --version`.

### `journal-cli doctor` reports inaccessible data

Grant Full Disk Access to the exact terminal application you are using, quit it completely, reopen it, and rerun `journal-cli doctor`.

### Live writes are refused because Apple Journal is open

Quit Apple Journal with **Journal → Quit Journal**. Closing its window is not enough.

### Destination journal is missing or entries land in the default journal

Create the journal in Apple Journal first and spell its name exactly. After import, run `journal-cli sync-journals --journal "Name"` and follow its finalization instructions. Journal routing is staged until Apple Journal authors its native membership data.

### Photos are missing

Keep `photos/` beside the JSON file. Check that the export actually contains the media files; a JSON reference alone is insufficient. The summary can succeed for text while a referenced file is unavailable.

### Photos appear as Markdown links

Use this script rather than an older text-only version. It removes Markdown image placeholders and supplies discovered files through `journal-cli --media`.

### `nothing to write`

Day One exports may contain empty records. This script skips records with no title, body, or resolved media.

### An import stopped partway through

Fix the reported problem and rerun the identical command. Completed UUIDs are skipped. By default the importer stops on the first failure; `--continue-on-error` processes the rest and returns a failure status at the end.

### A large import looks stuck

Media processing, backups, and iCloud work can take time. Do not force-quit immediately. Test with `--limit 5`, confirm the result, and then run without a limit. Keep the Mac awake and connected to power.

### The ledger is corrupt

Do not delete it reflexively. Make a copy, repair or remove only the malformed line, then rerun. Deleting the whole ledger removes duplicate protection for every completed entry.

## Command reference

```text
usage: dayone_to_applejournal.py JSON_EXPORT --journal NAME [options]

--live                 Perform writes; omitted means dry-run
--ledger PATH          Override the default adjacent ledger
--journal-cli PATH     Use a specific journal-cli executable
--continue-on-error    Continue after failed entries
--limit N              Process at most N eligible entries
--version              Print the importer version
```

## Safety and limitations

- This project is unofficial and is not affiliated with Apple, Day One/Bloom Built, or the `journal-cli` author.
- A dry run validates command construction but cannot guarantee that a later live write or iCloud sync will succeed.
- Never run two imports against the same Apple Journal store concurrently.
- Do not open Apple Journal during live writes.
- Do not rename or reuse a ledger for an unrelated export without understanding the UUID collision risk.
- CLI-written entries do not contain Apple Journal's app-authored text CRDT; see the upstream project's documentation before editing or merging them across devices.
- Review upstream release notes before a migration, especially after macOS or Apple Journal updates.

## License

MIT. See [LICENSE](LICENSE).
