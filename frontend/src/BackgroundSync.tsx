import { useEffect, useState } from "react";
import { api, dateLabel, label } from "./api";
import type { AppState, RecordData } from "./api";
import type { Action } from "./App";
import { Badge, Empty, Field, Icon, SectionHead } from "./ui";

const capabilityNames: Record<string, string> = {
  local_read: "本地资料读取",
  new_content: "真实新增发现",
  local_history: "本地历史检查",
  remote_history: "缺失历史获取",
  media: "图片与文件取回",
};
const modeNames: Record<string, string> = {
  continuous: "增量更新",
  history: "补充历史资料",
  media: "附件补齐",
};
const activeStates = new Set([
  "RUNNING",
  "QUEUED",
  "WAITING",
  "SCHEDULED",
  "IDLE",
  "BACKOFF",
  "RETRY_WAIT",
  "RETRY",
]);

function metric(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("zh-CN")
    : "未记录";
}

function ProcessingCounts({ counts = {} }: { counts?: RecordData }) {
  return (
    <div className="background-job-counts">
      {[
        ["inspected", "已检查"],
        ["new", "新发现"],
        ["kept", "保留为产品资料"],
        ["skipped", "已跳过"],
        ["pending", "待识别"],
        ["media_pending", "附件待补"],
      ].map(([key, name]) => (
        <div key={key}>
          <strong>{metric(counts[key])}</strong>
          <span>{name}</span>
        </div>
      ))}
    </div>
  );
}

function LastCycle({ processing = {} }: { processing?: RecordData }) {
  const cycle = processing.last_cycle || {};
  return (
    <div className="background-cycle">
      <p>
        最近检查：
        {processing.last_checked_at
          ? dateLabel(processing.last_checked_at)
          : "尚无记录"}
        {" · "}本轮保留：{metric(cycle.kept)}
        {" · "}更新资料：{metric(cycle.updated)}
      </p>
      <details>
        <summary>查看本轮处理工作量</summary>
        <p>
          查看原生记录 {metric(cycle.native_rows_inspected)} · 核对索引{" "}
          {metric(cycle.index_entries_inspected)} · 新发现或已改动{" "}
          {metric(cycle.new_or_changed)} · 读取正文{" "}
          {metric(cycle.content_reads)}
        </p>
        <p>
          分类 {metric(cycle.classification_operations)} · 图片文字识别{" "}
          {metric(cycle.ocr_operations)} · 附件取回{" "}
          {metric(cycle.media_retrieval_operations)} · 跳过{" "}
          {metric(cycle.skipped)} · 待识别 {metric(cycle.pending)}
        </p>
        <p className="small">
          本地快照复制 {metric(cycle.snapshot_copies)}{" "}
          次。核对索引或复制快照不代表重新识别全部历史内容。
        </p>
      </details>
    </div>
  );
}

function BackgroundBadge({ value }: { value?: RecordData }) {
  const status = String(
    value?.status || value?.state || "NOT_TESTED",
  ).toUpperCase();
  return (
    <Badge
      value={value?.label || label(status)}
      tone={
        ["PASS", "VERIFIED", "READY", "BOUND"].includes(status)
          ? "green"
          : /BLOCK|FAIL|PARTIAL|UNVERIFIED|INVALID/.test(status)
            ? "amber"
            : "neutral"
      }
    />
  );
}

export function BackgroundCapabilities({
  capabilities = {},
}: {
  capabilities?: RecordData;
}) {
  return (
    <div className="background-capabilities">
      {Object.entries({
        ...capabilityNames,
        ...(capabilities.documents ? { documents: "聊天文档取回" } : {}),
      }).map(([key, name]) => {
        const capability = capabilities[key] || {};
        return (
          <article key={key}>
            <strong>{name}</strong>
            <BackgroundBadge value={capability} />
            <p>{capability.reason || "尚未取得当前来源的验证结果。"}</p>
          </article>
        );
      })}
    </div>
  );
}

function rangeLabel(range?: RecordData) {
  const fromEpoch = (value: unknown) =>
    typeof value === "number" && Number.isFinite(value)
      ? new Date(value * 1000).toISOString()
      : undefined;
  const start =
    range?.start ||
    range?.min ||
    range?.earliest ||
    fromEpoch(range?.min_epoch ?? range?.start_epoch);
  const end =
    range?.end ||
    range?.max ||
    range?.latest ||
    fromEpoch(range?.max_epoch ?? range?.end_epoch);
  if (!start && !end) return "尚无时间范围记录";
  return `${start ? dateLabel(start) : "不限起点"} 至 ${end ? dateLabel(end) : "不限终点"}`;
}

