> Historical engineering evidence. Sanitized for distribution; counts and local instructions below are dated history. Follow README.md and docs/CODEX_DEPLOYMENT.md for this release. This file does not authorize collection. Historical local screenshots/native evidence are excluded; current retained data is in the release dataset.

# Codex Master Prompt — Local Travel Product Research and Recommendation Workbench

## 0. Your assignment and working language

Act as the implementation owner for this project, combining the responsibilities of a product lead, a chief engineer, an application engineer, and a verification engineer. Design the remaining implementation details and build a real, locally runnable product. Do not stop after producing a plan, screenshots, a static prototype, or an upload-only application.

Use English as your working language for technical reasoning, plans, all development conversation with me, questions, progress updates, code identifiers, comments, docstrings, commit messages, developer documentation, and the final engineering report. Keep this language policy even if the existing conversation and project context are predominantly Chinese. Explain decisions with concise English rationales; do not disclose private chain-of-thought.

Use Simplified Chinese for the product itself: navigation, labels, buttons, onboarding, user-facing status and errors, empty states, confirmation messages, product summaries, customer recommendations, comparison images, weekly collections, and the end-user guide. Preserve source material in its original language. Internal enums and structured-data keys may be English. Technical logs may be English, while errors displayed to the operator must be understandable Chinese.

This prompt is the complete project brief. You do not need another product-requirements document to begin. Inspect the actual workspace and host first, use existing useful code where appropriate, and continue through implementation and verification. If team/subagent support is available, delegate independent work with clear file ownership; otherwise perform the roles sequentially. Only one owner may control the live WeChat UI at a time.

## 1. Confirmed product decisions

The product is a desktop-first local web application tentatively named `选团助手`.

Its primary operator is an experienced travel advisor. The main business is helping customers choose suitable supplier tours. A secondary use is assembling reusable weekly product material for other travel advisors.

The end-to-end workflow is:

1. Collect material from explicitly selected WeChat groups, explicitly selected contacts' Moments, and user uploads.
2. Preserve original material and its provenance.
3. Extract and organize travel products, departures, prices, and conditions.
4. Accept a customer's requirements in natural language and editable structured fields.
5. Find a small, justified shortlist, compare alternatives, and identify unanswered questions.
6. Record supplier confirmations where needed.
7. Generate editable Chinese customer recommendations and clear comparison images.
8. Save the customer case and optionally add reviewed content to a weekly collection.

The user has confirmed all of the following:

- Run the web application locally on the same computer as the operator's WeChat desktop client. Mobile use and public hosting are outside the initial scope.
- Online AI API calls are allowed. Provider, endpoint, model, and credentials must be configurable. A locally deployed model has not been selected; keep the provider interface replaceable without requiring a local model now.
- WeChat collection is a first-release requirement, not a later optional integration. Both selected-group collection and selected-contact Moments collection are required.
- The selected material is already customer-facing supplier material. Do not add an internal-information audit, redaction workflow, commission-hiding project, privacy classification queue, or mandatory pre-export disclosure review. Normal factual correction, source tracking, and output preview remain necessary. Normal handling of application credentials remains necessary.
- Customer communication and supplier inquiries are prepared for the operator to copy or export. Automated sending, posting, liking, commenting, purchasing, or booking is not part of this implementation.
- Build useful real-data behavior, not fixed demo results. Clearly label and isolate any demonstration data.

## 2. Product scope and sensible defaults

Adopt these defaults unless the inspected environment provides a concrete reason to change them:

- Single operator and one explicitly selected logged-in WeChat account at a time. Bind source configurations and scan checkpoints to account identity. Never silently reuse another account's checkpoints.
- Business timezone defaults to `Asia/Shanghai`, configurable in settings. Display the active timezone beside date-range controls.
- Manual source selection and manually triggered scans are required. Recurring scheduling may be added after the required workflow works, but is not a substitute for the three required scan modes.
- First-release collection includes text, images, and documents. Preserve a record of other encountered post/message types and available originals or URLs; explicitly mark unsupported analysis types. Do not silently drop them and claim complete coverage. Full video transcription and expansion of arbitrary external websites are not required.
- Prioritize JPEG/PNG/WebP, text, PDF, DOCX, XLSX, CSV, and TXT for analysis. Preserve other attachments with an actionable unsupported-format state. Do not execute macros, scripts, executables, or active document content merely to read a supplier file.
- Treat Moments posts as the collection unit: author, post text, publication-time evidence, image set, and available attachments/link metadata. Likes and other people's social interactions are not a required dataset. If an accessible author correction is associated with a product, preserve that relationship.
- Keep operational notes and advisor judgment, but do not build a separate confidentiality workflow for them. Customer output should contain relevant travel information and recommendations rather than application diagnostics.
- Provide a simple customer-case outcome field if useful. A full booking, payment, commission-accounting, or multi-tenant system is outside the first release.

