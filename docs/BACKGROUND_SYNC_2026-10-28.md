> Historical engineering evidence. Sanitized for distribution; counts and local instructions below are dated history. Follow README.md and docs/CODEX_DEPLOYMENT.md for this release. This file does not authorize collection. Historical local screenshots/native evidence are excluded; current retained data is in the release dataset.

# Integrated background synchronization — 2026-10-28

> **Final reviewed correction:** two OCR false positives were removed, leaving **7 relevant automatic materials plus 2 protected earlier materials**. Final dispositions: **7 keep, 211 skip, 56 pending relevance, 16 acquisition retry**; 25 original business records and 13 original files are unchanged, and 25 unused blobs were removed. **259 tests passed.** The 9-kept / 209-skipped / 11-material figures below are the initial migration checkpoint. See [the correction report](RELEVANCE_CORRECTION_2026-10-28.md) for final evidence and the retained failed/successful guard attempts.

> **Superseded behavior — product correction later on 2026-10-28.** This report is preserved as the earlier full-import checkpoint. Its 21 Moments posts, 269 chat records, 98 saved image occurrences and repeated complete traversals are source-processing history, not current useful-material totals or the current normal polling policy. The current implementation gates product relevance before material creation, keeps minimal processing receipts separately, completes initial local history once, and uses changed-index incremental processing with hourly broader index hashing rather than parsing unchanged bodies. See [RELEVANCE_CORRECTION_2026-10-28.md](RELEVANCE_CORRECTION_2026-10-28.md) for the superseding implementation and final corrected-run evidence.
>
> The live migration examined 290 authorized events: **9 kept, 209 skipped, 56 pending relevance, 16 awaiting acquisition**. Active materials changed from **292 to 11**: 9 relevant automatic materials plus 2 protected earlier materials. All 25 protected pre-existing business records are unchanged; 23 unreferenced blobs were removed and the rollback backup preserved. Two 300-second continuous jobs and two 30-second media jobs are active, with initial history complete. Two unchanged cycles required no expensive content processing. Genuine new native events remain **NOT_TESTED**, missing native history remains **BLOCKED**, and the earlier test totals below are not the final corrected-run totals. The remainder of this report is historical evidence retained verbatim.

The normal workbench now runs the authorized Moments and one-to-one chat reader, durable history/continuous jobs, independent media recovery, and Chinese classification controls. **Overall P0 remains incomplete:** genuinely new content was unavailable during the bounded observation, and no permitted mechanism for requesting records absent from native local history was demonstrated.

This report supersedes earlier implementation-blocked observations for these two sources only. Historical evidence directories and reports remain intact. It does not establish group-chat acceptance.

## Scope and preservation

- Account: **采集账号**, `collector-account-002`.
- Friend: **罗18955311550**, `wxid_8n1ox3efqcat11`; only that author's Moments and that exact one-to-one conversation, both directions.
- Revalidated client: **4.1.15.56**, Weixin PID **43384**, creation time **2026-10-28 13:29:21 Asia/Shanghai**. Process handles, data-directory binding, decrypted self identity and unique exact friend identity were checked again before access. This is a dated observation, not a reusable PID authorization.
- Normal data: `C:\TravelWorkbenchData`; isolated experiments: `.local/integration-20261028`.
- Backup before integration: `backups/backup-20261028T075818-c2cc95.zip` under the normal data root. Final verification backup: `backups/backup-20261028T092010-40ac25.zip`.
- **All 25 pre-existing records and all 13 backed-up files are unchanged.** New authorized account/source/material/job records were added. The two prior sources, seven original attachment records, two products, cases, exports and weekly data were preserved.
- No foreground WeChat interaction, sending, posting, hooks, debugger, hardware breakpoint, injection, process writes, authentication-store inspection, account switching, original database writes, client changes or paid dependency was used. Browser operations targeted the local workbench only. AI configuration remains deferred.

Final independent verification: [production-after-recovery.json](../.local/integration-20261028/production-after-recovery.json). It reads a consistent app backup, compares old record/file hashes, and reopens saved images in a separate process; it does not import the collector or access WeChat.

## Delivered data and separate capability outcomes

