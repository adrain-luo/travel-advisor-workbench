# Independent Codex deployment handoff

## Ready-to-use task

Deploy this private release of Travel Advisor Workbench on a supported Windows host using only this repository, its versioned release assets and this document. Install declared dependencies in a new virtual environment; verify and import the sanitized dataset into a new data directory; start on an unused loopback port; inspect the Chinese UI and real saved media; run the smoke check and backup/restore verification; stop only the instance you started. Preserve any existing installation. Keep live WeChat collection, foreground collection and online AI disabled. Do not request or reuse the original collecting account, native databases, keys, sessions or sync cursors. Report actual results and remaining boundaries.

## Read order and prerequisites

1. AGENTS.md and README.md.
2. This handoff and docs/DATA_PACKAGE.md.
3. docs/RELEASE_VALIDATION.md and the release build manifest.
4. docs/DEPLOYMENT.zh-CN.md for the human-facing operating guide.

Supported target: Windows 11 x64, Python 3.12 x64, Node.js 24 x64, pnpm 11.25.0 and Git for Windows. Verified interpreter/compiler versions and actual results are in RELEASE_VALIDATION.md. Other operating systems are unverified.

Private repository: https://github.com/adrain-luo/travel-advisor-workbench
Release tag: v2026.10.30.1
Dataset archive: travel-advisor-data-v2026.10.30.1.zip

Authenticate through existing Git Credential Manager, or `gh auth login` followed by `gh auth setup-git`. Never ask for passwords or tokens in chat. The fetch helper obtains credentials in memory through standard Git credential handling and strips Authorization on cross-origin asset redirects. No new collaborators or public visibility are needed.

Initial setup requires network downloads from normal Python/npm package sources. This is not an offline installer. RapidOCR models come from the pinned wheel; no runtime model downloads occur. Windows Chinese fonts are used under the host's own license. Configure TRAVEL_CJK_FONT only if the standard Windows Chinese fonts are absent.

## Installation and retrieval commands

Use a short fresh working path to avoid Windows path-length problems. These are the tested command forms; substitute only your checkout location, interpreter/pnpm paths, fresh data directory and free port.

```powershell
git clone https://github.com/adrain-luo/travel-advisor-workbench.git travel-advisor-workbench
cd travel-advisor-workbench
git checkout v2026.10.30.1
npm install --global pnpm@11.25.0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe .\scripts\verify_resources.py
.\.venv\Scripts\python.exe .\scripts\fetch_release.py --repo adrain-luo/travel-advisor-workbench --tag v2026.10.30.1 --output .\downloads
.\.venv\Scripts\python.exe .\scripts\portable_data.py verify --package .\downloads\travel-advisor-data-v2026.10.30.1.zip
```

If PATH does not select the intended tools, use:
```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -PythonPath 'C:\Tools\Python312\python.exe' -PnpmPath 'C:\Tools\pnpm.cmd'
```

The project must not inherit site-packages from another environment. Setup creates a regular venv. Both requirements.lock.txt and requirements-ocr.lock.txt are installed. The frontend uses pnpm install --frozen-lockfile and pnpm build. Do not copy an existing .venv, node_modules, Codex runtime cache or another person's fonts.

fetch_release verifies private visibility, asset lengths, available GitHub SHA-256 digests, and all SHA256SUMS.txt entries. The dataset verifier checks the logical package/schema version, exact inventory, byte lengths, hashes, fresh SQLite integrity, source links, attachment occurrences and business snapshots. Compare build-manifest.json's source commit against `git rev-parse HEAD`. Do not mix tags, datasets or manifests. No LFS reconstruction is required.

Alternatively extract the complete handoff ZIP: source/ is the verified Git source tree and the data archive is included. Verify its external checksum before extraction. Use the same installation/import commands from source/, adjusting only the dataset path.

## Import, run and validate

```powershell
$dataRoot = Join-Path $env:LOCALAPPDATA 'TravelAdvisorWorkbench\verification'
.\.venv\Scripts\python.exe .\scripts\portable_data.py import --package .\downloads\travel-advisor-data-v2026.10.30.1.zip --data-dir $dataRoot
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -DataDir $dataRoot -Port 8767 -NoBrowser
Invoke-RestMethod http://127.0.0.1:8767/api/health
.\.venv\Scripts\python.exe .\scripts\smoke.py --url http://127.0.0.1:8767 --data-dir $dataRoot --exercise --output .\smoke-result.json
```

--exercise creates comparison/weekly verification records in this isolated imported dataset and tests product editing/version history, restoring the original note. Omit it when checking an installation whose business objects should not be changed.

Expected health: status=ok, schema_version=1, imported_dataset=true, live_collection_enabled=false, requested data_dir. /api/state must have no API key, empty provider endpoint, no selected imported accounts/sources and no executable imported jobs. The Chinese page must load, display 导入资料, and show the package's 9 material cards and 2 products before exercise. Open real product images and check source labels, original publication time versus collection time, order of attachment IDs, and product-source links.