Keep routine decisions autonomous. Do not request confirmation for every layout choice, dependency, reversible edit, parser improvement, or test. Ask only for a genuinely missing input or material decision, such as which live source to test, a required desktop handoff, provider credentials, a purchase, or a tradeoff that changes a confirmed requirement. Consolidate such questions and continue unaffected work.

## 3. Architecture: simple local application with real desktop collection

The browser is the operator's control panel. Native WeChat collection runs in a local backend/worker with access to the actual interactive desktop session. Do not attempt to make browser JavaScript directly read WeChat desktop data.

If the workspace does not already establish a suitable stack, prefer:

- React and TypeScript for the Chinese desktop web interface.
- A Python backend, with FastAPI as a reasonable default.
- SQLite for business records, persisted jobs, checkpoints, and an initial searchable index.
- A dedicated local file store for original attachments, derived previews, exports, and backups.
- A single serialized WeChat automation worker, plus a bounded independent extraction/AI worker pool.

Select and pin mutually compatible versions after checking the host and current primary documentation. Reuse a good existing project instead of rebuilding for stylistic reasons. A different stack is acceptable if it materially reduces complexity; explain the decision in English. Do not add microservices, Redis, a mandatory vector database, or a container requirement without demonstrated need.

Bind the application to loopback by default. Bundle ordinary frontend assets locally. AI being unavailable must not prevent viewing existing data, manual editing, structured filtering, comparison, or export. Initial package installation may require networking; distinguish this from normal runtime dependencies.

Keep a native UI worker in the desktop session that actually hosts WeChat. WSL, a container, a cloud coding host, or a headless session does not by itself prove access to the user's Windows WeChat UI. If the current execution host cannot access that UI, complete portable modules and the native worker packaging, but clearly mark live collection verification as blocked until run on the real desktop.

Use an explicit application data directory outside ephemeral build output. Record its location in settings. Keep original attachments immutable. Use database migrations and avoid destructive resets of user data. Support one-command start/stop and provide suitable Windows launch scripts if the real target is Windows.

## 4. First engineering milestone: prove the actual WeChat path

Before committing to a collection library or spending most of the effort on presentation, perform a small, read-oriented proof of capability against the actual host and selected logged-in account.

Record:

- OS and architecture, desktop-session availability, Python/runtime environment, and relevant display scaling.
- Exact WeChat/Weixin desktop version and the observable account identity.
- Candidate automation library/version, available methods, maintenance status, and any required license.
- Whether group history, a selected contact's Moments history, timestamps, attachments, and resumption are actually supported.

Prefer Windows UI Automation or an equivalent supported native accessibility/UI route when applicable. An existing library may be used if its required behavior is verified. Avoid hardcoded screen coordinates as the primary mechanism. If a calibrated visual fallback is necessary, tie it to observable window geometry and client state and document the limitation.

Do not silently make encrypted-database key extraction, process injection, authentication bypass, private-protocol emulation, or changing/downgrading the user's WeChat installation a dependency of the project. Use the existing authenticated client and material it can legitimately access. User-exported files can be supported as an additional source, but cannot be counted as proof that the required WeChat scanners work.

An appropriate proof of capability includes:

1. Resolve and reopen one specifically selected group without confusing a same-name group.
2. Read history across multiple loaded pages, preserving sender, text, and time evidence.
3. Save at least one available image and one document from that group and distinguish original, preview, failure, and unavailable content.
4. Open the Moments history of one specifically selected contact, not merely filter a few items from the general feed.
5. Read that contact's posts across pages, identify time information, and retrieve a multi-image post's available media.
6. Exercise a date boundary, duplicate scan, pause/resume, and an interruption.

