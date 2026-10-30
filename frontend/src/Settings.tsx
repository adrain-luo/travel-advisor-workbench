import { useEffect, useState } from "react";
import type { AppState, RecordData } from "./api";
import { api, display, label, humanValue } from "./api";
import type { Action } from "./App";
import { Badge, Field, Icon, SectionHead } from "./ui";
import { BackgroundCapabilities } from "./BackgroundSync";

export function Settings({
  state,
  action,
}: {
  state: AppState;
  action: Action;
}) {
  const [settings, setSettings] = useState<RecordData>(state.settings);
  const [key, setKey] = useState("");
  const [dirty, setDirty] = useState(false);
  const [check, setCheck] = useState<RecordData | null>(
    state.settings.provider?.verified_capabilities || null,
  );
  const [backup, setBackup] = useState("");
  const [restorePath, setRestorePath] = useState("");
  const [restored, setRestored] = useState<RecordData | null>(null);
  useEffect(() => {
    if (!dirty) setSettings(state.settings);
  }, [state.settings, dirty]);
  const set = (k: string, v: unknown) => {
    setDirty(true);
    setSettings({ ...settings, [k]: v });
  };
  const provider = (k: string, v: unknown) =>
    set("provider", { ...settings.provider, [k]: v });
  const save = async () => {
    const r = await api("/api/settings", "PUT", {
      timezone: settings.timezone,
      provider: settings.provider,
      ...(key ? { api_key: key } : {}),
    });
    setKey("");
    setDirty(false);
    setSettings(r);
    return r;
  };
  return (
    <div className="settings-grid">
      <section className="panel full-width">
        <SectionHead
          title="后台同步能力"
          subtitle="朋友圈与一对一聊天的后台能力独立于旧前台采集。具体来源状态与任务入口位于“素材中心 → 后台同步”。"
        />
        <BackgroundCapabilities capabilities={state.background?.capabilities} />
      </section>
      <section className="panel full-width">
        <SectionHead
          title="旧前台采集与手动上传"
          subtitle="以下为实际适配器报告；文档描述与测试样本不等同于已在当前客户端验证。"
        />
        <div className="capability-grid">
          {[
            ["group", "微信群历史", "chat"],
            ["moments", "联系人朋友圈历史", "image"],
            ["upload", "用户上传", "upload"],
          ].map(([kind, title, icon]) => {
            const c = state.capabilities[kind] || {};
            return (
              <article className="capability" key={kind}>
                <div className="capability-title">
                  <span className="source-icon">
                    <Icon name={icon} size={23} />
                  </span>
                  <h3>{title}</h3>
                  <Badge value={c.status || "NOT_TESTED"} />
                </div>
                <p>
                  {c.reason ||
                    c.limitation ||
                    c.message ||
                    "尚未取得当前环境的能力证据。"}
                </p>
                {Object.entries(c)
                  .filter(
                    ([k]) =>
                      ![
                        "status",
                        "available",
                        "reason",
                        "limitation",
                        "message",
                        "code",
                        "kind",
                        "requires_foreground",
                      ].includes(k),
                  )
                  .map(([k, v]) => (
                    <div className="capability-detail" key={k}>
                      <span>
                        {(
                          {
                            adapter: "适配器",
                            client_version: "客户端版本",
                            account: "账号",
                            selected_contact_history: "指定联系人历史",
                            history: "历史遍历",
                            attachments: "附件",
                            resume: "断点恢复",
                            evidence: "观察证据",
                            license: "许可",
                            next_action: "下一步",
                            text: "文字",
                            images: "图片",
                            documents: "文档",
                            group_history: "群历史",
                            moments_history: "朋友圈历史",
                            version: "版本",
                            features: "功能状态",
                            adapter_version: "适配器版本",
                            platform: "运行平台",
                            enrolled: "来源校验配置",
                            metadata: "环境信息",
                          } as RecordData
                        )[k] || "状态详情"}
                      </span>
                      <span>
                        {typeof v === "boolean"
                          ? v
                            ? "可用"
                            : "未验证"
                          : humanValue(v)}
                      </span>
                    </div>
                  ))}
              </article>
            );
          })}
        </div>
        <div className="settings-note">
          <Icon name="alert" />
          <p>
            旧前台微信采集保持暂停；上方后台能力独立报告。当前只授权指定好友的朋友圈和一对一聊天，无需打开指定页面或交接桌面。已保存资料与上传功能可继续使用。
          </p>
        </div>
        <div className="settings-account">
          <h3>已绑定的账号</h3>
          {state.accounts.length ? (
            state.accounts.map((a) => (
              <div className="account-row" key={a.id}>
                <span className="avatar">微</span>
                <div>
                  <strong>{a.display_name}</strong>
                  <small>{display(a.identity_evidence)}</small>
                </div>
                <Badge value={a.verification_status || "NOT_TESTED"} />
              </div>
            ))
          ) : (
            <p className="muted">
              暂无绑定账号。请在“素材中心 → 添加微信来源”中选择。
            </p>
          )}
        </div>
      </section>
      <section className="panel">
        <SectionHead
          title="AI 服务"
          subtitle="配置后可解析产品与客户需求；原始资料和手动操作不依赖 AI。"
        />
        <div className="settings-body">
          <Field label="服务协议">
            <select
              value={settings.provider?.protocol || "openai_compatible"}
              onChange={(e) => provider("protocol", e.target.value)}
            >
              <option value="openai_compatible">OpenAI 兼容接口</option>
            </select>
          </Field>
          <Field label="服务地址">
            <input
              value={settings.provider?.base_url || ""}
              onChange={(e) => provider("base_url", e.target.value)}
              placeholder="https://您的服务地址/v1"
              spellCheck={false}
            />
          </Field>
          <div className="form-grid">
            <Field label="文本模型">
              <input
                value={settings.provider?.model || ""}
                onChange={(e) => provider("model", e.target.value)}
                placeholder="供应商提供的模型标识"
              />
            </Field>
            <Field label="图像模型（可选）">
              <input
                value={settings.provider?.vision_model || ""}
                onChange={(e) => provider("vision_model", e.target.value)}
                placeholder="支持图像输入的模型"
              />
            </Field>
          </div>
          <Field
            label={
              state.settings.has_api_key
                ? "API 密钥（已保存，留空保留）"
                : "API 密钥"
            }
            hint="仅发送至本机后端保存，不写入浏览器缓存或导出资料。"
          >
            <input
              type="password"
              value={key}
              autoComplete="new-password"
              onChange={(e) => setKey(e.target.value)}
              placeholder={
                state.settings.has_api_key
                  ? "已保存 · 输入新值可替换"
                  : "输入服务密钥"
              }
            />
          </Field>
          <div className="form-grid">
            <Field label="请求超时（秒）">
              <input
                type="number"
                min="5"
                max="120"
                value={settings.provider?.timeout || 30}
                onChange={(e) => provider("timeout", Number(e.target.value))}
              />
            </Field>
            <Field label="并行分析数">
              <select
                value={settings.provider?.max_concurrency || 2}
                onChange={(e) =>
                  provider("max_concurrency", Number(e.target.value))
                }
              >
                <option value={1}>1</option>
                <option value={2}>2</option>
              </select>
            </Field>
          </div>
          <div className="actions">
            <button
              className="button primary"
              onClick={() => action(save, "AI 设置已保存。")}
            >
              <Icon name="save" />
              保存设置
            </button>
            <button
              className="button secondary"
              onClick={() =>
                action(async () => {
                  await save();
                  const r = await api("/api/provider/check", "POST");
                  setCheck(r);
                  return r;
                }, "能力检测已返回，请查看每项结果。")
              }
            >
              <Icon name="refresh" />
              检测连接与能力
            </button>
          </div>
          {check && Object.keys(check).length > 0 && (
            <div className="provider-results">
              {Object.entries(check).map(([k, v]) => (
                <div key={k}>
                  <strong>
                    {(
                      {
                        text: "文本",
                        vision: "图像",
                        image: "图像",
                        structured: "结构化输出",
                        structured_output: "结构化输出",
                        status: "状态",
                        issues: "待处理问题",
                        usage: "用量",
                        model: "模型",
                        embeddings: "向量能力",
                      } as RecordData
                    )[k] || k}
                  </strong>
                  <span>{humanValue(v)}</span>
                </div>
              ))}
            </div>
          )}
          <p className="small">
            能力检测会调用您配置的服务，使用小型已知测试输入。未支持的图像或结构化功能会明确保留为不可用。
          </p>
        </div>
      </section>
      <div className="settings-stack">
        <section className="panel">
          <SectionHead title="本地数据与时间" />
          <div className="settings-body">
            <Field label="业务时区">
              <select
                value={settings.timezone || "Asia/Shanghai"}
                onChange={(e) => set("timezone", e.target.value)}
              >
                <option value="Asia/Shanghai">
                  中国标准时间 · Asia/Shanghai
                </option>
                <option value="Asia/Hong_Kong">
                  香港时间 · Asia/Hong_Kong
                </option>
                <option value="UTC">协调世界时 · UTC</option>
              </select>
            </Field>
            <button
              className="button secondary"
              onClick={() => action(save, "时区设置已保存。")}
            >
              保存时区
            </button>
            <div className="data-path">
              <span>当前数据目录</span>
              <code>{state.settings.data_dir || "等待本地服务返回"}</code>
            </div>
            <p className="small">
              原始附件、数据库、检查点和导出资料保存在此目录。更换目录需通过启动配置完成。
            </p>
          </div>
        </section>
        <section className="panel">
          <SectionHead
            title="备份与恢复验证"
            subtitle="备份包含数据库与关联文件，不含 AI 密钥。"
          />
          <div className="settings-body">
            <button
              className="button secondary full"
              onClick={() =>
                action(async () => {
                  const r = await api("/api/backup", "POST");
                  setBackup(r.path);
                  setRestorePath(r.path);
                  return r;
                }, "一致性备份已保存。")
              }
            >
              <Icon name="download" />
              创建本地备份
            </button>
            {backup && (
              <div className="data-path">
                <span>最近创建的备份</span>
                <code>{backup}</code>
              </div>
            )}
            <div className="divider" />
            <Field label="备份文件路径">
              <input
                value={restorePath}
                onChange={(e) => setRestorePath(e.target.value)}
                placeholder="粘贴本机备份文件的完整路径"
              />
            </Field>
            <button
              className="button secondary full"
              disabled={!restorePath.trim()}
              onClick={() =>
                action(async () => {
                  const r = await api("/api/restore", "POST", {
                    path: restorePath,
                  });
                  setRestored(r);
                  return r;
                }, "备份已恢复到独立验证目录，当前资料库未被替换。")
              }
            >
              <Icon name="refresh" />
              恢复到独立目录并验证
            </button>
            <p className="small">
              先在独立目录核对文件与业务记录。当前资料库保持可用，恢复后需要重新配置密钥。
            </p>
            {restored && (
              <div className="info-box">
                <Icon name="check" />
                <div>
                  {Object.entries(restored).map(([k, v]) => (
                    <p key={k}>
                      {(
                        {
                          path: "恢复目录",
                          directory: "恢复目录",
                          restored_to: "恢复目录",
                          verified: "校验结果",
                          message: "说明",
                          files: "文件",
                          records: "记录",
                        } as RecordData
                      )[k] || k}
                      ：{display(v)}
                    </p>
                  ))}
                </div>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