| Capability | Implementation | Live result |
| --- | --- | --- |
| Account/source binding | Exact expected account, process generation, directory and friend checks; no fallback | PASS for the stated session; fresh verification also passed after app restart |
| Database-key access | Bounded passive read-only access; keys stay in memory | PASS, authenticated copied databases; independent of image keys |
| Database readability | Consistent copies, SQLCipher page authentication and committed WAL validation | PASS for required contact, SNS, selected message shard, resource and hardlink-index roles |
| Local Moments import | All accessible local dates and independent date ranges | **21 posts**: 1 from 2017, 18 from 2025, 2 from 2026 |
| Local chat import | Exact conversation, shard/table/local-ID identity, direction and compressed-text decoding | **269 records: 168 sent, 97 received, 4 unresolved/system sender**; no encoding issues in this snapshot |
| History absent only from workbench | Resumable batches and independent history cursors | PASS for the available local records; all-history jobs and the 2025 Moments job reached `COMPLETED_LOCAL` |
| Continuous Moments discovery | Active scheduler, durable baseline, full bounded reconciliation and late-arrival catch-up | Operational polling/replay PASS; real newly published post **NOT_TESTED** |
| Continuous chat discovery | Active scheduler, independent progress and downtime catch-up | Operational polling/replay PASS; real newly arriving message **NOT_TESTED** |
| Moments media | Known-record CDN requests and record-supplied decoding references | **48 saved images / 49 media slots**; one native type-6 slot unsupported |
| Chat image-key access | Separate bounded account-matched candidate; validation against exact indexed bytes | PASS; unvalidated candidates expire and are never treated as verified keys |
| Chat image retrieval | Exact message/index association, cached image decoding, bounded offline WXGF conversion | **50 saved images / 65 image occurrences**; 8 missing exact index links, 7 unsupported formats |
| Chat documents | Exact conversation/message resource association plus byte/hash validation | Implemented and fixture-tested; **0 real document samples**, awaiting a real sample |
| Missing native history | Candidate review and passive native-snapshot reconciliation | **BLOCKED**: no compatible remote history-request mechanism demonstrated |
| Missing local chat media | Exact known local paths; concrete per-file failures | **PARTIAL**: no verified background fetch for the 8 absent exact links; 7 additional formats require a verified decoder |
| Workbench integration | Chinese controls, source status, independent job progress, view/correct actions | PASS through the local browser; existing business workflows retained |

The local Moments snapshot spans **2017-10-17 20:42:46 to 2026-10-04 17:33:41**. The selected chat snapshot spans **2026-03-12 21:05:20 to 2026-10-28 15:24:14**, all displayed in Asia/Shanghai. These are observed endpoints, not evidence that every intervening record is available. Requested history ranges are half-open. Moments' observed-range field describes the native rows examined, including rows excluded by the requested import range.

The newer native snapshot already contained ten more 2025 posts than the earlier eight-post phase. Their presence was detected before any remote history request; it is **not** proof that this work retrieved missing native history. Records have 21/269 unique native events and exactly 21/269 source-event revisions after repeated ingestion: no duplicate events were created by the live replays.

All **98 saved images** passed independent size/hash checks and full image decoding. Quality remains **48 `unknown_CDN_rendition`, 21 `unknown_cached_rendition`, 29 `unknown_cached_transcoded`**. The WXGF files are decoded PNG previews, with separate preconversion hash/size/format provenance. None is claimed to be a supplier-original file. The unavailable media remain associated with their original ordered slots and concrete errors.

## Bounded new-content observation

Activation baselines were **17:01:59.557059** for chat and **17:01:59.631355** for Moments on October 28, Asia/Shanghai. The finite acceptance window ended **17:10:27.342287**. No qualifying newly published post or newly arriving selected-conversation message appeared. Both D/E and P0-03 are **NOT_TESTED**, not failed and not passed by empty polling.

The scheduler performed nine complete Moments traversals and 42 chat batches (seven complete selected-chat traversals) by that checkpoint. First-discovery time, native publication/message time and activation baseline are stored separately. Reconciliation counts a new event even when an independent history job imported it first, while excluding material already stored before activation and deduplicating evidence by native event identity.

The later final verification at **17:20:09 Asia/Shanghai** still showed zero qualifying new events. Normal synchronization continues independently of this closed acceptance window.

Evidence: [observation start](../.local/integration-20261028/production-observation-start.json), [observation end and repeat verification](../.local/integration-20261028/production-delivery-verification.json).

## Classification and browser verification