If a candidate SDK only exposes the general Moments feed, investigate an actual contact/profile UI path or another viable supported adapter. A general-feed filter is at most a clearly labeled partial capability; it is not equivalent to scanning a selected contact's accessible history.

Classify each capability as `PASS`, `PARTIAL`, `BLOCKED`, or `NOT_TESTED`, with observed evidence and a concrete limitation. Documentation and mocks do not count as a live pass. Do not purchase a commercial dependency automatically; first demonstrate that it supplies the missing capability and explain the concrete cost/selection decision if approval is needed. Do not treat an unlicensed method as implemented.

If one collector is blocked, keep working on independent modules. Do not silently remove that collector from scope or declare the complete product finished. State the exact remaining P0 gap and the smallest action needed to validate or implement it.

## 5. Collection sources and operator controls

Implement three source adapters with one normalized output contract:

- `WeChatGroupAdapter`
- `WeChatMomentsAdapter`
- `UploadAdapter`

Each adapter exposes discovered capabilities rather than fabricated capabilities. A minimal contract can include `probe_capabilities`, `resolve_source`, `iterate_items`, `fetch_attachment`, and checkpoint/resume support. Adapt the interface to actual implementation needs without overengineering it.

### 5.1 Source selection

Allow the operator to select one or more groups and one or more contacts' Moments sources under the currently selected logged-in account. Show enough observable identity information to disambiguate same-name entries. If a stable native ID is unavailable, retain a verified local source identity and the evidence needed to reopen and verify it. Do not invent a WeChat ID.

Source discovery metadata is not permission to ingest every conversation. Collection and AI submission are limited to the operator-selected sources, selected ranges, and uploaded files. Revalidate the active account and target before each sequence of UI operations. Pause if the account changes or the worker can no longer verify the target.

The source-selection UI is the normal place to choose live test targets. If no live source has been selected, do not guess a group/contact to make a test pass.

### 5.2 Group content

Within the requested range, enumerate source records, preserving text that gives context to images and files. Do not scan only the latest visible page. Do not treat a function named `GetAllMessage` as proof of whole-history coverage.

Capture the sender, the group identity, the displayed time evidence, quoted/forwarded relationships when available, and attachment associations. A forwarding person, posting person, and actual supplier are separate concepts; do not automatically identify all three as the same supplier.

Where the client exposes merged messages or quoted material, preserve their relationship and process available nested content. If expansion is unsupported, mark the record accordingly. Do not claim to have analyzed an unavailable nested file.

### 5.3 Contact Moments content

Collect the selected contact's accessible posts, their text, publication-time evidence, and ordered media set. Distinguish a profile/album history from the general feed. Keep per-post media counts when observable so missing images can be reported.

Store available originals where possible. If only a preview or screenshot is obtainable, label its quality and origin; never call it an original. Existing privacy restrictions, retention limits, deleted posts, and unavailable content remain observable boundaries, not recoverable content assumptions.

### 5.4 Uploads

Support drag-and-drop, multi-file selection, and pasted text. Allow the operator to add a supplier label and source/date note without requiring a long form. Uploaded files enter the same raw-material, extraction, product, and recommendation pipeline as WeChat material.

If a file's original publication date is unknown, keep it unknown. File creation time and import time are not automatically the product publication date.

## 6. Scan modes, time semantics, and honest coverage

Provide these three required modes:

1. `ALL_ACCESSIBLE`: scan all history currently accessible to the selected account through the supported client/source path.
2. `SINCE`: scan from a user-selected start date/time.
3. `INCREMENTAL`: collect updates since the last saved scan, including an overlap interval and outstanding media retries.

For a date-only start, default to an inclusive boundary at 00:00:00 in the configured business timezone and display this interpretation in Chinese. Allow explicit time adjustment. Filter by source publication/message time, not ingestion time. Freeze an upper boundary at the scan's start time for that run; new material beyond that point belongs to a subsequent incremental run. Display the requested interval.

Preserve `source_time_raw`, normalized time or interval, timezone, precision, and parsing status. Relative dates must be anchored to the observation time. Do not silently guess the year for an ambiguous date or assign one precise timestamp to all messages under a coarse time separator. Keep uncertain-time items visible and avoid discarding them at a boundary that cannot be established reliably.