function BackgroundJob({
  job,
  source,
  action,
}: {
  job: RecordData;
  source?: RecordData;
  action: Action;
}) {
  const [busy, setBusy] = useState(false);
  const command = async (operation: string) => {
    setBusy(true);
    try {
      await action(
        () =>
          api(
            `/api/background/jobs/${encodeURIComponent(job.id)}/${operation}`,
            "POST",
            {},
          ),
        operation === "pause"
          ? "已请求暂停，已保存的资料会保留。"
          : "任务已提交，进度会自动更新。",
      );
    } finally {
      setBusy(false);
    }
  };
  const active = activeStates.has(String(job.state).toUpperCase());
  const processing = job.processing || {
    last_cycle: job.last_cycle,
    last_checked_at: job.last_success_at,
  };
  return (
    <article className="background-job">
      <div className="background-job-heading">
        <div>
          <strong>
            {source?.display_name || job.source_name || "已授权来源"}
          </strong>
          <span>
            {(source?.kind || job.source_kind) === "chat" ? "聊天" : "朋友圈"}
            {" · "}
            {job.initial_history
              ? "首次历史检查"
              : modeNames[job.mode] || "后台任务"}
          </span>
        </div>
        <Badge
          value={
            job.state === "RUNNING" ? "正在检查与处理" : job.state || "UNKNOWN"
          }
        />
      </div>
      {(processing.counts || job.metrics) && (
        <>
          <ProcessingCounts counts={processing.counts || job.metrics} />
          <p className="small">
            本任务处理统计；已检查、新发现与跳过不等于产品资料数量。
          </p>
        </>
      )}
      {processing.last_cycle && <LastCycle processing={processing} />}
      <dl className="background-job-details">
        <div>
          <dt>上次成功</dt>
          <dd>
            {job.last_success_at
              ? dateLabel(job.last_success_at)
              : "尚无成功周期"}
          </dd>
        </div>
        <div>
          <dt>下次尝试</dt>
          <dd>{job.next_run_at ? dateLabel(job.next_run_at) : "暂无排期"}</dd>
        </div>
        <div>
          <dt>请求范围</dt>
          <dd>
            {job.mode === "continuous"
              ? "首次历史完成后检查新增、改动及到期的待处理内容"
              : job.mode === "media"
                ? "独立补齐保留资料与待识别候选所需附件"
                : job.requested_range?.start || job.requested_range?.end
                  ? `${rangeLabel(job.requested_range)}（结束时刻不含）`
                  : "全部可访问本地历史"}
          </dd>
        </div>
        <div>
          <dt>已观察时间</dt>
          <dd>{rangeLabel(job.observed_range)}</dd>
        </div>
        <div>
          <dt>启动基线</dt>
          <dd>
            {job.activation_baseline
              ? dateLabel(
                  typeof job.activation_baseline === "object"
                    ? job.activation_baseline.at ||
                        job.activation_baseline.activated_at ||
                        job.activation_baseline.cutoff ||
                        job.activation_baseline.time
                    : job.activation_baseline,
                )
              : "未记录 / 本任务不适用"}
          </dd>
        </div>
        <div>
          <dt>覆盖情况</dt>
          <dd>
            {job.coverage === "UNKNOWN" || !job.coverage
              ? "完整性未知"
              : label(job.coverage)}
          </dd>
        </div>
      </dl>
      {(job.last_error || job.stop_reason) && (
        <p
          className="background-job-reason"
          role={job.last_error ? "status" : undefined}
        >
          {typeof job.last_error === "string"
            ? job.last_error
            : job.last_error?.message ||
              job.last_error?.reason ||
              job.stop_reason}
        </p>
      )}
      <div className="actions">
        {active ? (
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => command("pause")}
          >
            暂停
          </button>
        ) : (
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => command("resume")}
          >
            继续任务
          </button>
        )}
        <button
          className="button secondary"
          disabled={busy || active}
          onClick={() => command("retry")}
        >
          重试任务
        </button>
      </div>
    </article>
  );
}

