> Historical engineering evidence. Sanitized for distribution; counts and local instructions below are dated history. Follow README.md and docs/CODEX_DEPLOYMENT.md for this release. This file does not authorize collection. Historical local screenshots/native evidence are excluded; current retained data is in the release dataset.

# WeChat host and collection compatibility

> **Final reviewed correction:** **7 relevant automatic materials + 2 protected earlier materials**, with **211 skips, 56 relevance candidates and 16 acquisition retries**. Two false positives were removed after exact-image review and a verified narrow rule correction; this does not prove general visual accuracy. All 25 original records and 13 original files remain unchanged, 25 unused blobs were removed, and **259 tests passed**. The 9-kept / 209-skipped / 11-material totals below are the earlier initial migration. [Final correction evidence](RELEVANCE_CORRECTION_2026-10-28.md).

> **Current product correction — later on 2026-10-28.** The full-import behavior and material totals in the historical sections below are superseded by a relevance gate before business-material creation, a separate minimal processing ledger, one-time initial local-history processing, and changed-index incremental checks. Normal checks default to **300 seconds**, with configurable timing, `立即检查` and separate explicit `补充历史资料`; hourly broader index hashing does not parse unchanged bodies. Plausible unresolved candidates remain separate from the default product-material view, and acquisition failure never proves irrelevance.
>
> Live correction: **290 events = 9 kept + 209 skipped + 56 pending relevance + 16 awaiting acquisition**; active materials changed from **292 to 11** (9 relevant automatic + 2 protected earlier). All 25 protected business records remain unchanged; 23 unreferenced blobs were removed with the rollback backup preserved. Two continuous jobs at 300 seconds and two media jobs at 30 seconds are active after initial history. Two unchanged cycles required no expensive content processing; genuine new-event discovery remains **NOT_TESTED**. Missing native history remains **BLOCKED**, AI setup stays deferred and foreground collection stays disabled. [Current correction and final verification](RELEVANCE_CORRECTION_2026-10-28.md). The 21/269/98 counts and test results below belong to their dated earlier phases, not current useful-material counts or final corrected-run totals. Earlier content is retained verbatim.

## Final integrated verification — 2026-10-28 17:20 Asia/Shanghai

The normal workbench now contains **21 selected-friend Moments posts / 48 saved images**, and **269 one-to-one chat records / 50 saved images**. Current-account binding, passive database-key access, authenticated database copies, independent image-key validation, actual file retrieval and separate-process reopening passed separately. Every saved image occurrence passed hash/size/decode checks; none is claimed original-quality. Moments has 1 unsupported media slot; chat has 8 missing exact index links and 7 unsupported image formats. Chat documents are implemented but awaiting a real sample.

Two continuous and two media jobs remain active; local all-history/date-range traversal and live dedup passed. Real new posts/messages were absent during **17:01:59–17:10:27**: new-content acceptance is **NOT_TESTED**. Missing-native history and absent cached-chat-media fetching remain **BLOCKED** without a compatible verified background request mechanism. A later transient incomplete process binding was preserved as evidence, fixed to retry only after full revalidation, and recovered live. Actual identity mismatches remain blocked. **160 tests passed; frontend build passed.** Existing business data is preserved. [Full final outcomes, source pins, commands and evidence](BACKGROUND_SYNC_2026-10-28.md). Older sections below are dated implementation and historical observations.

## Integrated implementation — 2026-10-28

The application now has an integrated background adapter and durable scheduler for account **采集账号** (`collector-account-002`) and the exact friend **罗18955311550** (`wxid_8n1ox3efqcat11`): Moments plus both directions of the one-to-one chat. Previous group/contact sources stay suspended and their records remain preserved. Foreground collection stays disabled. The working implementation and final deployment/live totals are reported separately in [BACKGROUND_SYNC_2026-10-28.md](BACKGROUND_SYNC_2026-10-28.md).