Handle pinned/out-of-order entries and source-specific ordering. Do not stop at the first older item unless the observed ordering and pagination evidence make that stop valid. An incremental scan needs an overlap/reconciliation policy and durable retry records; a single latest timestamp is insufficient. A bounded overlap does not guarantee detection of edits to arbitrarily old posts: provide a selected-range reconciliation/rescan action, preserve discovered revisions, and do not claim otherwise.

Use separate fields for execution state and coverage outcome. Suggested execution states are `QUEUED`, `RUNNING`, `PAUSING`, `PAUSED`, `NEEDS_USER_ACTION`, `COMPLETED`, `PARTIAL`, `FAILED`, and `CANCELED`. Suggested coverage outcomes include `REQUESTED_BOUNDARY_REACHED`, `ACCESSIBLE_END_REACHED`, `STALLED_UNPROVEN_END`, `PARTIAL_WITH_GAPS`, and `UNKNOWN`.

The product must distinguish:

- The requested date range has been traversed with supported evidence.
- The currently accessible source endpoint has been reached.
- Traversal stopped without proving an endpoint.
- Records were discovered but some media were not retrieved or analyzed.

Report requested scope, observed earliest/latest time or interval, discovered records, saved attachments, previews/originals, failures, skipped unsupported types, unresolved dates, retry items, last checkpoint, and stop reason. Keep discovery, download, and extraction progress separate. When total size is unknown, show real counts rather than an invented progress percentage.

No new records after scrolling, a timeout, a repeated viewport, a configured quantity cap, or reaching the end of a currently loaded page is not by itself proof that all requested history was read. Use bounded retries and source-specific evidence; otherwise report a partial/unproven result. A resource cap may pause work but cannot silently redefine `ALL_ACCESSIBLE`.

Never claim all historical content ever posted on the account has been recovered. The acceptance target is exhaustive traversal of the supported, currently accessible selected-source range, with retrieval/analysis gaps separately visible.

## 7. Durable jobs, deduplication, and UI-worker behavior

Persist scan jobs and per-source checkpoints transactionally. Persist discovered source items before advancing a resumable checkpoint. Commit attachment success only after bytes have been saved and validated; retain partial downloads as incomplete retryable work. AI failure must not roll back acquisition or require rescraping completed material.

Keep separate durable state for:

- Source discovery progress and known coverage.
- Attachment retrieval attempts, missing originals, and retry scheduling.
- Extraction attempts and versions.
- Product organization and unresolved fields.

Cancel or pause at safe boundaries, release the WeChat-control lock, and retain already acquired material. After a restart, classify interrupted jobs as resumable rather than finished. Never terminate the user's WeChat application to cancel a job.

Only one worker may manipulate the WeChat UI at a time, including switching chats, scrolling, opening a contact, navigating Moments, or UI-dependent downloads. AI parsing and purely local file work may run with bounded parallelism. Display `正在采集微信` together with the current source and clear pause/resume/cancel controls. If user interaction disrupts verified targeting or the desktop becomes unavailable, pause with a specific Chinese explanation instead of blindly continuing or repeatedly stealing focus.

Store identical file bytes once when appropriate, but retain every source occurrence and provenance link. Blob deduplication, source-event deduplication, and product merging are different operations.

Use stable native event IDs only when their semantics are actually verified. Some UI identifiers change after navigation and some library hashes may collide. Where stable IDs do not exist, use a source/account-scoped fingerprint plus observed time precision, author, text, attachment identity, and sequence/overlap context. Preserve repeated legitimate posts. If two occurrences cannot safely be disambiguated, retain the uncertainty instead of deleting one solely to make a deduplication test pass.

Do not merge different suppliers' products solely because the titles or poster images match. Provide explainable duplicate/merge suggestions and preserve original observations. An omitted item in a later scan is not proof it was deleted.

## 8. Data model and evidence

Design the schema around these responsibilities; combine tables only where it simplifies implementation without losing semantics:

