# Travel Advisor Workbench / 选团助手

A local Windows workbench for source-linked travel materials, product editing, customer matching, offer comparison, Chinese recommendations, and weekly collections.

This release preserves the current relevance filtering, initial-history and incremental-processing implementations and corrected dataset. Imported data is labeled **导入资料**. Live collection and scheduling are disabled by default. Online AI configuration remains optional and deferred.

## 快速开始（Windows）

安装 Python 3.12 x64、Node.js 24 x64、Git，并确保当前账号能访问私有仓库。首次安装需要网络。

```powershell
git clone https://github.com/adrain-luo/travel-advisor-workbench.git
cd travel-advisor-workbench
git checkout v2026.10.30.1
npm install --global pnpm@11.25.0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
.\.venv\Scripts\python.exe .\scripts\fetch_release.py --repo adrain-luo/travel-advisor-workbench --tag v2026.10.30.1 --output .\downloads
.\.venv\Scripts\python.exe .\scripts\portable_data.py verify --package .\downloads\travel-advisor-data-v2026.10.30.1.zip
.\.venv\Scripts\python.exe .\scripts\portable_data.py import --package .\downloads\travel-advisor-data-v2026.10.30.1.zip --data-dir "$env:LOCALAPPDATA\TravelAdvisorWorkbench\data"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -DataDir "$env:LOCALAPPDATA\TravelAdvisorWorkbench\data" -Port 8767
```

打开 `http://127.0.0.1:8767/`。停止：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop.ps1 -Port 8767`。

- [中文安装与使用手册](docs/DEPLOYMENT.zh-CN.md)
- [Independent Codex deployment handoff](docs/CODEX_DEPLOYMENT.md)
- [Dataset contents and exclusions](docs/DATA_PACKAGE.md)
- [Release validation](docs/RELEASE_VALIDATION.md)

## Layout and delivery

| Path | Contents |
| --- | --- |
| backend/ | FastAPI, SQLite store/schema, native adapters, relevance pipeline, extraction/matching and Chinese export |
| frontend/ | Chinese React/TypeScript/Vite interface and frozen pnpm lockfile |
| scripts/ | Install/start/stop, release fetch, selected-field export, verified import/backup/restore and smoke checks |
| tests/ | Synthetic business, storage, source, incremental, relevance and release-safety regression tests |
| docs/ | Current deployment/data/validation documents and marked historical reports |
| requirements*.lock.txt | Exact Python and local OCR dependency versions |
| config/ | Placeholder-only optional local binding template |
| source-inclusion.json | Explicit source inclusion inventory; no original Git history |

Actual sanitized records/media are versioned assets in the same private release: data ZIP, complete handoff ZIP, dataset/build manifests and SHA256SUMS.txt. No Git LFS is required. Setup downloads dependencies; this is not an offline installer.

Windows 11 x64 was tested. Other systems and live collection on another host are unverified. See [third-party notices](THIRD_PARTY_NOTICES.md); supplier material is not assigned a blanket open-source license.
