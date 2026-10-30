import { useCallback, useEffect, useState } from "react";
import {
  api,
  dateLabel,
  display,
  emptyState,
  label,
  price,
  fieldLabels,
  humanValue,
  setDateTimezone,
} from "./api";
import type { AppState, RecordData } from "./api";
import { Badge, Empty, Field, Icon, Modal, SectionHead, useSaved } from "./ui";
import { Workbench, ProductEditor } from "./Workbench";
import { Settings } from "./Settings";
import { NativeCollection, PageObservations } from "./NativeCollection";
import { BackgroundSync, PendingCandidates } from "./BackgroundSync";
import { ClassificationEditor, classificationLabel } from "./Classification";

export type Action = (
  task: () => Promise<unknown>,
  message?: string,
) => Promise<any>;
const tabs = [
  {
    id: "materials",
    name: "素材中心",
    icon: "library",
    description: "汇集供应商资料，让每个推荐都有依据",
  },
  {
    id: "workbench",
    name: "选团工作台",
    icon: "compass",
    description: "从客户需求出发，找到有依据的旅行方案",
  },
  {
    id: "cases",
    name: "接待记录",
    icon: "cases",
    description: "留存每一次需求、比较与推荐",
  },
  {
    id: "weekly",
    name: "本周资料",
    icon: "weekly",
    description: "把值得推荐的产品，整理成下一次的灵感",
  },
  {
    id: "settings",
    name: "设置",
    icon: "settings",
    description: "管理本地数据、微信连接与 AI 服务",
  },
];

