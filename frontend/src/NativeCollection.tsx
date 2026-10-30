import { useState } from "react";
import { api, dateLabel } from "./api";
import type { AppState, RecordData } from "./api";
import type { Action } from "./App";
import { Badge, Empty, Icon, Modal, SectionHead } from "./ui";

export function NativeCollection() {
  return (
    <div className="native-collection">
      <Badge value="旧前台采集已暂停" tone="amber" />
      <p className="small">
        此处保留此前来源与前台采集记录。已授权好友的独立后台同步，请进入“后台同步”页面查看实际能力并启动任务。
      </p>
      <div className="warning-box" role="status">
        <Icon name="alert" />
        <p>
          前台页面操作与截图识别导航已暂停。无需打开群页面、联系人相册或交接桌面。素材内容的文字识别不受影响。
        </p>
      </div>
      <p className="small">
        已选来源与历史证据保留。您可以继续上传素材、整理产品、筛选方案和导出资料。
      </p>
    </div>
  );
}

export function PageObservations({
  state,
  action,
}: {
  state: AppState;
  action: Action;
}) {
  const [observation, setObservation] = useState<RecordData | null>(null);
  const [sourceFilter, setSourceFilter] = useState("");
  const observations = state.page_observations.filter(
    (item) => !sourceFilter || item.source_id === sourceFilter,
  );
  const sourceName = (item: RecordData) =>
    state.sources.find((source) => source.id === item.source_id)
      ?.display_name ||
    item.source_name ||
    "来源待核对";
  const attachmentUrl = (item: RecordData) =>
    item.url ||
    (item.state === "SAVED" && item.id ? `/api/attachments/${item.id}` : "");
  return (
    <>
      <section className="panel">
        <SectionHead
          title="页面观察"
          subtitle="应用保存的页面证据单独列出；未确定消息或帖子边界时，不计入已解析记录。"
        />
        <div className="toolbar">
          <select
            aria-label="筛选页面观察来源"
            value={sourceFilter}
            onChange={(event) => setSourceFilter(event.target.value)}
          >
            <option value="">全部微信来源</option>
            {state.sources
              .filter((source) => source.kind !== "upload")
              .map((source) => (
                <option key={source.id} value={source.id}>
                  {source.display_name}
                </option>
              ))}
          </select>
          <span className="count-label">{observations.length} 个页面观察</span>
        </div>
        {!observations.length ? (
          <Empty
            icon="image"
            title="暂无页面观察"
            text="此处保留已保存的页面证据。前台采集已暂停；页面截图不会自动变成消息或产品。"
          />
        ) : (
          <div className="job-list">
            {observations.map((item) => (
              <article className="job-card" key={item.id}>
                <div className="job-heading">
                  <div>
                    <h3>{sourceName(item)}</h3>
                    <p>
                      页面采集时间：
                      {dateLabel(item.observed_at || item.created_at)}
                    </p>
                  </div>
                  <Badge value={item.parse_state || "UNPARSED"} />
                </div>
                <div className="observation-summary">
                  <Badge value="OPERATOR_POSITIONED" tone="amber" />
                  <span className="small">
                    关联待核对：{item.unresolved_associations ?? 0}
                  </span>
                </div>
                <button
                  className="button secondary"
                  onClick={() =>
                    action(async () =>
                      setObservation(
                        await api(`/api/page-observations/${item.id}`),
                      ),
                    )
                  }
                >
                  查看页面与附件证据
                </button>
              </article>
            ))}
          </div>
        )}
      </section>
      {observation && (
        <Modal
          title="页面观察证据"
          subtitle={sourceName(observation)}
          wide
          onClose={() => setObservation(null)}
        >
          <div className="observation-detail">
            <Badge value="OPERATOR_POSITIONED" tone="amber" />
            <p className="small">
              页面采集时间：
              {dateLabel(observation.observed_at || observation.created_at)}
            </p>
            <div className="warning-box">
              <Icon name="alert" />
              <p>
                此处保存的是页面观察。未确定的消息、帖子与附件关联仍待核对；页面截图不是供应商原件。
              </p>
            </div>
            {(observation.raw_text || observation.text) && (
              <div className="observation-text">
                <h3>页面识别文字 · 尚未归属到记录</h3>
                <p>{observation.raw_text || observation.text}</p>
              </div>
            )}
            <div className="observation-attachments">
              {(observation.attachments || []).map((attachment: RecordData) => {
                const url = attachmentUrl(attachment);
                const previewUrl = attachment.id
                  ? `/api/attachments/${attachment.id}?preview=true`
                  : url;
                return (
                  <article key={attachment.id || attachment.name}>
                    <h3>
                      {attachment.role === "page_capture"
                        ? "采集页面截图"
                        : attachment.role === "supplier_media"
                          ? "客户端取回的附件"
                          : "附件证据"}
                    </h3>
                    <p className="small">{attachment.name || "已保存文件"}</p>
                    <Badge value={attachment.quality || "UNKNOWN"} />
                    {attachment.association_state && (
                      <p className="small">
                        关联状态：
                        {associationLabel(attachment.association_state)}
                      </p>
                    )}
                    {url && attachment.mime?.startsWith("image/") && (
                      <a href={url} target="_blank" rel="noreferrer">
                        <img
                          src={previewUrl}
                          alt={
                            attachment.role === "page_capture"
                              ? "应用采集的微信页面截图"
                              : "应用取回的客户端图片"
                          }
                        />
                      </a>
                    )}
                    {url ? (
                      <a href={url} target="_blank" rel="noreferrer">
                        打开保存的文件
                      </a>
                    ) : (
                      <p className="small">
                        附件尚未保存，可查看任务中的具体原因。
                      </p>
                    )}
                  </article>
                );
              })}
            </div>
            {!observation.attachments?.length && (
              <p className="small">此页面尚无可打开的附件。</p>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}

function associationLabel(value: unknown) {
  return (
    (
      {
        confirmed: "已核对",
        associated: "已关联",
        verified: "已核对",
        unresolved: "关联待核对",
        unknown: "关联待核对",
        unassociated: "尚未关联",
        page_only: "仅关联到页面",
        page_observation: "仅关联到页面观察",
        unparsed: "尚未解析",
      } as Record<string, string>
    )[String(value).toLowerCase()] || "关联待核对"
  );
}