function SourceControls({
  source,
  capabilities,
  jobs,
  action,
  onOpenMaterials,
}: {
  source: RecordData;
  capabilities: RecordData;
  jobs: RecordData[];
  action: Action;
  onOpenMaterials: (id: string) => void;
}) {
  const [historyScope, setHistoryScope] = useState("all");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const processing = source.processing || {};
  const configuredInterval = processing.interval_seconds || 300;
  const [interval, setInterval] = useState(configuredInterval);
  const [batch, setBatch] = useState(50);
  const [reprocess, setReprocess] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => setInterval(configuredInterval), [configuredInterval]);
  const onboarding = String(processing.onboarding_state || "");
  const initialComplete = [
    "INITIAL_LOCAL_HISTORY_PROCESSED",
    "INCREMENTAL_ACTIVE",
  ].includes(onboarding);
  const active = (mode: string) =>
    jobs.some(
      (j) => j.mode === mode && activeStates.has(String(j.state).toUpperCase()),
    );
  const validSettings = () => {
    setError("");
    if (
      !Number.isInteger(interval) ||
      interval < 30 ||
      interval > 3600 ||
      !Number.isInteger(batch) ||
      batch < 1 ||
      batch > 200
    ) {
      setError("检查间隔为 30–3600 秒，每批条数为 1–200 的整数。");
      return false;
    }
    return true;
  };
  const sourceCommand = async (operation: "check" | "settings") => {
    if (operation === "settings" && !validSettings()) return;
    setBusy(true);
    try {
      await action(
        () =>
          api(
            `/api/background/sources/${encodeURIComponent(source.id)}/${operation}`,
            "POST",
            operation === "settings" ? { interval_seconds: interval } : {},
          ),
        operation === "check"
          ? "已安排立即检查，将保留现有进度。"
          : "检查间隔已保存。",
      );
    } finally {
      setBusy(false);
    }
  };
  const startJob = async (mode: string) => {
    if (!validSettings()) return;
    const usesRange =
      mode === "history" || (mode === "continuous" && !initialComplete);
    if (usesRange && historyScope === "dates" && !start && !end) {
      setError("请选择至少一个历史日期边界。");
      return;
    }
    if (usesRange && historyScope === "dates" && start && end && start >= end) {
      setError("结束日期须晚于开始日期；结束日期当天不包含在范围内。");
      return;
    }
    setBusy(true);
    try {
      const range =
        usesRange && historyScope === "dates"
          ? {
              ...(start ? { start: `${start}T00:00:00+08:00` } : {}),
              ...(end ? { end: `${end}T00:00:00+08:00` } : {}),
            }
          : {};
      await action(
        () =>
          api("/api/background/jobs", "POST", {
            source_id: source.id,
            mode,
            range,
            interval_seconds: interval,
            batch_size: batch,
            ...(mode === "history" ? { reprocess } : {}),
          }),
        mode === "history"
          ? "补充历史任务已提交，日常增量进度独立保留。"
          : "后台任务已提交，请查看首次历史与增量更新状态。",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel background-source">
      <div className="background-source-heading">
        <span className="source-icon">
          <Icon name={source.kind === "moments" ? "image" : "chat"} size={24} />
        </span>
        <div>
          <h3>{source.kind === "moments" ? "好友朋友圈" : "一对一聊天"}</h3>
          <p>{source.display_name}</p>
        </div>
        <button
          className="text-button"
          onClick={() => onOpenMaterials(source.id)}
        >
          查看产品资料 <Icon name="arrow" size={15} />
        </button>
      </div>
      <p className="small">
        {source.kind === "moments"
          ? "检查这位好友发布的内容，只保留与旅游产品有关的资料。"
          : "检查双方消息；有明确依据的产品补充信息随相关资料保留，普通聊天会跳过。"}
      </p>
      <div className="background-onboarding">
        <strong>来源处理阶段</strong>{" "}
        <Badge
          value={onboarding ? label(onboarding) : "首次历史状态尚未记录"}
        />
        <p className="small">
          先完成所选范围的首次本地历史检查，再按间隔处理新增、改动与到期候选。暂停或重启后继续已保存的进度。
        </p>
        {processing.initial_range && (
          <p className="small">
            首次范围：
            {processing.initial_range.start || processing.initial_range.end
              ? `${rangeLabel(processing.initial_range)}（结束时刻不含）`
              : "全部可访问本地历史"}
          </p>
        )}
      </div>
      <ProcessingCounts counts={processing.counts} />
      <p className="small">
        以上为此来源的累计处理结果。已检查与新发现不等于已保留的产品资料；附件待补与待识别分别统计。
      </p>
      <LastCycle processing={processing} />
      {typeof processing.counts?.acquisition_failed === "number" &&
        processing.counts.acquisition_failed > 0 && (
          <p className="issue">
            {metric(processing.counts.acquisition_failed)}{" "}
            项内容暂未取得，等待后续尝试；尚未判定相关性。
          </p>
        )}
      {capabilities && Object.keys(capabilities).length > 0 && (
        <details className="background-source-capabilities">
          <summary>查看此来源的独立能力状态</summary>
          <BackgroundCapabilities capabilities={capabilities} />
        </details>
      )}
      <div className="form-grid">
        <Field label="更新检查间隔（秒，默认 300）">
          <input
            type="number"
            min={30}
            max={3600}
            step={1}
            value={interval}
            onChange={(e) => setInterval(Number(e.target.value))}
          />
        </Field>
        <Field label="每批记录数">
          <input
            type="number"
            min={1}
            max={200}
            step={1}
            value={batch}
            onChange={(e) => setBatch(Number(e.target.value))}
          />
        </Field>
      </div>
      <div className="actions">
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => sourceCommand("settings")}
        >
          保存间隔
        </button>
        <button
          className="button secondary"
          disabled={
            busy ||
            (!initialComplete && !jobs.some((job) => job.mode === "continuous"))
          }
          onClick={() => sourceCommand("check")}
        >
          立即检查
        </button>
      </div>
      {!initialComplete && !jobs.some((job) => job.mode === "continuous") && (
        <p className="small">
          请先选择历史范围并开始首次检查；已有进度后可随时立即检查。
        </p>
      )}
      <div className="actions">
        <button
          className="button primary"
          disabled={busy || active("continuous")}
          onClick={() => startJob("continuous")}
        >
          <Icon name="refresh" />
          {active("continuous")
            ? "自动更新已安排"
            : initialComplete
              ? "开启增量更新"
              : "开始首次检查与自动更新"}
        </button>
        <button
          className="button secondary"
          disabled={busy || active("media")}
          onClick={() => startJob("media")}
        >
          补齐待取附件
        </button>
      </div>
      <p className="small">
        默认每 5
        分钟检查一次。已完成判断且没有改动的内容不会反复识别或下载。安静检查不会生成资料卡片，也不代表“真实新增已验证”。
      </p>
      <div className="background-history">
        <h4>补充历史资料</h4>
        <p className="small">
          主动检查额外日期范围；需要重新判断旧内容时，可明确勾选下方选项。首次检查尚未开始时，上方启动按钮也使用这里选择的范围。
        </p>
        <Field label="要检查的本地历史范围">
          <select
            value={historyScope}
            onChange={(e) => setHistoryScope(e.target.value)}
          >
            <option value="all">全部可访问本地历史</option>
            <option value="dates">指定日期范围</option>
          </select>
        </Field>
        {historyScope === "dates" && (
          <div className="form-grid">
            <Field label="开始日期（含当天）">
              <input
                type="date"
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </Field>
            <Field label="结束日期（不含当天）">
              <input
                type="date"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
              />
            </Field>
          </div>
        )}
        <label className="background-reprocess">
          <input
            type="checkbox"
            checked={reprocess}
            onChange={(event) => setReprocess(event.target.checked)}
          />
          <span>重新判断此范围内已处理的内容（保留已有人工决定）</span>
        </label>
        <div className="actions">
          <button
            className="button secondary"
            disabled={busy || active("history")}
            onClick={() => startJob("history")}
          >
            {active("history") ? "补充历史任务已运行" : "开始补充历史资料"}
          </button>
          {source.kind === "moments" && (
            <button
              className="text-button"
              onClick={() => {
                setHistoryScope("dates");
                setStart("2025-01-01");
                setEnd("2026-01-01");
              }}
            >
              设为 2025 年
            </button>
          )}
        </div>
        <p className="small">
          日期按中国标准时间，结束日期不含当天。只检查微信本地可访问的内容；不是取回服务器上的全部历史。补充范围不限制日常增量更新。
        </p>
      </div>
      {error && (
        <p className="issue" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

export function BackgroundSync({
  state,
  action,
  onOpenMaterials,
}: {
  state: AppState;
  action: Action;
  onOpenMaterials: (id: string) => void;
}) {
  const background = state.background || {};
  const binding = background.binding || {};
  const sources: RecordData[] = background.sources || [];
  const jobs: RecordData[] = background.jobs || [];
  const [checking, setChecking] = useState(false);
  return (
    <div className="background-sync">
      <section className="panel background-binding">
        <div className="background-binding-heading">
          <div>
            <h2>后台同步</h2>
            <p>先检查所选本地历史，再增量更新产品资料；微信可在后台运行。</p>
          </div>
          <BackgroundBadge value={binding} />
        </div>
        <div className="background-binding-details">
          <div>
            <span>当前授权账号</span>
            <strong>{binding.account_display || "尚未绑定本机账号"}</strong>
          </div>
          <div>
            <span>唯一授权好友</span>
            <strong>{binding.friend_display || "尚未绑定本机来源"}</strong>
          </div>
          <div>
            <span>最近账号核验</span>
            <strong>
              {binding.last_verified_at
                ? dateLabel(binding.last_verified_at)
                : "尚未完成本次核验"}
            </strong>
          </div>
        </div>
        <div className="actions">
          <button
            className="button secondary"
            disabled={checking || !background.live_collection_enabled}
            onClick={async () => {
              setChecking(true);
              try {
                await action(
                  () => api("/api/background/bind", "POST", {}),
                  "账号核验已完成，请查看绑定与来源状态。",
                );
              } finally {
                setChecking(false);
              }
            }}
          >
            <Icon name="user" />
            {checking ? "正在核验账号…" : "核验当前账号"}
          </button>
        </div>
        {(binding.error || binding.reason) && (
          <p className="issue" role="status">
            {typeof binding.error === "string"
              ? binding.error
              : binding.error?.message || binding.reason}
          </p>
        )}
        <p className="small">
          仅检查上述好友的朋友圈与一对一聊天。此前群聊和其他联系人继续暂停，手动导入与已有业务引用保留。更换账号或微信重启后需重新核验。AI
          配置继续暂缓，前台微信采集保持停用。
        </p>
      </section>
      <BackgroundCapabilities capabilities={background.capabilities} />
      {sources.length ? (
        <div className="background-source-grid">
          {sources.map((source) => (
            <SourceControls
              key={source.id}
              source={source}
              capabilities={
                background.per_source?.[source.kind] ||
                background.capabilities?.per_source?.[source.kind] ||
                {}
              }
              jobs={jobs.filter((job) => job.source_id === source.id)}
              action={action}
              onOpenMaterials={onOpenMaterials}
            />
          ))}
        </div>
      ) : (
        <section className="panel">
          <Empty
            icon="chat"
            title="先核验当前账号与好友"
            text="核验通过后，这里会显示已授权的朋友圈与一对一聊天。不会自动扩大到其他来源。"
          />
        </section>
      )}
      <section className="panel background-jobs">
        <div className="background-binding-heading">
          <div>
            <h2>处理任务与覆盖</h2>
            <p>首次历史、增量更新、补充历史与附件恢复分别保留处理进度。</p>
          </div>
          <span className="count-label">{jobs.length} 项任务</span>
        </div>
        {jobs.length ? (
          jobs.map((job) => (
            <BackgroundJob
              key={job.id}
              job={job}
              source={sources.find((source) => source.id === job.source_id)}
              action={action}
            />
          ))
        ) : (
          <Empty
            icon="clock"
            title="尚未创建后台任务"
            text="账号核验后，可分别启动朋友圈和聊天的首次检查与自动更新。"
          />
        )}
      </section>
    </div>
  );
}

export function PendingCandidates({
  state,
  action,
}: {
  state: AppState;
  action: Action;
}) {
  const [pending, setPending] = useState<RecordData | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    api("/api/background/candidates")
      .then((result) => {
        if (current) {
          setPending(result);
          setError("");
        }
      })
      .catch(() => {
        if (current) setError("暂时无法取得候选状态，请刷新后重试。");
      });
    return () => {
      current = false;
    };
  }, [state.background]);
  const items: RecordData[] = Array.isArray(pending)
    ? pending
    : pending?.items || [];
  const summary = Array.isArray(pending)
    ? state.background?.pending_summary || {}
    : pending?.summary || {};
  const candidates = items.filter(
    (item) =>
      (item.disposition || item.outcome || "PENDING_RELEVANCE") ===
      "PENDING_RELEVANCE",
  );
  return (
    <section className="panel pending-candidates">
      <SectionHead
        title="待识别"
        subtitle="这里只显示可能与旅游产品有关、目前证据不足的候选。无需逐条批准已经明确相关或无关的内容。"
      />
      {error && (
        <p className="issue" role="status">
          {error}
        </p>
      )}
      <div className="pending-summary">
        <p>
          待识别候选：
          {metric(summary.pending ?? (pending ? candidates.length : undefined))}
        </p>
        <p>
          内容暂未取得：{metric(summary.acquisition_failed)}
          。缺少图片、格式无法读取或暂时取回失败，都不等于内容无关。
        </p>
        {typeof summary.expired === "number" && summary.expired > 0 && (
          <p>
            已有 {metric(summary.expired)}{" "}
            项超过暂存期限，未判定为无关；后续取得新证据后仍可重新判断。
          </p>
        )}
        <p className="small">
          待识别内容不会进入普通资料列表、产品推荐或本周资料。普通问候和已确认无关的内容只保留处理结果，不在这里生成卡片。
        </p>
        <button
          className="button secondary"
          onClick={() =>
            action(async () => {
              const result = await api("/api/background/candidates");
              setPending(result);
              setError("");
              return result;
            }, "处理状态已刷新。")
          }
        >
          刷新状态
        </button>
      </div>
      {candidates.length ? (
        <div className="pending-list">
          {candidates.map((candidate) => (
            <article className="pending-candidate" key={candidate.id}>
              <div className="background-job-heading">
                <strong>{candidate.title || "待识别的产品资料候选"}</strong>
                <Badge value="PENDING_RELEVANCE" />
              </div>
              <p>
                {state.sources.find(
                  (source) => source.id === candidate.source_id,
                )?.display_name || "已授权来源"}
                {" · "}
                {candidate.publication_time
                  ? dateLabel(candidate.publication_time)
                  : "原文时间待核对"}
              </p>
              <p>
                {candidate.reason_label ||
                  (
                    {
                      CONFLICTING_TRUSTED_CLASSIFICATIONS:
                        "已有判断依据存在分歧，需要新的相关证据。",
                      EXPLICIT_UNCERTAIN_CLASSIFICATION:
                        "已有判断明确保留为待确认，后续自动规则不会擅自覆盖。",
                      TRUSTED_INSPECTION_UNCERTAIN:
                        "已核读的资料仍无法确定用途。",
                      MEDIA_INSPECTION_REQUIRED:
                        "需要检查图片或文件中的产品信息。",
                      INSPECTION_EVENT_MISMATCH:
                        "现有图片判断尚未与这条内容准确对应。",
                      INSPECTION_REVISION_MISMATCH:
                        "内容已有改动，需要重新核对图片依据。",
                      MEDIA_RELEVANCE_UNRESOLVED:
                        "图片或文件已进入识别流程，用途仍待确认。",
                      INSUFFICIENT_PRODUCT_DETAILS:
                        "目前缺少足够的旅游产品细节。",
                    } as Record<string, string>
                  )[candidate.reason_code] ||
                  "现有文字或图片证据还不足以判断是否包含旅游产品信息。"}
              </p>
              <p className="small">
                {candidate.imported
                  ? "导入的待识别记录，已停用自动重试与到期清理。"
                  : candidate.expires_at
                  ? `暂存至 ${dateLabel(candidate.expires_at)}`
                  : "按有限期限暂存，期限届满不等于确认无关。"}
                {candidate.next_retry_at
                  ? ` · 下次尝试 ${dateLabel(candidate.next_retry_at)}`
                  : ""}
              </p>
              {candidate.attachments?.some((attachment: RecordData) => attachment.url) && (
                <details>
                  <summary>查看已保存附件（按原顺序）</summary>
                  {candidate.attachments.map((attachment: RecordData) => attachment.url && (
                    <div key={attachment.index}>
                      {String(attachment.mime).startsWith("image/") && (
                        <img src={`${attachment.url}?preview=true`} alt={`候选附件 ${attachment.index + 1}`}
                          loading="lazy" style={{ maxWidth: "100%", maxHeight: 360, objectFit: "contain" }} />
                      )}
                      <p><a href={attachment.url} target="_blank" rel="noreferrer">{attachment.index + 1}. {attachment.name}</a></p>
                    </div>
                  ))}
                </details>
              )}
              {(candidate.text || candidate.excerpt) && (
                <details>
                  <summary>查看候选文字</summary>
                  <pre className="source-text">
                    {candidate.excerpt || candidate.text}
                  </pre>
                </details>
              )}
            </article>
          ))}
        </div>
      ) : (
        <Empty
          icon="check"
          title={pending ? "目前没有需要识别的候选" : "尚无候选处理状态"}
          text="已确认的产品资料会直接保留。取回失败在上方汇总，普通聊天和已跳过内容不会占用这份列表。"
        />
      )}
    </section>
  );
}