| Entity | Required responsibility |
| --- | --- |
| `AccountBinding` | Observable account identity, local binding, and adapter/environment compatibility information. |
| `Source` | Selected group/contact/upload source, identity evidence, type, display name, and last known capabilities. |
| `ScanJob` / `SourceCheckpoint` | Requested time scope, mode, state, coverage evidence, checkpoints, and resumable work. |
| `SourceItem` | Immutable original text/time evidence, author/forwarder, source locator, observation time, and changes. |
| `Attachment` / occurrence links | Stored bytes/hash, original name/type, source association, quality, retrieval state, and local path. |
| `ExtractionVersion` | Parser/model/schema/prompt versions, structured findings, evidence references, and review issues. |
| `Supplier` | Supplier identity and observed contact/product associations without equating a group name with a supplier. |
| `Product` / `ProductVersion` | Itinerary and product identity with preserved revisions and source relationships. |
| `Offer` | Price tied to departure date or validity interval, package, traveler category, occupancy, currency, inclusions, and supplier. |
| `VerificationRecord` | Field-level supplier confirmation, applicability, evidence, and confirmation time. |
| `CustomerCase` | Requirements, hard constraints, preferences, selected alternatives, notes, and optional outcome. |
| `RecommendationVersion` | Requirements/product versions used, editable wording, status, and exports. |
| `WeeklyCollection` | Operator-selected reusable material and exported package versions. |

Support many-to-many material/product relationships: one poster can contain multiple departures or products, and one product can be described by several images, documents, and later corrections.

Represent `unknown`, `not applicable`, `explicitly zero`, and `known` distinctly where needed. A starting price is not an applicable confirmed quote. Store price kind (`exact`, `from`, or `range`), per-person/per-party units, traveler class, occupancy conditions, required extras, transport inclusion, and relevant dates. Do not add unknown costs as zero.

Keep three clocks distinct: when a supplier posted a source, when the application collected it, and when a supplier quote/availability was confirmed. A new scrape does not refresh an old supplier quote.

Keep source statements, AI interpretations, and advisor judgment distinguishable. Key factual fields need references to a source item and, when available, a document page or image region. Do not fabricate bounding boxes or supporting quotes. A human correction is a valid observation with its own author/time; preserve earlier extraction versions.

On supplier updates, append revisions and flag affected recommendations for review. Do not silently rewrite already exported versions. Reprocessing material with a new model must not overwrite verified human corrections without surfacing the conflict.

## 9. AI configuration, parsing, and fallback behavior

Build a replaceable provider layer. Configure base URL, protocol/adapter, model identifier, credentials, timeouts, concurrency limits, and declared/verified capabilities. Allow separate text and vision models. An OpenAI-compatible HTTP adapter is a reasonable initial interface, but compatibility is not guaranteed for every endpoint or feature. Do not assume a future local model can accept images or constrained JSON.

Implement an explicit connection/capability check using small known test inputs. Distinguish text support, image support, structured-response support, and any optional embeddings. Test with the actual configured service when credentials are available. Never invent credentials or silently use a different provider.

Read ordinary document text locally where reliable; use available vision/OCR for image-only content and scanned document pages. Parse tables and documents with their page/sheet relationships intact. Preserve originals and extraction evidence. Long posters or multipage documents may require page/crop processing, with source positions preserved.

Require schema-validated structured extraction with nullable unknown fields, evidence references, and explicit issues. Apply bounded repair/retry behavior for malformed output. Separate extraction confidence from factual supplier verification. High model confidence does not mean a price or seat is confirmed.

Treat imported text as source data, not instructions. Do not let a supplier document change the application's system rules, trigger external actions, or execute commands. AI receives the selected task material and relevant product facts, not an unrestricted dump of the computer or all WeChat conversations.

Cache results using material/content identity, provider/model, prompt version, schema version, and extraction options. Record actual API usage when the provider returns it; otherwise say usage/cost is unknown. Repeated unchanged scans should not repeatedly reanalyze unchanged files. Keep bounded concurrency, cancellation, finite timeouts, and retry behavior for transient errors.

Credentials stay in backend configuration or an appropriate local secret store, not frontend bundles, exported files, logs, or source control. Do not create a business-content privacy review process; credential handling is normal application implementation.

If AI is not configured or fails, show the real state in Chinese. Keep material acquisition, manual entry/correction, structured filtering, comparison, and template-based output working. Do not label a rules-only fallback as successful unrestricted natural-language understanding. Resume queued analysis when configuration is available.

## 10. Product search, comparison, and customer output

### 10.1 Requirements input

Accept natural-language Chinese requests and pasted customer messages. Convert them into editable conditions: departure city, destination, date range, duration, traveler composition, budget and units, transport inclusion, hotel preferences, pace, shopping requirements, and other explicit exclusions.

