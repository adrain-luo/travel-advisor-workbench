# Release validation

Release dataset: **v2026.10.30.1**, schema **1**, snapshot **2026-10-30T05:45:00.429063+00:00**. Source commit and artifact hashes are bound by the release build manifest. This report distinguishes the original source snapshot, sanitized package, local deployment and remote reproduction.

## Local preparation: PASS

- The active loopback workbench returned status=ok and its actual configured data root was verified before snapshotting. The application-supported backup held Store.lock, used SQLite backup and included committed assets; no job pause/restart was needed.
- An explicit inclusion manifest constructed a separate staging tree outside the active project and data roots. The original project had no Git repository. Its 99 selected source files retained their original SHA-256 values after preparation.
- Fresh selected-field export reconstructed SQLite from retained logical records, rather than editing/publishing the original database. Every current source/material/product/receipt/candidate association was compared against the source snapshot under aliasing; all checks passed.
- Sanitized export: 9 materials, 2 products, 13 source-event associations, 294 receipts, 73 detached candidates, 47 managed image blobs, 5 saved export files. All payload file hashes and relationships passed. Native IDs remain lossless strings.
- Media review inspected 82 image paths and 4 text exports, plus all 9 nonempty candidate bodies. Six local metadata-stripped PNG derivatives and 36 explicit exclusions (33 files, 3 personal captions) are documented. Two supplier-artwork QR codes were decoded offline, with no network navigation and no known owner identifier.
- Known owner/machine values, credential patterns, recursive archive members/names, image metadata and serialized bytes were scanned locally. Source and dataset scans have zero unresolved findings. Git objects and final bundles are additionally scanned before upload.
- No external AI service or upload scanner was used.

## Installation and regression checks: PASS

A fresh venv was created with Python **3.12.14 x64**; system/user site packages were not inherited. Node.js **24.19.0** and pnpm **11.25.0** built the frozen frontend lockfile. Both Python lock files installed through normal package installation; pip check passed. All three pinned RapidOCR model hashes passed; Chinese exports used the available Windows Microsoft YaHei font. No original virtual environment or runtime cache is distributed.

The full staging suite passed **277 tests** in **30.46 seconds**, with two known warnings: Starlette's httpx TestClient deprecation and a deliberately duplicated ZIP fixture used to reject tampering. A later equivalent synthetic URL-fixture representation was checked separately (1 passed); it avoids a credential-scanner false positive and changes no production code.

A long pytest temporary directory hit Windows MAX_PATH (263-character temporary blob name). The actual test assertions were retained and the complete suite passed in a fresh short test directory. Use short checkout, data and test paths. A restricted execution sandbox also blocked temporary-directory/socket operations; acceptance was run from a normal Windows process, not by treating those restrictions as application failures.

## Local imported deployment: PASS

Using a new data root on alternate port **8767**:
- Health showed imported_dataset=true and live_collection_enabled=false. No imported account/source was selected or locally verified, no active worker/sync state was installed, and the AI provider remained empty.
- All **9 material-linked saved image occurrences** and **39 pending-candidate images** opened through the local API, with matching sizes/hashes and decodable image bytes.
- Source labels, original publication versus collection timestamps, ordered attachment IDs and material/product links passed.
- Product editing/version history, restoration of the edited note, structured matching, comparison, Chinese recommendation text/PNG and weekly text exports passed.
- Browser inspection confirmed the rendered Chinese imported-data banner, nine materials, source details and the real saved sanitized poster.
- Consistent backup and restore to a new directory passed after fixing duplicate ZIP entries for shared export paths. All source occurrences remain separate while shared file bytes are stored once. The restored database retained 9 materials, 2 products, 294 receipts and 73 candidates, plus the deliberate smoke-created recommendation/weekly/export versions.
- The selected test process was stopped with the instance-owned stop script; the original workbench was not stopped.

## Remote delivery and isolated reproduction: PASS

New personal repository: **https://github.com/adrain-luo/travel-advisor-workbench**, confirmed **private** through the authenticated GitHub API. No collaborators or public access were added. The fresh sanitized Git history contains no original project history.

The rehearsal used published prerelease **v2026.10.30.1-rc1**, source commit **2ea92470507172ff57b7f2c459d2379e42ab34b7**. Code was cloned from GitHub into a new short directory; all 99 executable/source inventory hashes matched. A newly created venv installed both pinned Python requirement files from public PyPI with caching disabled. The frozen frontend lockfile installed and built successfully. Dependency integrity, the three OCR model hashes and the Chinese font check passed.