export default function App() {
  const [tab, setTab] = useSaved("active-tab", "materials");
  const [state, setState] = useState<AppState>(emptyState);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(0);
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(
    null,
  );
  const [product, setProduct] = useState<RecordData | null>(null);
  const refresh = useCallback(async () => {
    try {
      const next = await api("/api/state");
      setDateTimezone(next.settings?.timezone || "Asia/Shanghai");
      setState({
        ...emptyState,
        ...next,
        settings: { ...emptyState.settings, ...next.settings },
      });
      setConnected(true);
    } catch (e) {
      setConnected(false);
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    refresh().catch((e) => setNotice({ text: e.message, error: true }));
    const id = setInterval(() => {
      refresh().catch(() => {});
    }, 7000);
    return () => clearInterval(id);
  }, [refresh]);
  useEffect(() => {
    if (notice && !notice.error) {
      const id = setTimeout(() => setNotice(null), 5000);
      return () => clearTimeout(id);
    }
  }, [notice]);
  const action: Action = async (task, message) => {
    setBusy((x) => x + 1);
    try {
      const result = await task();
      await refresh();
      if (message) setNotice({ text: message, error: false });
      return result;
    } catch (e) {
      setNotice({
        text: e instanceof Error ? e.message : "操作未完成，请重试。",
        error: true,
      });
      return null;
    } finally {
      setBusy((x) => x - 1);
    }
  };
  const active = tabs.find((t) => t.id === tab) || tabs[0];
  const liveJob = state.jobs.find((j) => j.state === "RUNNING");
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Icon name="compass" size={29} />
          </div>
          <div>
            <strong>选团助手</strong>
            <small>旅行顾问的资料工作台</small>
          </div>
        </div>
        <div className="workspace-label">我的工作空间</div>
        <nav>
          {tabs.map((t) => (
            <button
              key={t.id}
              aria-label={t.name}
              className={tab === t.id ? "nav-item active" : "nav-item"}
              onClick={() => setTab(t.id)}
            >
              <Icon name={t.icon} />
              <span>{t.name}</span>
              {t.id === "materials" && state.materials.length > 0 && (
                <b>{state.materials.length}</b>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card">
            <span className={`dot ${connected ? "online" : ""}`} />
            <div>
              <strong>{connected ? "本地工作台已连接" : "等待本地服务"}</strong>
              <small>资料保存在这台电脑</small>
            </div>
          </div>
          <div className="sidebar-foot">
            <span>为每一程，选得更好</span>
            <span>本地版 0.1</span>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            我的工作空间 <Icon name="chevron" size={13} />{" "}
            <span>{active.name}</span>
          </div>
          <div className="topbar-right">
            <span className="timezone">
              <Icon name="clock" size={14} />
              {state.settings.timezone || "Asia/Shanghai"}
            </span>
            <button
              className="icon-button"
              onClick={() => action(refresh, "数据已刷新")}
              aria-label="刷新数据"
            >
              <Icon name="refresh" />
            </button>
            <span className="avatar">顾</span>
          </div>
        </header>
        <main>
          {state.settings.imported_dataset && (
            <p className="notice" role="status">当前为导入资料库：来源与采集时间来自导出记录，不代表本机微信采集。实时采集默认停用。</p>
          )}
          {state.settings.fixture_mode && (
            <div className="fixture-banner" role="alert">
              <Icon name="alert" size={22} />
              <strong>测试夹具环境 · 非真实供应商资料，不能用于客户推荐</strong>
            </div>
          )}
          <div className="page-heading">
            <div>
              <div className="eyebrow">旅行产品研究与推荐</div>
              <h1>{active.name}</h1>
              <p>{active.description}</p>
            </div>
            <div className="heading-aside">
              <span className="subtle-pill">
                <span className={`dot ${connected ? "online" : ""}`} />
                {connected ? "本地数据" : "服务未连接"}
              </span>
            </div>
          </div>
          {liveJob && (
            <div className="live-banner">
              <Icon name="refresh" />
              <strong>正在采集微信</strong>
              <span>
                {state.sources.find((s) => s.id === liveJob.source_id)
                  ?.display_name || "已选择的来源"}
              </span>
              <button
                onClick={() =>
                  action(() => api(`/api/jobs/${liveJob.id}/pause`, "POST"))
                }
              >
                暂停采集
              </button>
            </div>
          )}
          {notice && (
            <div
              className={`notice ${notice.error ? "error" : ""}`}
              role={notice.error ? "alert" : "status"}
            >
              <Icon name={notice.error ? "alert" : "check"} />
              <span>{notice.text}</span>
              <button
                className="icon-button"
                aria-label="关闭提示"
                onClick={() => setNotice(null)}
              >
                <Icon name="close" size={16} />
              </button>
            </div>
          )}
          {loading ? (
            <div className="loading">正在连接本地资料库…</div>
          ) : (
            <>
              {tab === "materials" && (
                <Materials
                  state={state}
                  action={action}
                  onProduct={setProduct}
                />
              )}{" "}
              {tab === "workbench" && (
                <Workbench
                  state={state}
                  action={action}
                  onProduct={setProduct}
                />
              )}{" "}
              {tab === "cases" && <Cases state={state} action={action} />}{" "}
              {tab === "weekly" && <Weekly state={state} action={action} />}{" "}
              {tab === "settings" && <Settings state={state} action={action} />}
            </>
          )}
        </main>
        <footer className="main-footer">
          <span>原始资料可追溯 · 待确认信息保留原状</span>
          <span>
            {busy > 0 ? "正在处理，请稍候…" : "选团助手 · 本地工作空间"}
          </span>
        </footer>
      </div>
      {product && (
        <ProductEditor
          product={product}
          materials={state.materials}
          action={action}
          onClose={() => setProduct(null)}
        />
      )}
    </div>
  );
}

function Materials({
  state,
  action,
  onProduct,
}: {
  state: AppState;
  action: Action;
  onProduct: (p: RecordData) => void;
}) {
  const [view, setView] = useSaved("material-view", "materials");
  const [query, setQuery] = useSaved("material-query", "");
  const [sourceFilter, setSourceFilter] = useSaved(
    "material-source-filter",
    "",
  );
  const [upload, setUpload] = useState(false);
  const [sourceModal, setSourceModal] = useState(false);
  const [selected, setSelected] = useSaved<string[]>("selected-sources", []);
  const [material, setMaterial] = useState<RecordData | null>(null);
  const counts = [
    {
      title: "产品资料",
      n: state.materials.length,
      icon: "file",
      hint: "已保留资料与手动导入",
    },
    {
      title: "已整理产品",
      n: state.products.length,
      icon: "compass",
      hint: "保留来源与报价条件",
    },
    {
      title: "微信采集来源",
      n: state.sources.filter((s) => s.kind !== "upload").length,
      icon: "chat",
      hint: "仅采集明确选择的来源",
    },
  ];
  const materials = state.materials.filter(
    (m) =>
      (!sourceFilter || m.source_id === sourceFilter) &&
      (!query ||
        `${m.text || ""} ${m.title || ""} ${m.supplier || ""} ${m.filename || ""} ${m.source_note || ""}`
          .toLowerCase()
          .includes(query.toLowerCase())),
  );
  const selectedSources = state.sources.filter(
    (s) => selected.includes(s.id) && s.kind !== "upload",
  );
  return (
    <>
      <div className="metric-grid">
        {counts.map((c) => (
          <div className="metric-card" key={c.title}>
            <span className="metric-icon">
              <Icon name={c.icon} size={21} />
            </span>
            <div>
              <span>{c.title}</span>
              <strong>
                {c.n}
                <small> 项</small>
              </strong>
              <p>{c.hint}</p>
            </div>
          </div>
        ))}
      </div>
      <div className="section-head library-head">
        <div className="tab-row">
          {[
            ["materials", "产品资料"],
            ["pending", "待识别"],
            ["background", "后台同步"],
            ["sources", "来源记录"],
            ["jobs", "旧采集任务"],
            ["observations", "页面观察"],
            ["products", "产品库"],
          ].map(([id, name]) => (
            <button
              className={view === id ? "selected" : ""}
              key={id}
              onClick={() => setView(id)}
            >
              {name}
              {id === "jobs" && state.jobs.length > 0 && (
                <span>{state.jobs.length}</span>
              )}
            </button>
          ))}
        </div>
        <div className="actions">
          <button
            className="button secondary"
            onClick={() => setView("background")}
          >
            <Icon name="refresh" />
            后台同步
          </button>
          <button className="button primary" onClick={() => setUpload(true)}>
            <Icon name="upload" />
            导入素材
          </button>
        </div>
      </div>
      {view === "materials" && (
        <section className="panel">
          <p className="library-explanation">
            后台只把与旅游产品有关的内容保留为资料。普通聊天、生活照片和无产品信息的旅行分享会跳过；尚待判断的候选在“待识别”中查看。手动导入与已有业务引用保留。
          </p>
          <div className="toolbar">
            <div className="search-input">
              <Icon name="search" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索素材内容、产品或供应商"
                aria-label="搜索素材"
              />
            </div>
            <select
              aria-label="筛选来源"
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
            >
              <option value="">全部来源</option>
              {state.sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.display_name}
                  {s.acquisition_mode === "background"
                    ? s.kind === "chat"
                      ? " · 一对一聊天"
                      : " · 朋友圈"
                    : ""}
                </option>
              ))}
            </select>
            <span className="count-label">{materials.length} 项资料</span>
          </div>
          {materials.length === 0 ? (
            <Empty
              title={query ? "没有找到对应素材" : "从一份真实资料开始"}
              text={
                query
                  ? "尝试更换关键词或来源筛选。"
                  : "核验已授权好友，检查本地历史中的旅游产品资料；也可以导入手头的行程与报价。没有符合条件的内容时不会生成空资料。"
              }
            >
              <div className="empty-options">
                <button
                  onClick={() => {
                    setView("background");
                  }}
                >
                  <Icon name="chat" />
                  已授权好友的后台同步
                  <Icon name="arrow" size={16} />
                </button>
                <button onClick={() => setUpload(true)}>
                  <Icon name="upload" />
                  上传图片、文档或文字
                  <Icon name="arrow" size={16} />
                </button>
              </div>
            </Empty>
          ) : (
            <div className="material-table">
              <div className="table-header">
                <span>素材内容</span>
                <span>来源 / 供应商</span>
                <span>原文时间</span>
                <span>整理状态</span>
                <span />
              </div>
              {materials.map((m) => (
                <button
                  className="material-row"
                  key={m.id}
                  onClick={() =>
                    action(async () => {
                      setMaterial(await api(`/api/materials/${m.id}`));
                    })
                  }
                >
                  <div className="material-name">
                    <div className="file-icon">
                      <Icon
                        name={
                          m.attachments?.some((a: RecordData) =>
                            a.mime?.startsWith("image"),
                          )
                            ? "image"
                            : "file"
                        }
                        size={22}
                      />
                    </div>
                    <div>
                      <strong>
                        {m.title ||
                          m.filename ||
                          m.attachments?.[0]?.name ||
                          m.text?.slice(0, 42) ||
                          "未命名素材"}
                      </strong>
                      <p>
                        {m.text?.slice(0, 65) ||
                          m.source_note ||
                          "资料已保存，打开查看详情"}
                      </p>
                      {m.acquisition_method ===
                        "assistant_native_ui_manual" && (
                        <span className="acquisition-label">
                          实机人工辅助采集 · 自动采集尚未验证
                        </span>
                      )}
                      {m.acquisition_method ===
                        "operator_positioned_native" && (
                        <span className="acquisition-label">
                          人工定位后自动采集
                        </span>
                      )}
                      {(m.acquisition_mode === "background" ||
                        m.classification) && (
                        <span className="acquisition-label">
                          {classificationLabel(m)}
                          {m.acquisition_mode === "background"
                            ? " · 后台同步"
                            : ""}
                        </span>
                      )}
                      {m.source_note && (
                        <span
                          className="material-source-note"
                          title={m.source_note}
                        >
                          来源备注：{m.source_note}
                        </span>
                      )}
                    </div>
                  </div>
                  <div>
                    {state.sources.find((s) => s.id === m.source_id)
                      ?.display_name || "来源待核对"}
                    <small>{m.supplier || "供应商未标注"}</small>
                    <small>
                      {state.sources.find((s) => s.id === m.source_id)?.kind ===
                      "group"
                        ? "微信群历史"
                        : state.sources.find((s) => s.id === m.source_id)
                              ?.kind === "moments"
                          ? "联系人朋友圈历史"
                          : state.sources.find((s) => s.id === m.source_id)
                                ?.kind === "upload"
                            ? "用户上传"
                            : state.sources.find((s) => s.id === m.source_id)
                                  ?.kind === "chat"
                              ? "一对一聊天"
                              : "来源类型待核对"}
                    </small>
                  </div>
                  <span>
                    {(m.acquisition_mode === "background" && m.publication_time
                      ? dateLabel(m.publication_time)
                      : null) ||
                      m.source_time_raw ||
                      (m.source_time
                        ? dateLabel(m.source_time)
                        : "发布时间未知")}
                    <small>
                      {dateLabel(m.imported_at || m.created_at)} 导入
                    </small>
                  </span>
                  <div>
                    <Badge value={m.extraction_state || m.state || "STORED"} />
                  </div>
                  <Icon name="chevron" size={16} />
                </button>
              ))}
            </div>
          )}
        </section>
      )}
      {view === "pending" && (
        <PendingCandidates state={state} action={action} />
      )}
      {view === "background" && (
        <BackgroundSync
          state={state}
          action={action}
          onOpenMaterials={(id) => {
            setSourceFilter(id);
            setQuery("");
            setView("materials");
          }}
        />
      )}
      {view === "sources" && (
        <div className="source-layout">
          <section className="panel">
            <SectionHead
              title="已保存的微信来源"
              subtitle="旧群聊和其他联系人继续暂停；当前好友的后台任务请到“后台同步”操作。"
            />
            {state.sources.filter((s) => s.kind !== "upload").length === 0 ? (
              <Empty
                icon="chat"
                title="还没有选定微信来源"
                text="请到“后台同步”核验当前已授权账号与好友。"
              />
            ) : (
              <div className="source-list">
                {state.sources
                  .filter((s) => s.kind !== "upload")
                  .map((s) => (
                    <label
                      className={`source-row ${selected.includes(s.id) ? "checked" : ""}`}
                      key={s.id}
                    >
                      <input
                        type="checkbox"
                        disabled
                        checked={selected.includes(s.id)}
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? [...selected, s.id]
                              : selected.filter((id) => id !== s.id),
                          )
                        }
                      />
                      <span className="source-icon">
                        <Icon
                          name={s.kind === "moments" ? "image" : "chat"}
                          size={22}
                        />
                      </span>
                      <span>
                        <strong>{s.display_name}</strong>
                        <small>
                          {s.kind === "moments"
                            ? "联系人朋友圈历史"
                            : s.kind === "chat"
                              ? "一对一聊天"
                              : "微信群历史"}{" "}
                          ·{" "}
                          {state.accounts.find((a) => a.id === s.account_id)
                            ?.display_name || "账号待确认"}
                        </small>
                        <p>{display(s.identity_evidence)}</p>
                      </span>
                      <Badge value={s.capabilities?.status || "NOT_TESTED"} />
                    </label>
                  ))}
              </div>
            )}
            <div className="panel-bottom">
              <button
                className="button secondary"
                onClick={() => setView("background")}
              >
                <Icon name="refresh" />
                打开后台同步
              </button>
            </div>
          </section>
          <section className="panel scan-panel">
            <h2>旧采集记录保留</h2>
            <p>
              已选择 <strong>{selectedSources.length}</strong> 个来源
            </p>
            <NativeCollection />
          </section>
        </div>
      )}
      {view === "observations" && (
        <PageObservations state={state} action={action} />
      )}
      {view === "jobs" && (
        <section className="panel">
          <SectionHead
            title="采集与覆盖记录"
            subtitle="采集、附件下载、内容分析分开记录；不以进度百分比代替实际覆盖。"
          />
          {!state.jobs.length ? (
            <Empty
              icon="clock"
              title="暂无旧采集任务"
              text="新的后台任务、附件重试与覆盖情况请到“后台同步”查看。"
            />
          ) : (
            <div className="job-list">
              {state.jobs.map((j) => (
                <article className="job-card" key={j.id}>
                  <div className="job-heading">
                    <div>
                      <h3>
                        {state.sources.find((s) => s.id === j.source_id)
                          ?.display_name ||
                          j.source_name ||
                          "已选择的来源"}
                      </h3>
                      <p>
                        {j.acquisition_mode === "operator_positioned"
                          ? `单次执行最多 ${j.page_budget || j.scope?.page_budget || "指定"} 页`
                          : (
                              {
                                ALL_ACCESSIBLE: "全部可访问历史",
                                SINCE: "指定时间起",
                                INCREMENTAL: "增量更新",
                              } as RecordData
                            )[j.mode] || j.mode}{" "}
                        · {dateLabel(j.created_at)}
                      </p>
                      {j.acquisition_mode === "operator_positioned" && (
                        <Badge value="OPERATOR_POSITIONED" tone="amber" />
                      )}
                    </div>
                    <Badge value={j.state} />
                  </div>
                  <div className="coverage">
                    <Icon name="clock" />
                    <span>
                      {label(j.coverage || j.coverage_outcome || "UNKNOWN")}
                    </span>
                  </div>
                  <div
                    className={`job-counts ${j.acquisition_mode === "operator_positioned" ? "positioned-counts" : ""}`}
                  >
                    {(j.acquisition_mode === "operator_positioned"
                      ? [
                          ["页面观察", j.counts?.page_observations ?? 0],
                          ["已解析记录", j.counts?.parsed_records ?? 0],
                          ["已取回附件", j.counts?.acquired_attachments ?? 0],
                          [
                            "关联待核对",
                            j.counts?.unresolved_associations ?? 0,
                          ],
                        ]
                      : [
                          [
                            "发现记录",
                            j.counts?.discovered ?? j.discovered_count ?? 0,
                          ],
                          [
                            "保存附件",
                            j.counts?.saved ?? j.saved_attachments ?? 0,
                          ],
                          ["原件", j.counts?.originals ?? 0],
                          ["预览", j.counts?.previews ?? 0],
                          [
                            "失败 / 待重试",
                            j.counts?.media_failures ?? j.retry_count ?? 0,
                          ],
                          ["时间待核对", j.counts?.unresolved_dates ?? 0],
                        ]
                    ).map(([name, n]) => (
                      <div key={String(name)}>
                        <strong>{n}</strong>
                        <span>{name}</span>
                      </div>
                    ))}
                  </div>
                  {j.acquisition_mode === "operator_positioned" ? (
                    <p className="small">
                      以上为本任务累计数量。页面截图单独保存，不等于已解析消息或供应商原件。页数上限与重复画面均不证明历史终点。
                    </p>
                  ) : (
                    <p className="small">
                      请求范围：{j.requested_start || j.start || "可访问起点"}{" "}
                      至 {dateLabel(j.cutoff_at || j.cutoff || j.created_at)}
                    </p>
                  )}
                  {j.acquisition_mode === "operator_positioned" && (
                    <p className="small">
                      附件失败 / 待重试：{j.counts?.media_failures ?? 0} ·
                      附件不可用：{j.counts?.media_unavailable ?? 0} ·
                      时间待核对：{j.counts?.unresolved_dates ?? 0}
                    </p>
                  )}
                  <p className="small">
                    观察到的时间：{j.observed_earliest || "尚未记录"} 至{" "}
                    {j.observed_latest || "尚未记录"}
                  </p>
                  {j.stop_reason && (
                    <div className="warning-box">
                      <Icon name="alert" />
                      <p>{j.stop_reason}</p>
                    </div>
                  )}
                  {j.state === "COMPATIBILITY_BLOCKED" && (
                    <p className="small">
                      技术人员需继续适配此能力；重新点击采集不能解决当前缺口。
                    </p>
                  )}
                  <div className="actions job-actions">
                    {["RUNNING", "QUEUED"].includes(j.state) && (
                      <button
                        className="button secondary"
                        onClick={() =>
                          action(() => api(`/api/jobs/${j.id}/pause`, "POST"))
                        }
                      >
                        暂停
                      </button>
                    )}
                    <p className="small">
                      前台采集已暂停，恢复与附件重试入口暂不开放。历史记录和检查点继续保留。
                    </p>
                    {!["CANCELED", "COMPLETED"].includes(j.state) && (
                      <button
                        className="button ghost"
                        onClick={() =>
                          action(() => api(`/api/jobs/${j.id}/cancel`, "POST"))
                        }
                      >
                        取消任务
                      </button>
                    )}
                    <details>
                      <summary>查看检查点与覆盖证据</summary>
                      <pre>
                        {JSON.stringify(
                          {
                            checkpoint: j.checkpoint,
                            coverage_evidence: j.coverage_evidence,
                            counts: j.counts,
                          },
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      )}
      {view === "products" && (
        <section className="panel">
          <SectionHead
            title="已整理产品"
            subtitle="每个价格保留出发日期、旅客类别和适用条件。"
          >
            <button className="button secondary" onClick={() => onProduct({})}>
              <Icon name="plus" />
              手动录入产品
            </button>
          </SectionHead>
          {!state.products.length ? (
            <Empty
              icon="compass"
              title="产品库等待整理"
              text="打开一份素材，运行分析或手动整理成产品。无需配置 AI，也可以录入与筛选。"
            />
          ) : (
            <div className="product-grid">
              {state.products.map((p) => (
                <article className="product-card" key={p.id}>
                  <div className="product-card-top">
                    <span>{p.supplier || "供应商待确认"}</span>
                    <Badge value={p.review_state || "PARTIAL"} />
                  </div>
                  <h3>{p.title}</h3>
                  <p>
                    {p.destination || "目的地待确认"} ·{" "}
                    {p.duration_days ? `${p.duration_days} 天` : "天数待确认"}
                  </p>
                  <div className="product-price">{price(p.offers?.[0])}</div>
                  <p className="small">
                    {p.offers?.[0]?.departure_date || "适用日期待确认"} ·{" "}
                    {p.offers?.length || 0} 个报价条件
                  </p>
                  <button
                    className="button secondary full"
                    onClick={() => onProduct(p)}
                  >
                    查看与修订
                    <Icon name="arrow" size={15} />
                  </button>
                </article>
              ))}
            </div>
          )}
        </section>
      )}
      {upload && (
        <UploadModal action={action} onClose={() => setUpload(false)} />
      )}{" "}
      {sourceModal && (
        <SourceModal
          state={state}
          action={action}
          onClose={() => setSourceModal(false)}
        />
      )}{" "}
      {material && (
        <MaterialDetail
          material={material}
          source={state.sources.find((s) => s.id === material.source_id)}
          action={action}
          onClose={() => setMaterial(null)}
          onProduct={onProduct}
        />
      )}
    </>
  );
}

function UploadModal({
  action,
  onClose,
}: {
  action: Action;
  onClose: () => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [text, setText] = useState("");
  const [supplier, setSupplier] = useState("");
  const [note, setNote] = useState("");
  const [drag, setDrag] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  return (
    <Modal
      title="导入素材"
      subtitle="原件保存在本机，导入后可分析或手动整理。"
      onClose={onClose}
    >
      <div className="modal-body">
        <div
          className={`dropzone ${drag ? "drag" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            setFiles([...files, ...Array.from(e.dataTransfer.files)]);
          }}
        >
          <Icon name="upload" size={30} />
          <h3>将图片或文件拖到这里</h3>
          <p>支持多选 · 图片、PDF、Word、Excel、CSV、TXT</p>
          <label className="button secondary file-picker">
            选择文件
            <input
              type="file"
              multiple
              onChange={(e) =>
                setFiles([...files, ...Array.from(e.target.files || [])])
              }
            />
          </label>
        </div>
        {files.length > 0 && (
          <ul className="file-list">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`}>
                <Icon name="file" />
                <span>
                  {f.name}
                  <small>{(f.size / 1024).toFixed(1)} KB</small>
                </span>
                <button
                  className="icon-button"
                  aria-label={`移除 ${f.name}`}
                  onClick={() => setFiles(files.filter((_, n) => n !== i))}
                >
                  <Icon name="close" size={15} />
                </button>
              </li>
            ))}
          </ul>
        )}
        <Field label="或粘贴原始文字">
          <textarea
            rows={5}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="粘贴供应商介绍、行程或报价。原始文字会保留。"
          />
        </Field>
        <div className="form-grid">
          <Field label="供应商标签（选填）">
            <input
              value={supplier}
              onChange={(e) => setSupplier(e.target.value)}
              placeholder="例如：海岛专线供应商"
            />
          </Field>
          <Field label="来源 / 日期备注（选填）">
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="例如：10 月报价单，发布日期待确认"
            />
          </Field>
        </div>
        <p className="small">
          上传时间不会自动当作原始发布日期。暂不支持分析的附件也会保存原件。
        </p>
      </div>
      <div className="modal-footer">
        <button className="button secondary" onClick={onClose}>
          取消
        </button>
        <button
          className="button primary"
          disabled={submitting || (!files.length && !text.trim())}
          onClick={async () => {
            setSubmitting(true);
            const r = await action(async () => {
              if (files.length) {
                const form = new FormData();
                files.forEach((f) => form.append("files", f));
                form.append("supplier", supplier);
                form.append("source_note", note);
                await api("/api/uploads", "POST", form);
              }
              if (text.trim())
                await api("/api/paste", "POST", {
                  text,
                  supplier,
                  source_note: note,
                });
              return true;
            }, "素材已保存，可打开查看原件并整理产品。");
            setSubmitting(false);
            if (r) onClose();
          }}
        >
          {submitting
            ? "正在保存…"
            : `保存素材${files.length ? `（${files.length} 个文件）` : ""}`}
        </button>
      </div>
    </Modal>
  );
}

function SourceModal({
  state,
  action,
  onClose,
}: {
  state: AppState;
  action: Action;
  onClose: () => void;
}) {
  const [account, setAccount] = useState(state.accounts[0]?.id || "");
  const [kind, setKind] = useState("group");
  const [name, setName] = useState("");
  const [evidence, setEvidence] = useState("");
  const [newAccount, setNewAccount] = useState(false);
  const [accountName, setAccountName] = useState("");
  const [accountEvidence, setAccountEvidence] = useState("");
  return (
    <Modal
      title="选择微信采集来源"
      subtitle="只采集您明确选择的群或联系人的朋友圈。"
      onClose={onClose}
    >
      <div className="modal-body">
        <Field label="微信账号">
          <select value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="">选择已绑定账号</option>
            {state.accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.display_name}
              </option>
            ))}
          </select>
        </Field>
        <button
          className="text-button"
          onClick={() => setNewAccount(!newAccount)}
        >
          ＋ 绑定当前微信账号
        </button>
        {newAccount && (
          <div className="inset-panel">
            <Field label="可观察到的账号名称">
              <input
                value={accountName}
                onChange={(e) => setAccountName(e.target.value)}
                placeholder="请与已登录微信中显示的信息一致"
              />
            </Field>
            <Field label="账号识别依据">
              <textarea
                rows={2}
                value={accountEvidence}
                onChange={(e) => setAccountEvidence(e.target.value)}
                placeholder="填写界面可见的身份信息，不要填写密码。"
              />
            </Field>
            <button
              className="button secondary"
              disabled={!accountName || !accountEvidence}
              onClick={() =>
                action(async () => {
                  const r = await api("/api/accounts", "POST", {
                    display_name: accountName,
                    identity_evidence: accountEvidence,
                  });
                  setAccount(r.id);
                  setNewAccount(false);
                  return r;
                }, "账号绑定已保存；采集前仍需实际校验。")
              }
            >
              保存账号绑定
            </button>
          </div>
        )}
        <Field label="来源类型">
          <div className="segmented">
            <button
              className={kind === "group" ? "selected" : ""}
              onClick={() => setKind("group")}
            >
              <Icon name="chat" />
              微信群历史
            </button>
            <button
              className={kind === "moments" ? "selected" : ""}
              onClick={() => setKind("moments")}
            >
              <Icon name="image" />
              联系人朋友圈历史
            </button>
          </div>
        </Field>
        <Field label={kind === "group" ? "群名称" : "联系人显示名称"}>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="请按微信内的实际名称填写"
          />
        </Field>
        <Field
          label="区分同名来源的依据"
          hint="例如群成员、联系人备注或资料页中可观察的信息。不会自动生成微信 ID。"
        >
          <textarea
            rows={3}
            value={evidence}
            onChange={(e) => setEvidence(e.target.value)}
            placeholder="填写足以再次定位并核对这一来源的信息"
          />
        </Field>
        <div className="info-box">
          <Icon name="alert" />
          <p>
            保存选择不代表已验证采集能力。朋友圈必须来自该联系人的历史页面；综合信息流筛选不算完整历史。
          </p>
        </div>
      </div>
      <div className="modal-footer">
        <button className="button secondary" onClick={onClose}>
          取消
        </button>
        <button
          className="button primary"
          disabled={!account || !name || !evidence}
          onClick={() =>
            action(async () => {
              const r = await api("/api/sources", "POST", {
                account_id: account,
                kind,
                display_name: name,
                identity_evidence: evidence,
              });
              onClose();
              return r;
            }, "来源选择已保存，请在采集任务中查看实际能力与结果。")
          }
        >
          保存来源选择
        </button>
      </div>
    </Modal>
  );
}