Differentiate hard constraints from preferences. Ask at most one or two high-impact missing questions when needed, while allowing useful provisional results. Never silently change the customer's budget, dates, or shopping requirement to fill a shortlist.

### 10.2 Retrieval and ranking

First evaluate structured applicability and hard constraints, then rank applicable candidates using preferences, source quality/freshness, and advisor notes. Keyword/full-text search is a reasonable starting point; add semantic retrieval only where it demonstrably improves the actual queries.

Show two or three useful candidates with an option to inspect more. Unknown hard-constraint fields belong in a clearly labeled needs-verification group and must not count as satisfied. Explicitly incompatible products are excluded or shown only in a deliberately requested alternatives view. Explain no-match results and offer a concrete next step without silently relaxing constraints.

For each candidate show the applicable offer/date, included and additional costs, why it fits, the key tradeoff, the most important uncertainty, and a source link. Avoid unexplained confidence scores that imply mathematical certainty.

### 10.3 Comparison and supplier inquiries

Support side-by-side desktop comparison, with differences and unresolved fields emphasized. Include dates, price basis, hotel changes, transit, shopping, inclusions/exclusions, source update time, and separate quote/availability confirmation information.

Generate supplier-specific Chinese question drafts that the operator can copy. Allow pasted replies or manual confirmation entries; record exactly what was confirmed, for which date/party/offer, by whom, and when. Reading a new source or checking one box must not mark every field confirmed.

### 10.4 Customer preview and export

Generate editable Chinese introductory text and a concise, legible comparison image. Preserve date, price applicability, significant additional costs/unknowns, the advisor's recommendation, and the information date. Long itineraries can be exported through an additional readable document/print view if useful.

Offer `复制介绍`, `生成对比图`, `保存图片`, and appropriate local file export actions. Do not advertise an external share URL that cannot be opened outside localhost. Do not label content `已发送` merely because it was copied or downloaded; an operator may record sending manually.

Support preliminary recommendations that clearly disclose unresolved factual conditions. Do not force every item through a separate review/approval screen or invent an internal-information exclusion audit. The user has expressly removed that requirement. A normal editable output preview is sufficient.

Persist the exact recommendation/export version and its linked requirements, product, and offer versions. For every prepared/exported version, retain immutable snapshots of the effective customer requirements, applicable offer and price conditions, relevant product facts, and the exact generated text/image. References to mutable current records alone are insufficient. If those inputs change, flag the draft for review and preserve already prepared/exported versions.

### 10.5 Weekly reuse

Allow selected reviewed products/recommendations to be added to `本周资料`. Generate a Chinese summary with product facts, suitable audiences, meaningful tradeoffs, unresolved items, sources, and update dates. Avoid requiring a second full analysis of unchanged content. No subscriber portal or automated distribution is required.

## 11. Chinese desktop UX

Use five main navigation areas:

1. `素材中心`: selected sources, scan creation, active jobs, coverage reports, uploads, acquired material, extraction issues, and product organization.
2. `选团工作台`: requirements, shortlist, comparison, supplier questions, and customer preview.
3. `接待记录`: saved cases, prior recommendations, changes, and optional outcomes.
4. `本周资料`: reusable selections and package export.
5. `设置`: WeChat/adapter capability status, active account, AI settings, data directory, timezone, backup/restore, and basic runtime diagnostics.

Keep selection and details close together. A material detail view should show the original beside editable structured fields. Show actionable empty/error states instead of a blank page or generic stack trace. Preserve the current source, filters, selected products, and draft edits while the operator switches to WeChat and back.

Separate source collection progress from analysis progress. Use honest counts and human-readable Chinese states. Important actions must have visible labels. Optimize the desktop layout for real source review and product comparison rather than decorative dashboards or large empty hero panels.

Implement the main workflow with real backend data from the outset. A fake `扫描成功` toast, fabricated progress bar, fixed product array, or mock API response must never appear as a live feature. Tests may use fixtures; an explicit demo mode must be unmistakable and separate from the real dataset.

## 12. Backup, recovery, and application delivery