All eight known 2025 posts and **all 30 associated images** were individually inspected and matched by hash. Results: **2 travel promotions, 2 travel-sharing posts, 3 other posts, 1 uncertain post; 2 travel flyers and 28 scenic/personal images**. No additional image-only promotion was found within those eight records. The nine-image scenic reference remains travel sharing. No image in this specific 30-image set is missing or unreadable.

The exact post IDs, ordered image indices, hashes, Chinese labels and evidence are in [eight-known-classifications.json](../.local/integration-20261028/eight-known-classifications.json); the per-post explanation is in [the inspection report](../.local/integration-20261028/eight-known-classifications.md). Import matched all 8 posts/30 images to production bytes, with origin `inspection`. These are assistant inspections, not an automatic vision system or user-authored corrections. Historical promotion classification does not establish current bookability.

The browser exercised account verification; starting both continuous and all-history imports; the 2025 range shortcut; pausing and retrying chat media; resuming history; viewing original text, direction, times, an unavailable image and actual saved images; and saving a classification correction. During this check, the additional May 31 Northern Xinjiang post `14668910138319245825` was classified as a promotion from its explicit package caption. It is outside the known eight and is not an image-only finding. The correction states that the assistant made it, uses the UI's `manual` origin, and survived subsequent live reconciliation. Its image was displayed, but its separate image label was left uncertain.

The final interface distinguishes chat and Moments in source filters and job cards, shows the retrieval timestamp and conservative image quality, and keeps the former foreground collection controls disabled. Screenshots: [account and collected totals](../.local/integration-20261028/workbench-background-final.png), [capabilities and active controls](../.local/integration-20261028/workbench-capabilities-final.png).

## Durability, failures and recovery

Each history, continuous and media job has independent durable state. Events, ordered attachment work and the job checkpoint commit together. Event identity is separate from byte deduplication; decimal native IDs remain strings. Corrections and source revisions survive rescans. Full bounded reconciliation handles older records arriving after a newer watermark. Media failure never erases a committed record or advances another job's cursor.

Snapshots validate generations, copy stability, page authentication and committed WAL frames. New snapshots failing their initial query are removed with a safe audit; committed cursor snapshots survive restart. Parse gaps remain explicit, block history-completeness claims, and allow continuous degraded polling while retaining the latest gap snapshot. Errors never mean end-of-history. Only due media work receives a short delay; future retries use backoff rather than repeated one-second binding probes.

A later live poll produced `ACCOUNT_PROCESS_BINDING_INCOMPLETE`; subsequent checks verified the same authorized account/process. [The observation](../.local/integration-20261028/transient-binding-observation.json) was preserved. This exact incomplete-evidence condition now clears stale cursor/key state and retries with backoff, requiring a fresh complete bind before any data access. Actual account/process/friend mismatches remain blocked. The managed app was restarted at **17:18:23**, the existing Moments job resumed, and live reconciliation succeeded with unchanged event/media counts. Abandoned cursor snapshots without retained parse gaps are safely retired with an audit.

Final actual-process recovery used only isolated fixture workers: PID **27120** was terminated through its verified owned handle after a committed first batch; PID **30500** resumed, revalidated, preserved the cursor, reached two records/two events without duplicates, and saved/reopened the attachment after retry. Both exited. [Recovery proof](../.local/integration-20261028/recovery-final/recovery-result.json). WeChat was not terminated. Earlier independent recovery runs (66500/63600 and 39436/16780) are preserved separately.

## Tests, dependencies and implementation files

**160 tests passed, 0 skipped, 2 existing warnings, 12.81 seconds** in [regression-tests-delivery3.xml](../.local/integration-20261028/regression-tests-delivery3.xml). Warnings concern Starlette's httpx deprecation and an intentional duplicate-ZIP tampering fixture. Tests cover same-second and large IDs, shard collisions, late historical arrival, atomic rollback, stable revisions, concurrent corrections/pause, transient and real identity failures, independent media retries, date ranges, changing DB/WAL generations, malformed records, decoder limits and real synthetic FFmpeg decoding. Fixtures never use business storage or live WeChat.