| Boundary | Implemented behavior and evidence scope | Remaining limitation |
| --- | --- | --- |
| Current account/friend binding | Process identity, observed database handles and exact native contact identity gate access; changes invalidate session material. | A successful old binding is not a reusable lease for a changed process/account. |
| Passive database-key access | Approved account-bound read-only memory access validates candidate material against copied encrypted pages; session material is reused only while valid. | No debugger attachment, hardware breakpoints, injection, hooks, login-store access or client writes. Key access is not itself a record/media pass. |
| Database reads | Contact/SNS and selected-conversation message/index snapshots are queried with native identity and time preserved. DB/WAL generation/commit validation and bounded copy retries are implemented. | Local snapshots do not prove server completeness or a cross-database transaction. Parse gaps remain visible. |
| Continuous discovery | Persisted baseline, intervals, bounded batches, source ownership, repeat reconciliation, pause/resume/retry and restart recovery are integrated. No 2025 restriction in continuous mode. | Genuine post-baseline Moments and chat arrivals require their own live evidence. Quiet polls and old-record imports do not pass that boundary. |
| Local historical import | All available local records or date-bounded traversal, separate from continuous and media jobs. | **All available local history is not all remote history.** Coverage stays unknown even after local traversal. |
| Records missing from native history | Capability explicitly **BLOCKED**. | No verified source-bound background mechanism retrieves a known record absent from native local data. No foreground fallback. |
| Moments media | Only exact record-associated advertised references; ordered slots, byte hashes, decoding, saved files and independent reopening. | Unsupported/missing media remain explicit; `unknown_CDN_rendition` is not original-file quality. |
| Chat images | Exact message/index association, local cached bytes, separately validated decoding and bounded passive image-key candidates; transcoded output retains a conservative quality label. | Database keys and successful Moments downloads do not establish chat-image success. Latest retry totals remain in the dated report. |
| Chat documents | Implemented scoped local-file retrieval and content validation. | The preliminary selected conversation has no suitable document sample: **awaiting a real sample**, not a document pass. |
| Classification | Post purpose and image type are independent; evidence/origin are visible and user corrections persist across ingestion. | Inspection of the known eight posts is a finite labeled baseline, not a deployed vision-provider quality pass. AI setup remains deferred. |

Preliminary isolated integration observations, before final media retry: **21 Moments posts, including 18 dated 2025; 48 saved Moments images and 1 unsupported reference; 269 chat records (168 sent, 97 received, 4 direction-unknown), with 65 image references and 0 document samples.** The 65 references are not a claim that 65 image byte sets were retrieved. These are intermediate local-snapshot counts, not a final total or full-history claim. They supersede neither the historical snapshot's eight-post count nor its exact observations; the later snapshot is different.

The eight previously known 2025 records were all inspected with all **30 images**: **2 travel promotions, 2 travel-sharing, 3 other and 1 uncertain-purpose post; 2 flyers and 28 scenic/personal photos**. No additional image-only promotion was found. The results use `origin: inspection`, not user-manual correction. See [inspection report](../.local/integration-20261028/eight-known-classifications.md) and [indexed labels/hashes](../.local/integration-20261028/eight-known-classifications.json).

## Earlier isolated result — 2026-10-28, 14:13 Asia/Shanghai