- The full remotely cloned suite passed **277 tests in 17.83 seconds**, with the same two non-failing warnings described above. The checkout remained clean.
- All five published assets were downloaded from GitHub using existing authorized Git credentials. Private visibility, asset lengths, GitHub SHA-256 digests and SHA256SUMS.txt coverage passed, including the complete data and handoff ZIPs. These were actual bytes retrieved from GitHub, not locally substituted files.
- The downloaded complete handoff archive passed ZIP integrity/path checks; all 120 embedded source files matched the remote checkout byte-for-byte, and its embedded dataset and manifest matched the separately downloaded assets.
- The remotely downloaded dataset passed schema, SQLite integrity, all payload hashes and relationship validation, then imported into a fresh data root.
- Port **8768** passed the full exercise smoke check: 9 material-linked image occurrences and 39 saved candidate images opened with matching hashes; product editing/version history and note restoration, structured matching, comparison, Chinese text/PNG recommendation exports and weekly text exports passed.
- Browser inspection confirmed the Chinese imported-data banner, 9 materials, 2 products, source labels, original publication versus collection dates, the real sanitized hot-spring poster and read-only imported candidate previews.
- Repeating import returned already_imported and preserved the exercise-created records. Consistent backup/restore passed; the restored instance on port **8769** again opened all 9 material-linked and 39 candidate images. It retained 9 materials, 2 products, 294 receipts, 73 candidates and the expected exercise additions (3 recommendations, 2 weekly objects, 6 export records; 129 revisions).
- Both isolated instances reported live_collection_enabled=false and an unconfigured AI provider. No executable imported jobs/source indexes were installed. Only the two instance-owned processes were stopped afterward; the original workbench stayed healthy.

The final release is **v2026.10.30.1**. Its executable source, dependency pins and dataset are identical to the successfully rehearsed prerelease; only documentation is finalized. The final build-manifest.json binds the final source commit and archive hashes. The published release notes record the final asset read-back check after publication. The data archive remains **43,048,951 bytes**, SHA-256 **8a8e474a4b4d5fc9c2ae88df27d109955548def200b14e9e01863fb0b4fccf4b**.

The configured host proxy stalled uploads; direct HTTPS for the publishing process succeeded. Downloads through the normal documented fetch helper succeeded. No system/global proxy setting was changed, and no special route or token is embedded in the project.

## Tested command forms

Run from the selected checkout with a fresh data directory and free port:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -PythonPath $Python312 -PnpmPath $Pnpm
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe .\scripts\verify_resources.py
.\.venv\Scripts\python.exe .\scripts\portable_data.py verify --package $DatasetZip
.\.venv\Scripts\python.exe .\scripts\portable_data.py import --package $DatasetZip --data-dir $DataRoot
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -DataDir $DataRoot -Port 8767 -NoBrowser
.\.venv\Scripts\python.exe .\scripts\smoke.py --url http://127.0.0.1:8767 --data-dir $DataRoot --exercise --output .\smoke-result.json
.\.venv\Scripts\python.exe .\scripts\portable_data.py backup --url http://127.0.0.1:8767 --output .\backup-imported.zip
.\.venv\Scripts\python.exe .\scripts\portable_data.py restore --archive .\backup-imported.zip --data-dir $RestoreRoot
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop.ps1 -DataDir $DataRoot -Port 8767
```

The English handoff gives retrieval/version-selection commands and the Chinese guide explains normal operation. The base Python/Node executables were available on this Windows host; all application packages were installed into a fresh venv from declared requirements. This is an isolated reproduction on one Windows host, not certification of every Windows machine.

## Boundaries and preservation

No new WeChat collection was requested, no collection scope was expanded, and no feasibility investigation was restarted. No AI provider was configured. A final read-only preservation audit found all 99 original selected source files, all 33 retained business/attachment records and all 19 referenced media/export paths unchanged. The original recorded process and port remained active; its nine background jobs retained five COMPLETED_LOCAL and four WAITING states, and two legacy jobs retained NEEDS_USER_ACTION. Original source, business records/media, account settings and credentials were not sanitized or changed in place; the supported backup added a new private backup only. Original scheduled jobs were left in their prior operating states, so their own routine timestamps can naturally advance.

Real native document acquisition remains unverified because this snapshot contains no saved document attachment; Chinese text/PNG exports were tested. Missing native history/media stays explicitly missing. The separately documented fresh-account live-collection workflow was validated with synthetic adapters only. Other operating systems and arbitrary long Windows paths are unverified. Supplier offers remain historical evidence, not confirmations of current availability.