Back up an application-consistent database snapshot plus every referenced original and required asset, with a manifest, schema version, and hashes. Do not simply copy a changing database and assume it is consistent. Either quiesce relevant writes or use an appropriate snapshot plus consistent attachment-manifest strategy. Exclude live secrets from ordinary shareable backups by default and explain how to reconfigure them.

Restore into a separate directory for verification before replacing the active dataset. Keep a pre-restore backup when replacing existing data. Validate that restored products, attachments, sources, cases, checkpoints, and exports still work. Starting after an interrupted job must not duplicate entire datasets or mark missing media as complete.

Provide a practical setup/start workflow for the actual target. Report occupied ports and missing dependencies clearly. If WeChat collection needs an unlocked interactive desktop or a visible client, show that operational requirement where the operator starts a scan. Do not claim a native UI collector runs headlessly unless actually verified.

## 13. Implementation sequence and autonomy

Use these milestones; do not turn every milestone into a mandatory user-approval pause.

### Milestone A — Environment and acquisition feasibility

Inspect the repository/host, establish the local run path, create a short implementation plan, and perform the live collector proof described above. Produce a compact capability matrix and choose adapters based on evidence. Scaffold portable UI/storage work in parallel where useful, but prioritize resolving the selected-contact Moments path early.

### Milestone B — Persistent acquisition pipeline

Implement account/source selection, the three adapters, persistent raw records and files, date modes, source verification, serialized UI work, visible jobs, resumable discovery/downloads, and honest coverage reporting. Demonstrate a real collected/uploaded item can be reopened after restarting.

### Milestone C — Extraction and product library

Implement provider settings/capability checks, document/image analysis, schema validation, product/offer versioning, source-linked correction, supplier resolution, and reprocessing behavior. Verify a multi-product poster and multiple-source product case.

### Milestone D — Advisor workflow

Implement natural-language/structured requirements, matching, comparison, supplier questions/confirmations, editable Chinese recommendations, text/image exports, and saved case versions. Use actual acquired material where available.

### Milestone E — Reliability and delivery

Finish incremental reconciliation, media retries, interruption recovery, weekly reuse, backup/restore, startup instructions, and meaningful end-to-end verification. Fix concrete failures. Stop optional test expansion once the stated acceptance risks are resolved.

Continue routine work autonomously. When a live environment, selected target, AI credential, or dependency purchase is genuinely missing, describe the precise blocker and minimum action needed; continue independent implementation. Never convert a blocked requirement into a claimed pass. Do not modify unrelated projects or the user's WeChat installation to bypass an environmental gap.

## 14. Acceptance matrix

Create an evidence-backed acceptance report. Use explicit `PASS`, `PARTIAL`, `BLOCKED`, and `NOT_TESTED` statuses. For each pass, record the build/environment, sample, action, observed result, and evidence location without exposing API secrets.

| ID | Required acceptance scenario |
| --- | --- |
| A01 | The app starts locally using the documented procedure; Chinese UI and core stored-data operations work without a configured AI endpoint. |
| A02 | The chosen logged-in account and selected source are correctly resolved; a same-name source and account change do not silently redirect collection. |
| A03 | A real selected group is scanned across multiple history pages, with original text/time evidence and available images/documents saved. |
| A04 | A real selected contact's Moments history is traversed across pages; a multi-image post and time evidence are preserved. A general-feed demo alone fails this criterion. |
| A05 | Uploaded images/documents/text pass through the same persistent extraction/product pipeline. |
| A06 | Inclusive date-only starts, exact datetime boundaries, cross-year/relative/uncertain dates, and the run cutoff behave as specified. |
| A07 | `ALL_ACCESSIBLE`, `SINCE`, and `INCREMENTAL` report actual coverage; a timeout, quantity cap, repeated viewport, or missing attachment does not become a false full-completion claim. |
| A08 | Repeated scans reuse identical blobs and do not duplicate the same source event, while legitimate repeated posts and cross-source occurrences remain distinguishable. |
| A09 | Pause, cancel, process interruption, restart, and resume preserve acquired items, release UI ownership, and retain unfinished work. |
| A10 | A discovered item with a failed/late attachment can retrieve that attachment later even after the discovery watermark advances. |
| A11 | User interference, lost desktop/client availability, or target mismatch produces a recoverable state rather than scanning the wrong source. |
| A12 | Actual configured AI calls are verified when credentials exist; unsupported vision, invalid JSON, timeout, and rate-limit behavior are explicit and recoverable. |
| A13 | One poster with multiple products and multiple documents for one product preserve correct evidence and do not silently merge unrelated suppliers. |
| A14 | Different departures/traveler categories, starting prices, missing costs, and transport inclusions are not conflated into one unconditional price. |
| A15 | Source facts, human corrections, supplier confirmations, and advisor judgments remain distinguishable; reprocessing preserves human corrections. |
| A16 | Hard constraints are respected; unknown shopping/price applicability is not counted as satisfied; no-match behavior offers a truthful next action. |
| A17 | Changed customer requirements or product/offer versions flag affected recommendations while preserving previous versions. |
| A18 | Customer text and images are Chinese, editable/legible, match the preview, and accurately retain applicable dates, prices, and unresolved conditions. No separate internal-information audit is introduced. |
| A19 | Copy/export does not automatically send a message, publish content, or mark it as sent; the prepared version is saved. |
| A20 | Restarting preserves materials, files, product records, cases, job state, and exports; a backup is successfully restored into a separate test directory. |
| A21 | A weekly collection reuses selected content and exports readable Chinese material with provenance and dates. |
| A22 | A real end-to-end demonstration goes from selected-source acquisition to product search, comparison, and customer output, with any untested or blocked stages explicitly identified. |