The user-selected current account **采集账号** was bound to its running **4.1.15.56** process and contact/SNS files. The approved passive key-access route and copied-database reading passed. An exact-author query for friend **罗18955311550** found **8 locally cached 2025 posts**; **2 travel promotions and 1 supplemental nine-image post** were persisted as **3 materials / 11 images**, all reopened in a separate process. Full-year coverage, uncached backfill and new-post discovery remained unverified. At this phase the original business data was unchanged and the path was a bounded diagnostic, not yet a production collector. See [dated evidence and that phase's P0-01–09](P0_BACKGROUND_VALIDATION.md#first-real-background-read).

## Earlier October 28 background review — retained history

**Dated P0 verification, 2026-10-28:** [P0_BACKGROUND_VALIDATION.md](P0_BACKGROUND_VALIDATION.md) records the post-handoff baseline, both pinned WeFlow reviews, the separate group/Moments P0-01–09 matrix, 8 newly run targeted tests, and an owned-process offline restart/dedup/retry proof. Live background acquisition remains **BLOCKED**. Historical and earlier October 28 evidence below is preserved; the new report also records the already granted, narrowly scoped read-only key-access approval and its unmet prerequisites.

## Earlier decision and background-access verification — 2026-10-28

**Foreground collection and screenshot/OCR navigation are suspended. Both selected-source background collectors remain BLOCKED, not P0 complete.** There is no pending desktop handoff. Material-content OCR is unaffected; online AI configuration remains deferred. The earlier native evidence below is historical and must not be read as the current implementation route.

The current application rejects new foreground establishment/scan/resume/retry requests before dispatch, and checks queued work before constructing a native adapter. The queue, immutable files, source-event deduplication, checkpoints, independent media retries, uploads and business workflows are retained. Foreground code is dormant and unverified; `TRAVEL_ENABLE_FOREGROUND_COLLECTION` must remain unset for this deployment. It is an engineering override, not an operator setting or an authorized next step.

### Actual access point and bounded local proof

The probe reads **local filesystem metadata, format headers and a read-only SQLite schema query**, using `scripts/probe_background_access.py`. It does not read message rows, login/key stores or process memory, and does not contact a server or invoke WeChat UI. Results are in `.local/background-access-2026-10-28/storage-probe.json` and `host.json`.

- The configuration points to `D:\Software\Weixin\Chats\xwechat_files`. Three account-shaped directories exist. Their names are candidate account identifiers; none is verified as the selected travel-advisor account. Display-name bindings in the app remain manually observed evidence, not native database IDs.
- At the current probe, **no Weixin/WeChat process was running**. Installed executable `D:\Software\Weixin\Weixin\Weixin.exe` reports **4.1.15.56**. A loaded-client version therefore cannot be verified. The probe did not launch it.
- Five database categories per account were checked: `contact/contact.db`, `session/session.db`, `message/message_0.db`, `message/message_resource.db`, `sns/sns.db`. **All 15 had non-SQLite headers and returned `file is not a database`** to ordinary SQLite. This establishes that ordinary SQLite cannot read them; encryption/codec details are candidate-tool claims, not proven by that error alone. Sizes/modification timestamps remained unchanged.
- The three `msg/attach` trees contained 335, 37 and 9,458 filesystem entries. All 24 sampled headers matched a candidate V2 container marker; they were not decoded or counted as acquired images.
- The three `msg/file` trees contained 8, 1 and **at least 10,000** entries; the last hit the explicit enumeration cap and includes nested extracted folders. These are filesystem counts, not attachment/message counts. Sample headers included ordinary compound documents, ZIP containers and PDF. Their chat/source membership is unresolved, so unrelated files were not imported.
- `business/sns` contained 1, 0 and 4 files with JPEG headers. These five files are **not identified as five selected-contact post images**: they could serve other cache roles, and author/post/order/original-quality relationships remain unknown.
- An exact-byte search using the two prior authorized, manually saved JPEGs found **zero matches within the probed trees**. It does not prove absence elsewhere or absence of differently encoded versions. Three backup account directories were present but had no files in the bounded metadata inspection; no usable export was established.
- This iteration acquired **0 selected-source records, 0 page observations, 0 attributed images, 0 group files and 0 verified multi-image posts**. No scan/checkpoint was fabricated. The two prior manual records retain their labels and the dataset remains intact.

### Capability boundaries under the background requirement

| Capability | Selected group | Selected contact's Moments |
| --- | --- | --- |
| Account/source identification | BLOCKED: contact/session databases unreadable by ordinary SQLite; group ID unresolved | BLOCKED: account/contact ID unresolved; cache paths do not prove author identity |
| Locally cached content | PARTIAL for filesystem existence/signatures only; message records unreadable | PARTIAL for database/cache existence only; posts unreadable |
| Requested historical timeframe | NOT_TESTED: no source records or timestamps read | NOT_TESTED: no posts or timestamps read; cached feed is not complete contact history |
| Proactive uncached history/media retrieval | No verified background endpoint | No verified background endpoint; candidate cached SNS reader has no proven backfill |
| Actual image/file acquisition | 0 attributed files saved; ordinary cached document bytes may be usable once source linkage is verified | 0 attributed images saved; no complete post media set |
| Online-document link full text | NOT_TESTED/UNIMPLEMENTED: message/card/link metadata is not document body; actual URL, access rights and provider export/reader are required | Same boundary for linked documents |
| Multiple images and ordering | Not established for compound media messages | NOT_TESTED: expected count, saved count and order unknown; no missing slot may be silently dropped |
| Repeat/incremental/resume | Existing storage mechanics pass fixtures; no live background pass | Same; no source cursor or historical endpoint proven |

For a future verified post, persist the native post identity, ordered media IDs, expected count, per-slot saved hash/quality and explicit `PENDING`, `RETRY` or `UNAVAILABLE` states. Count a post's media complete only when every advertised slot is accounted for; do not infer missing images from directory order or a thumbnail count. This is an acceptance rule, **not an implemented live parser claim**.

Code-backed candidate mechanisms and exact-version limits are in [the focused candidate review](background-access-candidates.md). The strongest cached-data lead requires database keys read from process memory when no valid key is supplied. It has not been installed, activated or accepted as a dependency. The original brief, section 4, says not to silently make encrypted-database key extraction a dependency. Any such experiment requires a specific scope decision first; even success would not establish uncached-history retrieval. No account auto-switching or fallback to foreground retrieval is authorized.

### Verification and reproduction

Run the metadata-only probe while leaving WeChat alone:

```powershell
.\.venv\Scripts\python.exe scripts/probe_background_access.py --root 'D:\Software\Weixin\Chats\xwechat_files' --output '.local/background-access-check/storage-probe.json'
```

Optional `--reference` arguments accept already-authorized saved media; only exact matching bytes may be copied to the evidence directory, and they still do not become source records. The probe refuses output inside the WeChat tree. It never decrypts data or changes the source files.

**90 tests passed**, with two existing warnings, in the October 28 regression run. This includes foreground-dispatch denial, committed-progress preservation, and the probe's read-only/no-false-record boundaries. The frontend build passed. The restarted real app reports `foreground_collection_enabled=false`, preserves two manual materials, and exposes zero native sessions/page observations. These checks do not establish background acquisition. Evidence: `.local/background-access-2026-10-28/{pytest-results.xml,app-before.json,app-after.json}`.

## Historical native inspection — October 25–26

Native inspection: 2026-10-25, Asia/Shanghai. Evidence import and application follow-through: 2026-10-26. This report distinguishes manual client observations, persisted manual evidence, and implemented portable code. **Required automatic group and selected-contact Moments collection remain blocked.** The manual proof reached both selected sources and saved one image from each. Those two observations and two conservative product drafts are now persisted in the real application, visibly labeled as manually assisted acquisition. They support a partial manual workflow through matching and example output; they do not establish that the automatic collectors work. AI setup was explicitly deferred by the user.

## Actual host evidence

| Observation | Evidence and result |
| --- | --- |
| Host | Windows 11 Home Chinese, build 10.0.26200, 64-bit; interactive session available; Weixin processes in session 1. |
| Client | `D:\Software\Weixin\Weixin\Weixin.exe`; initial executable `FileVersion` and `ProductVersion` observation was **4.1.13.65**. A later read of the same path returned **4.1.15.56**, independently through PowerShell `VersionInfo` and the public Windows version-resource API. The currently loaded process version is **unconfirmed**. This records two observations; it does not establish when or whether the running client changed. No installation change was performed by the implementation team. |
| Runtime | Bundled Python **3.12.14**; local `.venv` created for application dependencies. |
| Desktop | Initially no exposed WeChat window. Root agent launched the existing executable, which restored the logged-in client window. Initial screenshot measured 819 × 674 pixels. A later user-prepared window measured 984 × 643 and already displayed the selected contact's chat and a right-side `朋友圈` album. Display scaling was not established; no calibrated unattended navigation is claimed. |
| Accessibility | Root was the only live UI owner. Initial Computer Use tree contained `微信` → `Weixin` → `MMUIRenderSubWindowHW`; the later album surface still exposed rendering panes and a generic embedded document (`view_1030`, object-replacement document text), not post, sender, time, or media controls. This is a real observed compatibility blocker, not a missing selector guessed from documentation. |
| Account | The account profile display and region were manually observed: 采集账号, 安徽芜湖. A local evidence binding and profile screenshot are persisted. No stable native account ID, automatic re-identification, or account-change recovery was verified. Local application IDs are not asserted to be WeChat IDs. |
| Selection | The user explicitly selected group **芜湖联众芜湖同业群** and contact **完美新疆西北赵照18552600189**. These selections authorize only those sources. Two source observations are persisted with `acquisition_method=assistant_native_ui_manual`; their source types remain `group` and `moments`. No automatic scan result or discovery checkpoint was created by this import. |
| Group evidence | Root visually verified the exact selected group header and history title, with member count `(497)`. History showed a travel poster and adjacent text with `2026年10月25日 21:55`, then an older loaded view at `21:49`. Root saved a poster through the client's image viewer. The file filter showed `无内容`; no group document was saved and no accessible endpoint was proven. |
| Contact album evidence | The user initially opened the contact-specific album. Root subsequently verified the full selected author name, observed post time `昨天09:07` on 2026-10-25, and traversed the album from Yesterday to October 13 over five scrolls. One post image was saved through native Save As. No multi-image post was observed; this is not proof of a complete ordered image set or automatic collection. |
| Interrupted interaction | An earlier profile-navigation attempt opened an unused group-creation dialog; no member was selected and no creation submitted. Escape reported `user input detected`, after which root stopped until a desktop handoff. Later manual proof resumed. This shows cautious operator behavior, not an application-worker interruption/resume pass. |

## Candidate comparison

| Candidate | Checked evidence | Decision |
| --- | --- | --- |
| `wxauto4` free | Author documents support through client 4.1.8.107; both observed host executable versions are newer. Original `cluic/wxauto4` repository says development stopped. | Not installed or selected as a verified solution. |
| `wxautox4` Plus | PyPI version observed on October 25: **41.2.1**. Author documents license activation and marks history traversal, account detail, file retrieval and Moments as Plus capabilities. | No license purchased or activated; methods were not represented as implemented live capabilities. Licensing alone would not establish contact-album traversal on this host. |
| Native UIA | Implemented `NativeUIADriver` uses pywinauto's accessibility selectors, invocation/value/selection patterns and scrolling. **pywinauto 0.6.9** is installed in the application environment; BSD 3-Clause. | Installed replaceable implementation route; no verified host enrollment exists because the observed content tree is collapsed. Package installation is not a live collector pass. No default fabricated selectors are shipped. |
| Built-in Windows OCR | `Windows.Media.Ocr`, installed `zh-Hans-CN`, maximum image dimension 10000, invoked through Windows PowerShell 5.1. A saved-image-only spike tested bounded crops from the selected group and contact evidence. | No target identity or publication-time string was recognized reliably across the three preprocessing variants. This local bridge is not connected to a native collector. |
| `wechatauto-replica` | Maintainer describes memory writes to enable its UIA path and encrypted database/key extraction for reading. | Excluded under the brief; not installed or invoked. |

Primary references, checked on the inspection date: [wxauto installation and licensing](https://docs.wxauto.org/docs/install.html), [history traversal](https://docs.wxauto.org/docs/class/WeChat.html), [message and media semantics](https://docs.wxauto.org/docs/class/Message.html), [Moments methods](https://docs.wxauto.org/docs/class/Moment.html), [original repository](https://github.com/cluic/wxauto4), [pywinauto documentation](https://pywinauto.readthedocs.io/en/latest/getting_started.html), [pywechat maintainer's current accessibility limitation](https://github.com/Hello-Mr-Crab/pywechat/blob/main/Weixin4.0.md), and [replica maintainer's implementation explanation](https://github.com/fanyuantaier/wechatauto-replica/blob/main/README_pypi.md).

The Moments documentation describes the general feed and pagination. It does not establish opening one contact's accessible album history, reliable post publication-time evidence, or retrieving a complete multi-image post. Feed filtering is deliberately rejected by `WeChatMomentsAdapter`.

## Historical capability matrix — October 26

| Required capability | Live status | Evidence / smallest unresolved step |
| --- | --- | --- |
| Restore and view installed client | PASS | Existing executable restored the visible logged-in shell; no installation changes. |
| Verify active account and disambiguate selected source | PARTIAL | Account display/region, exact selected group/history title and full selected contact author were visually verified and retained in a local evidence binding. Stable native identity, same-name disambiguation and automatic target reopening remain unverified. |
| Group history across multiple pages | PARTIAL | Manual history navigation showed 21:55 and an older loaded view at 21:49 on October 25. Semantic rows and automatic pagination are still unavailable. One manually transcribed source record is persisted; the importer created no scan/checkpoint. Later explicit scan requests remained blocked with zero discovered records. |
| Group image and document saved | PARTIAL | One client-viewer JPEG saved and byte-validated. The file filter showed `无内容`; no document pass. Automatic attachment retrieval remains unimplemented. |
| Selected contact profile/album surface | PARTIAL | Full selected author and contact-specific history visually verified, not a general-feed filter. Automatic reopening and account/source binding remain unverified. |
| Selected contact post traversal/acquisition | PARTIAL | Manual album traversal from Yesterday to October 13 over five scrolls. One manually normalized post and image are persisted with raw-time evidence. No proven endpoint, automatic page traversal or complete-media coverage is claimed. |
| Moments multi-image post and publication time | PARTIAL | Raw `昨天09:07` and one saved post JPEG observed. Multi-image post discovery and ordered complete-media retrieval remain NOT_TESTED. |
| Date boundary, repeated scan, interruption/resume in client | NOT_TESTED | Offline time/traversal tests pass, but no live acquisition has exercised these behaviors. |
| Native worker ownership and target mismatch handling | PARTIAL | Serialized backend worker and conservative driver revalidation exist. Offline fixtures exercise interference; live interruption not verified. |
| Upload path | PASS for adapter mechanics | Local file fixture retains unknown source publication time, saves validated bytes and hash; API acceptance is reported separately. This is not WeChat proof. |

## Implemented boundary and honest limits

The three adapters share `probe_capabilities`, `resolve_source`, `iterate_items`, and `fetch_attachment`. Real WeChat pages are normalized only after source/account verification. A date-filtered scan retains unknown dates, excludes provably out-of-range events, freezes its upper cutoff, and does not stop at the first old record. Empty/repeated views and page budgets report partial/unproven coverage. A checkpoint carries a run cutoff; a completed incremental watermark requires actual endpoint evidence.

In a live-capable client, an engineer can enroll observed selectors using `TRAVEL_WECHAT_ENROLLMENT` pointing to an application-local JSON file. Schema version 1 requires `verified_at`, `evidence_reference`, exact `client_version`, executable/window selectors, persistent account identity rules, and a separate route for each supported source type. The driver reads the executable's public version resource before attaching; a missing/unreadable version or a changed version at the same path blocks stale enrollment. Each route supplies source-opening steps, source identity rules including a discriminator beyond a display name, an observed container/item/text/time/author mapping, media controls, and optionally an observed endpoint control. Moments requires `surface: "contact_album"`. Selectors are matched uniquely; ambiguity or lost foreground stops collection. Search inputs are restricted to search controls. Send/post/like/comment/delete/payment actions are refused. **No valid enrollment is supplied for this inspected host.**

This boundary is not a claim that configuration alone fixes an inaccessible client. An offline OCR bridge now exists in `backend/collectors/local_ocr.py` and `windows_ocr.ps1`, but a calibrated visual collector has not been implemented or verified. The saved-image-only experiment failed reliable source/time recognition; details follow below. Native original/file retrieval is still unimplemented for the inspected client. The native driver returns a retryable media gap. Cross-run event identity also requires live overlap evidence: temporary UI IDs are never treated as persistent IDs. Conservative adjacent-page reconciliation exists, while ambiguous repeated occurrences remain separate. Restart replay can retain additional uncertain occurrences rather than silently delete legitimate posts.

Resume now gives new pages their own budget after a verified saved overlap sequence is reached. Replay pages do not consume that budget, an unlocated/ambiguous anchor remains partial, and replay never regresses the stored frontier. These mechanics are fixture-tested; they do not establish cross-run identity for the actual visual client. Compact relative labels such as `昨天09:07` retain raw evidence and minute precision, rather than inventing exact seconds.

## Saved-image OCR feasibility

On October 26, the built-in OCR engine was run only against selected crops from the already saved `group-history-timestamps.png` and `moments-post-detail.png`. It performed no desktop capture or input and activated no adapter. `.local/live-evidence/ocr-feasibility-2026-10-26.json` records source hashes, crop bounds, raw output and the human reference strings. Grayscale enlargement with no threshold, threshold 180 and threshold 220 all failed to reproduce the group header/time and contact author/time accurately enough for unattended identity or publication-time decisions. No confidence score was available; OCR output was not promoted to normalized source records.

Returned word boxes and lines do not establish message/post boundaries or complete media sets. Embedded poster text mixes with surrounding post text, and thumbnail geometry alone does not establish a complete single-image or multi-image post. The bridge therefore always reports identity as unverified, preserves source bytes, removes temporary crops and rejects unsafe coordinate assumptions. This credential-free experiment narrows the next engineering work; it does not change either collector's blocked status. No additional OCR package, paid service or WeChat modification was used.

## Local manual evidence

Native evidence is kept in `.local/live-evidence/`. `scripts/import_live_evidence.py` additionally preserved seven media/evidence blobs, two selected-source records and two conservative product drafts in `C:\TravelWorkbenchData`. It is an explicit offline, idempotent evidence import, not a scanner or the upload adapter: it creates no jobs/checkpoints and refuses to overwrite later human edits. The application shows `实机人工辅助采集 · 自动采集尚未验证`, retains `coverage=UNKNOWN`, and separates `client_saved` quality from screenshots/originals. Observation date is October 25 at day precision; import time is October 26. Missing product years remain unknown and are not filled from either clock. Screenshots include `group-selected-page1.png`, `group-selected-page2.png`, `group-history-timestamps.png`, `group-history-older-page.png`, `group-documents-empty.png`, `moments-album-page1.png`, `moments-album-page2.png`, `moments-album-oct13.png`, and `moments-post-detail.png`. They document the single-owner native proof, not scanner output.

| Saved client image | Validated bytes | Dimensions | SHA-256 |
| --- | --- | --- | --- |
| `group-selected-poster.jpg` | 2,203,596 | 1182 × 2598 | `7e88abd7c837c4d09b65db5b7179defd9c1492a5ae80e2ec269d8674a7aadf7f` |
| `moments-selected-post.jpg` | 398,752 | 1080 × 2450 | `5dcde026b5ca437f25b14ad1707f08f6862f2b2e9245471a03ccf298d753d804` |

Both files decode as JPEG. Their byte quality relative to supplier originals is unknown; they are not labeled original-quality. A manual Save/Save As result is not a working durable `fetch_attachment` implementation.

Application follow-through is recorded in `docs/evidence/live-followthrough.json`; browser-only preview/clipboard checks are recorded separately in `docs/evidence/browser-followthrough.json`: both imported JPEGs reopened with matching hashes; an explicitly labeled example case produced conservative matching, editable Chinese text, a source-snapshot PNG and matching clipboard/export text. A real dataset backup was restored into a separate directory. `comparison-live-example.png` and `recommendation-live-example.txt` are real-source software-verification examples, not confirmed customer quotations. This makes A22 partial for a continuous **manual** workflow; automatic collection remains blocked. Live AI has not been called because the user deferred setup.

No process injection, memory modification, database key extraction, authentication bypass, downgrade, security-setting change, sending, posting, liking, or purchase was performed.

## Reproducible checks and next action

```powershell
.\.venv\Scripts\python.exe -m backend.collectors
.\.venv\Scripts\python.exe -m pytest tests/test_collectors.py -q
```

The collector suite is explicitly an offline fixture suite: **30 passed** in the latest recorded October 26 run (`docs/evidence/pytest-results.xml`). It verifies date semantics, selected-account/source guards, contact-album enforcement, unproven endpoints, resource caps, ordered overlap, repeated legitimate content, target interference, foreign checkpoints, interruption replay, fresh resume budgets, executable-version guards, independent late-media retries, upload byte integrity, and OCR crop/coordinate safety. It cannot pass A02–A04 or live A22.

The prior proposed foreground-adapter work is superseded by the October 28 background requirement above. Do not resume desktop navigation or ask for a group-ready handoff. The selected sources remain authorized; source verification, actual saved media and historical coverage still need a proven background access point.