function MaterialDetail({
  material,
  source,
  action,
  onClose,
  onProduct,
}: {
  material: RecordData;
  source?: RecordData;
  action: Action;
  onClose: () => void;
  onProduct: (p: RecordData) => void;
}) {
  const [current, setCurrent] = useState(material);
  useEffect(() => {
    const id = setInterval(
      () =>
        api(`/api/materials/${material.id}`)
          .then(setCurrent)
          .catch(() => {}),
      2500,
    );
    return () => clearInterval(id);
  }, [material.id]);
  return (
    <Modal
      title="素材详情"
      subtitle="原始资料与整理结果并排保留，方便回查。"
      onClose={onClose}
      wide
    >
      <div className="material-detail">
        <div className="original-pane">
          <div className="minor-heading">
            <Icon name="file" />
            原始资料
          </div>
          {current.acquisition_method === "assistant_native_ui_manual" && (
            <div className="warning-box acquisition-notice" role="status">
              <Icon name="alert" />
              <p>实机人工辅助采集 · 自动采集尚未验证</p>
            </div>
          )}
          {current.acquisition_method === "operator_positioned_native" && (
            <div className="info-box acquisition-notice" role="status">
              <Icon name="check" />
              <p>人工定位后自动采集 · 本轮来源绑定</p>
            </div>
          )}
          {current.acquisition_mode === "background" && (
            <div className="info-box acquisition-notice">
              <Icon name="refresh" />
              <p>后台同步资料 · 文本、附件和历史覆盖分别记录</p>
            </div>
          )}
          <div className="original-meta">
            来源：{source?.display_name || current.source_name || "来源待核对"}
            <br />
            类型：
            {source?.kind === "group"
              ? "微信群历史"
              : source?.kind === "moments"
                ? "联系人朋友圈历史"
                : source?.kind === "upload"
                  ? "用户上传"
                  : source?.kind === "chat"
                    ? "一对一聊天"
                    : "来源类型待核对"}
            <br />
            原文时间：
            {(current.acquisition_mode === "background" &&
            current.publication_time
              ? dateLabel(current.publication_time)
              : null) ||
              current.source_time_raw ||
              (current.source_time
                ? dateLabel(current.source_time)
                : "时间未知")}
            <br />
            导入：{dateLabel(current.imported_at || current.created_at)}
            <br />
            {current.observation_time_precision === "day"
              ? "观察日期："
              : "观察时间："}
            {current.observation_time_precision === "day"
              ? String(current.observed_at || "日期未知").slice(0, 10)
              : dateLabel(current.observed_at)}
            <br />
            发布者：
            {current.acquisition_mode === "background"
              ? current.direction === "sent"
                ? "我（当前账号）"
                : source?.display_name || "已授权好友"
              : display(current.author || "未注明")}
            {source?.kind === "chat" && (
              <>
                <br />
                收发方向：
                {["sent", "outgoing", "outbound"].includes(current.direction)
                  ? "我发出"
                  : ["received", "incoming", "inbound"].includes(
                        current.direction,
                      )
                    ? "对方发来"
                    : "待核对"}
              </>
            )}
            <br />
            供应商：{current.supplier || "未标注"}
            <br />
            备注：{current.source_note || "无"}
          </div>
          {current.time_evidence?.status === "parsed" && (
            <p className="small">
              {current.time_evidence.precision === "minute"
                ? "来源时间已按分钟区间保存；未补填秒数。"
                : current.time_evidence.precision === "day"
                  ? "来源时间精确到日期，按当天的时间区间保存，未补填具体时刻。"
                  : current.time_evidence.precision === "relative_interval"
                    ? "来源为相对时间，按观察时的日期和已知精度保留时间区间。"
                    : "来源时间已根据原文保存。"}
            </p>
          )}
          {current.source_time_raw &&
            !current.source_time &&
            !current.publication_time &&
            current.time_evidence?.status !== "parsed" && (
              <p className="small">
                {current.time_evidence?.status === "context_only"
                  ? "时间来自界面的分隔标记，仅作为上下文证据；不能当作这条记录的精确发布时间。"
                  : "原文时间尚未完整确定。缺失的年份或具体时刻保持未知，不按导入时间补填。"}
              </p>
            )}
          {current.text && <pre className="source-text">{current.text}</pre>}
          {Array.isArray(current.product_context) &&
            current.product_context.length > 0 && (
              <section className="product-context">
                <h4>已关联的产品补充信息</h4>
                <p className="small">
                  仅保留有明确回复关系的相关补充，适用日期与条件仍需结合原文核对。
                </p>
                {current.product_context.map(
                  (context: RecordData, index: number) => (
                    <article key={context.event_key || index}>
                      <p className="small">
                        {dateLabel(
                          context.publication_time || context.source_time,
                        )}
                      </p>
                      <pre className="source-text">
                        {context.text || "补充内容暂无可显示文字"}
                      </pre>
                    </article>
                  ),
                )}
              </section>
            )}
          <ClassificationEditor
            record={current}
            kind="materials"
            action={action}
            onChanged={async () =>
              setCurrent(await api(`/api/materials/${current.id}`))
            }
          />
          {current.attachments?.map((attachment: RecordData) => {
            const saved =
              String(attachment.state || "").toUpperCase() === "SAVED";
            const a: RecordData = {
              ...attachment,
              url:
                attachment.url ||
                (saved && attachment.id
                  ? `/api/attachments/${encodeURIComponent(attachment.id)}`
                  : null),
            };
            return (
              <div className="attachment" key={a.id || a.name}>
                {a.mime?.startsWith("image") && a.url && (
                  <img
                    src={`${a.url}${a.url.includes("?") ? "&" : "?"}preview=true`}
                    alt={a.name || "原始素材图片"}
                  />
                )}
                <div>
                  <Icon name="file" />
                  <strong>{a.name || a.original_name || "附件"}</strong>
                  <Badge value={a.quality || a.state || "UNKNOWN"} />
                  {a.acquisition_mode === "background" && (
                    <Badge value={a.media_state || a.state || "UNKNOWN"} />
                  )}
                </div>
                {a.url ? (
                  <a
                    className="text-button"
                    href={a.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {a.quality === "original"
                      ? "打开原件"
                      : a.quality === "screenshot"
                        ? "打开截图"
                        : a.quality === "preview"
                          ? "打开预览"
                          : "打开已保存附件"}{" "}
                    ↗
                  </a>
                ) : (
                  <p className="small">
                    {saved
                      ? "附件已保存，但暂缺打开链接，请刷新资料或检查附件记录。"
                      : "附件尚未取回，请查看采集任务中的重试项。"}
                  </p>
                )}
                {(a.retrieved_at ||
                  a.bytes_saved_at ||
                  a.fetched_at ||
                  a.saved_at) && (
                  <p className="small">
                    取回时间：
                    {dateLabel(
                      a.retrieved_at ||
                        a.bytes_saved_at ||
                        a.fetched_at ||
                        a.saved_at,
                    )}
                  </p>
                )}
                {a.last_error && (
                  <p className="issue">
                    {typeof a.last_error === "string"
                      ? a.last_error
                      : a.last_error.message ||
                        a.last_error.reason ||
                        "附件尚未取回，请查看来源任务。"}
                  </p>
                )}
                {a.id && (
                  <ClassificationEditor
                    record={a}
                    kind="attachments"
                    action={action}
                    onChanged={async () =>
                      setCurrent(await api(`/api/materials/${current.id}`))
                    }
                  />
                )}
              </div>
            );
          })}
        </div>
        <div className="structured-pane">
          <h3>整理为可比较的产品</h3>
          <p>一份素材可以对应多个产品。同一产品也可以关联多份原始资料。</p>
          <div className="actions">
            <button
              className="button primary"
              onClick={() =>
                action(async () => {
                  await api(`/api/materials/${current.id}/analyze`, "POST");
                  setCurrent(await api(`/api/materials/${current.id}`));
                  return true;
                }, "已加入分析队列，结果会自动更新。")
              }
            >
              <Icon name="spark" />
              分析素材
            </button>
            <button
              className="button secondary"
              onClick={() =>
                onProduct({
                  source_item_ids: [current.id],
                  supplier: current.supplier,
                })
              }
            >
              <Icon name="plus" />
              手动整理产品
            </button>
          </div>
          <div className="divider" />
          <h4>提取结果与问题</h4>
          {current.extracted_text && (
            <details open>
              <summary>本地提取文字</summary>
              <pre className="source-text">{current.extracted_text}</pre>
            </details>
          )}
          {(current.issues || []).map((issue: any, n: number) => (
            <p className="issue" key={n}>
              {display(issue)}
            </p>
          ))}
          {(current.extractions || []).length ? (
            (current.extractions || []).map((x: RecordData, i: number) => (
              <article className="extraction" key={x.id || i}>
                <Badge
                  value={x.status || x.state || x.result?.status || "UNKNOWN"}
                />
                <p className="small">
                  {dateLabel(x.created_at)} ·{" "}
                  {x.model || x.provider || "本地解析"}
                </p>
                {(x.issues || x.result?.issues || []).map(
                  (issue: any, n: number) => (
                    <p className="issue" key={n}>
                      {display(issue)}
                    </p>
                  ),
                )}
                {x.text && <pre className="source-text">{x.text}</pre>}
                {(x.products || x.result?.products || []).map(
                  (p: RecordData, n: number) => (
                    <button
                      className="extracted-product"
                      key={n}
                      onClick={() =>
                        onProduct({ ...p, source_item_ids: [current.id] })
                      }
                    >
                      <strong>{p.title || "待整理产品"}</strong>
                      <span>
                        检查并保存产品 <Icon name="arrow" size={14} />
                      </span>
                    </button>
                  ),
                )}
              </article>
            ))
          ) : (
            <div className="info-box">
              <Icon name="file" />
              <p>
                尚无分析结果。未配置 AI
                时，文档可先提取文字，图片可手动整理，之后再继续分析。
              </p>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

function Cases({ state, action }: { state: AppState; action: Action }) {
  const [active, setActive] = useState<RecordData | null>(null);
  const [versions, setVersions] = useState<RecordData[]>([]);
  return (
    <section className="panel">
      <SectionHead
        title="客户接待档案"
        subtitle="保留需求、产品与输出版本；复制或导出不会标记为已发送。"
      />
      {!state.cases.length ? (
        <Empty
          icon="cases"
          title="每一次认真比较，都值得留下"
          text="在选团工作台保存客户需求，生成的推荐将按版本留存在这里。"
        />
      ) : (
        <div className="case-grid">
          {state.cases.map((c) => (
            <button
              className="case-card"
              key={c.id}
              onClick={() => {
                setActive(c);
                setVersions([]);
              }}
            >
              <div className="case-avatar">
                <Icon name="user" />
              </div>
              <div>
                <h3>{c.name || "未命名接待"}</h3>
                <p>{c.request_text || "已保存结构化需求"}</p>
                <span>{dateLabel(c.updated_at || c.created_at)}</span>
              </div>
              <Icon name="chevron" />
            </button>
          ))}
        </div>
      )}
      {active && (
        <Modal
          title={active.name || "接待记录"}
          onClose={() => setActive(null)}
          wide
        >
          <div className="modal-body">
            <p className="source-text">
              {active.request_text || "未填写原始需求"}
            </p>
            <div className="key-values">
              {Object.entries(active.requirements || {})
                .filter(
                  ([k]) => fieldLabels[k] && !["budget", "hotels"].includes(k),
                )
                .map(([k, v]) => (
                  <div key={k}>
                    <dt>{fieldLabels[k]}</dt>
                    <dd>{humanValue(v)}</dd>
                  </div>
                ))}
            </div>
            <h3>推荐版本</h3>
            {state.recommendations
              .filter((r) => r.case_id === active.id)
              .map((r) => (
                <article className="recommendation-history" key={r.id}>
                  <div className="section-head">
                    <strong>{dateLabel(r.created_at)}</strong>
                    <Badge
                      value={
                        r.stale || r.needs_review ? "需重新核对" : "已准备"
                      }
                    />
                  </div>
                  <pre className="source-text">{r.text}</pre>
                  <div className="actions">
                    <button
                      className="button secondary"
                      onClick={() =>
                        action(async () => {
                          await navigator.clipboard.writeText(r.text || "");
                          return true;
                        }, "介绍已复制，未自动发送。")
                      }
                    >
                      <Icon name="copy" />
                      复制介绍
                    </button>
                    <button
                      className="button secondary"
                      onClick={() =>
                        action(
                          () =>
                            api(`/api/recommendations/${r.id}/export`, "POST"),
                          "该版本已导出，可在推荐记录中查看。",
                        )
                      }
                    >
                      <Icon name="download" />
                      导出此版本
                    </button>
                    <button
                      className="button ghost"
                      onClick={() =>
                        action(async () => {
                          setVersions(
                            await api(`/api/recommendations/${r.id}/versions`),
                          );
                          return true;
                        })
                      }
                    >
                      查看修订历史
                    </button>
                    {r.image_url && (
                      <a
                        className="button secondary"
                        href={r.image_url}
                        download
                      >
                        保存图片
                      </a>
                    )}
                  </div>
                </article>
              ))}
            {versions.length > 0 && (
              <div className="version-history">
                <h3>保存的历史版本</h3>
                {versions.map((v, i) => (
                  <article className="recommendation-history" key={i}>
                    <strong>
                      版本 {v.version || i + 1} · {dateLabel(v.created_at)}
                    </strong>
                    <pre className="source-text">{v.text || v.data?.text}</pre>
                    {(v.image_url || v.data?.image_url) && (
                      <a
                        className="button secondary"
                        href={v.image_url || v.data?.image_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        查看该版本图片
                      </a>
                    )}
                  </article>
                ))}
              </div>
            )}
            {!state.recommendations.some((r) => r.case_id === active.id) && (
              <p className="muted">这条接待记录还没有准备过推荐。</p>
            )}
          </div>
        </Modal>
      )}
    </section>
  );
}

function Weekly({ state, action }: { state: AppState; action: Action }) {
  const [ids, setIds] = useSaved<string[]>("weekly-selection", []);
  const [title, setTitle] = useSaved("weekly-title", "本周精选旅行资料");
  const [result, setResult] = useState<RecordData | null>(null);
  return (
    <div className="weekly-layout">
      <section className="panel">
        <SectionHead
          title="挑选本周资料"
          subtitle="复用已整理产品，保留来源、适用人群和待确认事项。"
        />
        {!state.products.length ? (
          <Empty
            icon="weekly"
            title="还没有可复用的产品"
            text="先在素材中心整理产品，再挑选需要收入本周资料的内容。"
          />
        ) : (
          <div className="weekly-products">
            {state.products.map((p) => (
              <label key={p.id}>
                <input
                  type="checkbox"
                  checked={ids.includes(p.id)}
                  onChange={(e) =>
                    setIds(
                      e.target.checked
                        ? [...ids, p.id]
                        : ids.filter((id) => id !== p.id),
                    )
                  }
                />
                <span>
                  <strong>{p.title}</strong>
                  <small>
                    {p.supplier || "供应商待确认"} · {price(p.offers?.[0])}
                  </small>
                </span>
              </label>
            ))}
          </div>
        )}
        <div className="panel-bottom">
          <Field label="资料包标题">
            <input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <button
            className="button primary"
            disabled={!ids.length || !title}
            onClick={() =>
              action(
                () =>
                  api("/api/weekly", "POST", {
                    title,
                    product_ids: ids,
                    recommendation_ids: [],
                  }),
                `已保存本周资料的 ${ids.length} 个产品选择。`,
              )
            }
          >
            <Icon name="save" />
            保存资料包
          </button>
        </div>
      </section>
      <section className="panel">
        <SectionHead
          title="已保存资料包"
          subtitle="每次导出保留当时的产品信息。"
        />
        {!state.weekly.length ? (
          <Empty
            icon="weekly"
            title="暂无资料包"
            text="选中左侧产品并保存，即可生成中文资料。"
          />
        ) : (
          <div className="weekly-list">
            {state.weekly.map((w) => (
              <article key={w.id}>
                <span className="date-chip">
                  <Icon name="weekly" />
                </span>
                <h3>{w.title}</h3>
                <p>
                  {w.product_ids?.length ?? w.products?.length ?? 0} 个产品 ·{" "}
                  {dateLabel(w.created_at)}
                </p>
                <button
                  className="button secondary"
                  onClick={() =>
                    action(async () => {
                      const r = await api(`/api/weekly/${w.id}/export`, "POST");
                      setResult(r);
                      return r;
                    }, "资料包已生成。")
                  }
                >
                  <Icon name="download" />
                  导出中文资料
                </button>
              </article>
            ))}
          </div>
        )}
        {result && (
          <div className="export-links">
            {Object.entries(result)
              .filter(([k, v]) => k.endsWith("_url") && typeof v === "string")
              .map(([k, v]) => (
                <a
                  className="button primary"
                  key={k}
                  href={String(v)}
                  target="_blank"
                  rel="noreferrer"
                  download
                >
                  {k.includes("image") ? "保存图片" : "下载资料"}
                </a>
              ))}
          </div>
        )}
      </section>
    </div>
  );
}