Use focused automated tests for business rules, checkpointing, schema validation, and recovery. Use integration/live tests for the actual WeChat and AI boundaries. A fixture proves only the behavior it exercises, not live-client compatibility. Keep fixtures explicitly labeled.

Where supplied, use approximately ten real historical customer requirements as a small usefulness evaluation. Measure shortlist latency, missed known candidates, hard-constraint errors, and operator effort. A first useful shortlist within roughly one minute on an already organized pilot library is a target, not a result to invent. State dataset size and host/provider conditions for measurements. If no real benchmark is available, report that fact and provide a reproducible test path.

## 15. Required deliverables and final response

Deliver:

- Working application source and appropriate dependency lockfiles/configuration.
- Local start/stop scripts and a documented data directory.
- A concise English `README.md` with environment/setup/developer instructions.
- A Chinese `USER_GUIDE.zh-CN.md` covering source selection, scanning, partial coverage, AI setup, selecting tours, export, and backup/restore.
- A compact English capability/compatibility report for the actual WeChat host and chosen adapter.
- An English acceptance report covering the matrix above and exact remaining P0 gaps.
- Meaningful tests/fixtures and reproducible verification commands.
- Example exports only when clearly marked as samples or based on selected actual test material.

Do not produce multiple repetitive planning/audit documents instead of implementation. Keep the live capability evidence, implementation decisions, and acceptance report concise and useful. The prompt already resolves product direction; do not reopen settled questions without a concrete conflict.

Your final engineering response must be in English and state: what works, how to start it, what was actually tested, which collector/AI capabilities remain limited or blocked, where data and deliverables are located, and the smallest next action if any. Never say the entire project is complete if a required group or selected-contact Moments collector remains unverified or unimplemented.

## 16. Research starting points — verify before using

The following primary project-author documentation was inspected while preparing this brief on 2026-10-25. These are research leads, not guarantees about the target machine or a purchase recommendation. Recheck live documentation, maintenance, exact client compatibility, and required licensing before selecting a dependency.

- Installation and environment: https://docs.wxauto.org/docs/install.html
- WeChat methods, including history traversal: https://docs.wxauto.org/docs/class/WeChat.html
- Message identifiers and media/file methods: https://docs.wxauto.org/docs/class/Message.html
- Moments methods: https://docs.wxauto.org/docs/class/Moment.html
- Original repository status to verify rather than blindly depend on: https://github.com/cluic/wxauto4

At preparation time, these documents described a Windows UI Automation route, version/edition dependencies, historical-message traversal, attachment methods, and Moments pagination. They did not establish that the user's exact environment supports full selected-contact history, reliable publication-time extraction, and original-media retrieval together. Prove those requirements on the host. Personal WeChat and enterprise WeCom integrations are different capabilities; do not substitute an enterprise API without verifying it actually serves the selected personal-account requirement.

Begin now with a short English acknowledgment of the confirmed scope and language policy, inspect the actual environment, establish the live acquisition capability plan, and proceed into implementation.
