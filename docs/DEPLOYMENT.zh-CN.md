# 选团助手：Windows 安装与使用

发布包支持浏览导入资料、图片、来源和产品，编辑产品，匹配与比较客户需求，生成中文推荐和周汇总。无需微信、原账号、数据库/图片密钥或在线 AI。导入资料不表示在当前电脑采集。

## 环境与访问

- Windows 11 64 位；其他系统未验证。
- Python 3.12 x64、Node.js 24 x64、Git for Windows。
- 运行 `npm install --global pnpm@11.25.0`。
- Windows 中文字体，例如微软雅黑。
- 当前 GitHub 账号须有私有仓库访问权限。通过 Git Credential Manager 登录，或运行 `gh auth login` 与 `gh auth setup-git`。不要把令牌放入聊天或仓库。

首次安装从 Python 包索引和 npm 下载依赖。OCR 模型随固定版本 RapidOCR 安装，运行时不自动下载。此包不是离线安装器。

## 下载、安装、导入

```powershell
git clone https://github.com/adrain-luo/travel-advisor-workbench.git
cd travel-advisor-workbench
git checkout v2026.10.30.1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
.\.venv\Scripts\python.exe .\scripts\fetch_release.py --repo adrain-luo/travel-advisor-workbench --tag v2026.10.30.1 --output .\downloads
.\.venv\Scripts\python.exe .\scripts\portable_data.py verify --package .\downloads\travel-advisor-data-v2026.10.30.1.zip
.\.venv\Scripts\python.exe .\scripts\portable_data.py import --package .\downloads\travel-advisor-data-v2026.10.30.1.zip --data-dir "$env:LOCALAPPDATA\TravelAdvisorWorkbench\data"
```

Python/pnpm 不在 PATH 时，安装命令可加 `-PythonPath 'C:\Tools\Python312\python.exe' -PnpmPath 'C:\Tools\pnpm.cmd'`，替换为实际安装路径。

也可下载完整交接 ZIP，解压进入 source 目录，使用同包数据 ZIP；仍需安装依赖。下载工具检查仓库私有状态、资源长度、GitHub 哈希（如有）和 SHA256SUMS.txt。导入工具核对数据结构、逐文件哈希及来源关联。

导入目标必须是新目录。重复导入同一包不会覆盖已有修改；已有其他数据或不同包会被拒绝。升级/恢复请用新目录，核对后切换。

## 启动、检查、停止

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -DataDir "$env:LOCALAPPDATA\TravelAdvisorWorkbench\data" -Port 8767
.\.venv\Scripts\python.exe .\scripts\smoke.py --url http://127.0.0.1:8767 --data-dir "$env:LOCALAPPDATA\TravelAdvisorWorkbench\data"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop.ps1 -DataDir "$env:LOCALAPPDATA\TravelAdvisorWorkbench\data" -Port 8767
```

打开 `http://127.0.0.1:8767/`。可换用空闲端口，加 `-NoBrowser` 只启动服务。每端口独立记录进程；停止命令只处理匹配的应用实例。不要批量结束 Python 或微信进程。

`-DataDir` 优先于 `TRAVEL_DATA_DIR`，默认是 `%LOCALAPPDATA%\TravelAdvisorWorkbench\data`。

## 使用资料

“产品资料”中可查看来源标签、原始发布时间、采集时间、分类依据与图片。相同图片可以属于不同来源事件。历史报价不代表当前可订，未知年份、币种或价格单位仍待确认。

“待识别”与正常资料分开。未取得附件、隐私排除项与已保存文件分别标明。账号头像、遍布账号水印的上下文截图和个人内容可能被排除；真实产品图片及可保留的来源证据仍在包内。具体见 DATA_PACKAGE.md 与数据清单。

可编辑产品、查修改版本、录入需求、匹配、比较、生成中文推荐与周汇总。导出不会自动发给客户，AI 可保持空配置。

## 备份、恢复、回退

在应用运行时执行一致备份：

```powershell
.\.venv\Scripts\python.exe .\scripts\portable_data.py backup --url http://127.0.0.1:8767 --output .\backup-imported.zip
.\.venv\Scripts\python.exe .\scripts\portable_data.py restore --archive .\backup-imported.zip --data-dir "$env:LOCALAPPDATA\TravelAdvisorWorkbench\restored"
```

恢复到新目录，不覆盖现有数据。用新的 DataDir 启动并验证后再切换。回退时停止新实例，用原目录启动。备份含业务数据，应保持私有。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| GitHub 404/认证失败 | 确认账号有访问权限，通过 GCM 重新登录 |
| Python 缺失/版本不符 | 安装 3.12 x64 或指定 -PythonPath；不要使用空的 Store 别名 |
| pnpm 版本不符 | 重新安装 pnpm@11.25.0，打开新终端 |
| OCR 模型校验失败 | 重装 requirements-ocr.lock.txt，运行 scripts/verify_resources.py |
| 中文字体缺失 | 安装 Windows 中文语言/字体组件，或用 TRAVEL_CJK_FONT 指定有许可的中文字体 |
| 端口占用 | 换端口，不停止未知进程 |
| 导入拒绝目标 | 选择新目录，不会自动合并/覆盖 |
| 哈希或结构校验失败 | 重新下载同一版本，不跳过校验 |
| 图片未取得/已排除 | 阅读清单原因；原电脑缓存不是交付依赖 |
| 启动失败 | 查看 .local/instances/端口/server-error.log |

## 可选实时后台采集

导入部署验证与新主机微信兼容性验证是两项独立工作。默认后台调度不启动。用户另行明确授权具体账号/来源后，才可填写本机绑定、核对当前账号/进程/来源并做受限验证。不得复用导入账号、旧游标、密钥或验证状态。详见英文交接手册和配置模板。前台点击、截图导航、自动发送继续禁用；AI 配置仍独立可选。