The production frontend build passed (`tsc -b` and Vite), recorded in [frontend-build-delivery2.log](../.local/integration-20261028/frontend-build-delivery2.log). The earlier 79/90/138/159 counts are dated checkpoints, not the final result. An intermediate regression failed one obsolete foreground-disabled message assertion; the guard itself continued rejecting dispatch. That assertion was updated to the implemented background UI wording. Earlier restricted-execution test attempts stalled before completion; owned test launcher/child pairs **51380/64320** and **32312/45260** were explicitly identified and stopped. They are not counted as passing suites.

Pinned free additions: `zstandard==0.25.0` for native compressed chat bodies, and `imageio-ffmpeg==0.6.0` for its bundled Windows FFmpeg 7.1. Existing bundled `cryptography==50.0.2` is loaded through an explicit dependency path on this host. The FFmpeg resolver avoids environment/system/conda fallback, uses a hidden pipe-only process, discards stderr, and bounds input/output, pixels and execution time.

The reviewed source references are pinned: `fanyuantaier/wechatauto-replica` **6e603974bbac3bda93d88bbd6995510ae2547f5c**, `334456777/WeFlow` **799e440d1bcc8e813cb4402f220c1570839a78cb**, and imageio-ffmpeg source **ae47d8028c237ca5507ceef1b843ee427b442887**. Adapted helpers exclude upstream eager UI imports, authentication/master-cipher branches, account fallback and debugger/hook paths. No original candidate package was initialized. The hicccc77/WeFlow candidate still requires separately supplied native components; neither WeFlow repository became a mandatory dependency. See [candidate review](background-access-candidates.md) and [chat/backfill source review](../.local/integration-20261028/chat-and-backfill-research.md).

Changed/added implementation files:

- `backend/background/{__init__,access,binding,snapshot,moments,native,media,chat,image_access,codec,service}.py`: separated binding, authenticated copies, exact-source records, media and scheduling.
- `backend/store.py`, `backend/app.py`: atomic ingestion, correction preservation, independent background API/lifecycle and existing foreground gate.
- `frontend/src/{BackgroundSync,Classification,App,Settings,NativeCollection}.tsx`, `frontend/src/api.ts`, `frontend/src/styles.css`: Chinese controls, truthful statuses, details and correction UI; rebuilt `frontend/dist`.
- `requirements.lock.txt`, `scripts/stop.ps1`, `scripts/verify_background_recovery.py`, `scripts/verify_background_delivery.py`: dependencies, verified managed-process shutdown, isolated recovery and independent delivery checks. Existing start launchers remain in use.
- `tests/test_background_{native,chat,codec,service,service_extra,api}.py`, `tests/test_operator_positioned.py`: scoped regressions and the updated disabled-foreground message assertion.
- `README.md`, `USER_GUIDE.zh-CN.md`, `docs/CAPABILITIES.md`, `docs/ACCEPTANCE.md`, `docs/P0_BACKGROUND_VALIDATION.md`, this report: dated current behavior and preserved historical evidence.

## Running application jobs

At final verification the normal server was parent PID **66000**, child PID **63096**, with exactly one background scheduler. These are dated process observations; use the managed launcher, not raw PIDs, to stop it.

| Source | Mode | Job ID | Final state |
| --- | --- | --- | --- |
| Moments | Continuous, 60-second interval / 50-row batches | `a244f9af673a4067976f5daea24fd171` | WAITING for next cycle; active |
| Chat | Continuous, 60-second interval / 50-row batches | `5351a146bad8453992333b774e2d8772` | WAITING for next cycle; active |
| Moments | Independent media | `81d3a61881434d25a253bf6518639ad9` | WAITING; active |
| Chat | Independent media | `77fbbd8e2fac4352a9e6c50ca007480f` | WAITING; active |
| Moments | All available local history | `1a62d65163314d95a28f0d38ff85e4af` | COMPLETED_LOCAL |
| Chat | All available local history | `dba654b1dd584a91a2357682acdc6e64` | COMPLETED_LOCAL |
| Moments | 2025 date range | `d763925c0c3542d7bed41605ab1dc2a1` | COMPLETED_LOCAL |

All experiment workers are stopped. Only normal application jobs remain active. Unavailable media are visible and can be retried explicitly; they do not create duplicate material or claim complete coverage.

## Exact operation and reproduction commands

From PowerShell in `C:\TravelWorkbench`, normal operation is:

```powershell
.\start.cmd
# Open http://127.0.0.1:8765/ -> 素材中心 -> 后台同步.
# Use the managed stop command when you want normal synchronization to stop:
.\stop.cmd
```