Read DATA_PACKAGE.md and dataset-manifest.json for exact current pending/receipt/media counts and exclusions. Missing native documents are not fabricated. Pending candidates are detached from retries and expiry; receipts preserve corrections without becoming synchronization state for another account.

The smoke command reads every material-linked saved file, validates bytes, exercises structured matching/comparison and Chinese text/PNG/weekly exports. It does not make collection or AI requests. Browser inspection is additionally required to confirm the rendered Chinese UI and actual images, not only HTTP status.

For regression tests, set an unrelated new data directory before importing backend.app. Windows pytest fixtures need a short writable temporary path:
```powershell
$env:TRAVEL_DATA_DIR = Join-Path $env:LOCALAPPDATA 'TravelAdvisorWorkbench\test-bootstrap'
.\.venv\Scripts\python.exe -m pytest -q --basetemp C:\Temp\travel-tests
Remove-Item Env:TRAVEL_DATA_DIR
```
Choose a new basetemp path; pytest owns and may clear it. Tests use synthetic adapters; do not enable live collection.

## Backup, restore, stop and rollback

```powershell
.\.venv\Scripts\python.exe .\scripts\portable_data.py backup --url http://127.0.0.1:8767 --output .\backup-imported.zip
.\.venv\Scripts\python.exe .\scripts\portable_data.py restore --archive .\backup-imported.zip --data-dir "$env:LOCALAPPDATA\TravelAdvisorWorkbench\restore-check"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop.ps1 -DataDir $dataRoot -Port 8767
```

Backup calls the application-supported Store lock/SQLite backup mechanism, preserving a consistent set of committed assets. Restore validates all files and relationships into a new directory. Repeat import of the same package preserves existing changes; a different/non-imported destination is refused. Never replace a user's database in place. Rollback means stopping this instance and starting the preserved prior directory/version. Logs and PID metadata are per-port in .local/instances/PORT; stop verifies executable, command line, start time and instance identity. Do not terminate unrelated Python, WeChat or existing workbench processes.

## Optional new-host collection: separate acceptance item

Do not enable collection while deploying the imported package. For a separately authorized local account/source:
1. Keep the imported package unchanged and create a private local binding from config/live-binding.example.json in the chosen data root as live-binding.json.
2. Replace every placeholder with the newly verified local account/source fields and set fresh_local_binding=true. This file is ignored by Git and must never be released.
3. Set TRAVEL_ENABLE_LIVE_COLLECTION=1 and restart the intended instance, then explicitly use the background binding workflow. It verifies the actual current process/account and selected source before access.
4. New live sources use an account-scoped namespace and must not overwrite/reuse imported sources, jobs, receipts or cursors. Start new history/incremental state only after successful fresh binding and explicit source authorization.
5. Keep TRAVEL_ENABLE_FOREGROUND_COLLECTION unset/0. Foreground clicks, navigation screenshots, debugger attachment, injection and sending messages are outside this deployment task.

New-host native collection compatibility, unavailable remote history and missing source media are unverified. Imported dataset deployment is independently useful. AI provider setup remains deferred.

## Reproducible next sanitized release

Use POST /api/backup on the running authorized source application. Copy the resulting consistent ZIP to a private staging directory outside source/data roots and verify every backup manifest entry before extraction. Do not copy a changing live database independently of its attachments.

Build a private identity-map.json shaped as {"replacements":{"private value":"stable alias"}} covering current/historical collecting owner IDs, names, aliases and machine paths. Review every retained image/document and its metadata locally. Prepare private media-policy.json:
- files maps each snapshot-relative path to action include/replace/exclude, a non-sensitive reason, and replacement_path for locally sanitized derivatives.
- candidates may map candidate IDs to exclude_text=true and a non-sensitive reason when a body itself contains excluded private content.
- Never publish either input map, original backup, unreviewed bytes or native caches.

```powershell
.\.venv\Scripts\python.exe .\scripts\portable_data.py export --snapshot C:\PrivateStage\snapshot --identity-map C:\PrivateStage\identity-map.json --media-policy C:\PrivateStage\media-policy.json --output C:\PrivateStage\dataset --version NEW_VERSION
.\.venv\Scripts\python.exe .\scripts\portable_data.py verify --package C:\PrivateStage\dataset
.\.venv\Scripts\python.exe .\scripts\portable_data.py pack --dataset C:\PrivateStage\dataset --output C:\PrivateStage\dataset.zip
.\.venv\Scripts\python.exe .\scripts\privacy_scan.py C:\PrivateStage\sanitized-source --identity-map C:\PrivateStage\identity-map.json --git
.\.venv\Scripts\python.exe .\scripts\privacy_scan.py C:\PrivateStage\public-assets --identity-map C:\PrivateStage\identity-map.json
```

The exporter builds a new SQLite file from explicitly selected fields, copies reviewed retained bytes, rehashes derivatives, preserves useful business versions and detaches processing history. It never sanitizes the original data in place. Media pixel review is required in addition to scanners. Stage an explicit source inventory, initialize a fresh Git repository and scan Git objects plus final archives before uploading. Record every exclusion. Obtain code/data from the uploaded release for a fresh-environment deployment rehearsal and preserve original runtime state.