Equivalent authorized job operations (an existing same-mode/range job is reused):

```powershell
$base = 'http://127.0.0.1:8765'
Invoke-RestMethod -Method Post -Uri "$base/api/background/bind"
$body = @{source_id='background-chat-wxid_8n1ox3efqcat11'; mode='continuous'; interval_seconds=60; batch_size=50; range=@{}} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/api/background/jobs" -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
$body = @{source_id='background-moments-wxid_8n1ox3efqcat11'; mode='history'; range=@{start='2025-01-01T00:00:00+08:00'; end='2026-01-01T00:00:00+08:00'}} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/api/background/jobs" -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
Invoke-RestMethod "$base/api/background"
# Job controls use POST /api/background/jobs/<returned-id>/pause, /resume or /retry.
```

Independent verification and recovery reproduction use fresh evidence names, preserve prior runs, and never operate the WeChat UI:

```powershell
.\.venv\Scripts\python.exe -B scripts\verify_background_delivery.py --name delivery-recheck-1
.\.venv\Scripts\python.exe -B scripts\verify_background_recovery.py --output-root .local\integration-20261028\recovery-recheck-1
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd" --dir frontend build
```

The delivery check intentionally compares the preserved original business baseline and creates an app backup. Later intentional business edits can invalidate that historical comparison. Recovery uses synthetic data and only its own child-process handles.

The exact final regression invocation used isolated environment/storage, with the bundled dependency path appended after pytest import:

```powershell
$env:TEMP='C:\TravelWorkbench\.local\integration-20261028\test-system-temp'
$env:TMP=$env:TEMP
$env:TRAVEL_DATA_DIR='C:\TravelWorkbench\.local\integration-20261028\regression-bootstrap-delivery3'
$env:PYTHONDONTWRITEBYTECODE='1'
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
@'
import pytest,sys
from pathlib import Path
sys.path.append(str(Path(sys.base_prefix)/'Lib/site-packages'))
raise SystemExit(pytest.main(['tests','-q','-p','no:cacheprovider','--tb=short','--basetemp=.local/integration-20261028/regression-temp-delivery3','--junitxml=.local/integration-20261028/regression-tests-delivery3.xml']))
'@ | .\.venv\Scripts\python.exe -B -
```

Use fresh evidence/temp suffixes when repeating. Run that test block in a separate PowerShell session so its isolated data setting cannot affect a later normal launcher. The normal deployment explicitly set `TRAVEL_DATA_DIR=C:\TravelWorkbenchData`, `TRAVEL_ENABLE_FOREGROUND_COLLECTION=0`, removed `TRAVEL_TEST_MODE`, then ran `scripts/stop.ps1` and `scripts/start.ps1 -NoBrowser`.

## Retained P0 boundaries and next mechanism

| Item | Current result |
| --- | --- |
| P0-01 Account/source identity | PASS for current account and exact friend; original group remains suspended |
| P0-02 Bounded history | PARTIAL: available local history imported, native/remote completeness unknown |
| P0-03 Real new-content discovery | NOT_TESTED in the finite window; both continuous implementations remain active |
| P0-04 Group image/document | NOT_TESTED, group outside current active scope; chat evidence does not substitute |
| P0-05 Ordered multi-image Moments | PASS for known eight posts/30 images, including the nine-image reference |
| P0-06 Durable storage | PASS for 290 integrated source records and 98 actual saved images |
| P0-07 Repeat/dedup | PASS for live repeated ingestion and focused legitimate-repeat/revision fixtures |
| P0-08 Interrupt/resume | PASS for the actual owned fixture-process interruption, media recovery and normal app restart; no WeChat termination |
| P0-09 Background operation | PASS for scoped collection and workbench integration without WeChat foreground controls |
| Separate: uncached history / missing-media retrieval | BLOCKED for absent native records and absent indexed chat media; known-record CDN retrieval is separately verified |

The next missing history mechanism is an audited, account-bound background history request compatible with the existing restrictions, plus an independently evidenced older record absent from the baseline native snapshot. Local pagination, changed cache contents without causal evidence, and known media URLs do not satisfy that test. For remaining media, exact authorized index/file availability or a verified additional decoder is needed. A real document and naturally arriving new selected-source events are sample prerequisites, not reasons to manufacture traffic or repeat scope approval.
