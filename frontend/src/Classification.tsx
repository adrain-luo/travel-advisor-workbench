import { useEffect, useState } from "react";
import { api, dateLabel } from "./api";
import type { RecordData } from "./api";
import type { Action } from "./App";
import { Badge, Field } from "./ui";

const postLabels: Record<string, string> = {
  travel_promotion: "旅游推广",
  travel_sharing: "旅行资讯 / 分享",
  other: "其他",
  uncertain: "待确认",
};
const mediaLabels: Record<string, string> = {
  travel_flyer: "旅游产品海报",
  itinerary_quote: "行程 / 报价单",
  scenic_personal: "风景 / 生活照片",
  screenshot: "截图",
  other: "其他",
  uncertain: "待确认",
};
const originLabels: Record<string, string> = {
  manual: "人工更正",
  user: "人工更正",
  human: "人工判断",
  manual_review: "人工核读",
  visual_review: "图像核读",
  inspection: "本次图像核读",
  rules: "本地规则",
  rule: "本地规则",
  local_rules: "本地规则",
  text_rules: "原文规则",
  local_ocr: "本地文字识别",
  ocr: "文字识别",
  uncertain: "待补充依据",
  default: "尚无判断依据",
};

export function classificationLabel(record: RecordData, kind = "materials") {
  const labels = kind === "materials" ? postLabels : mediaLabels;
  const value =
    typeof record.classification === "string"
      ? record.classification
      : record.classification?.label;
  return (
    labels[value || record.classification_label || "uncertain"] || "待确认"
  );
}

function evidenceText(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value))
    return value.map(evidenceText).filter(Boolean).join("；");
  if (value && typeof value === "object") {
    const evidence = value as RecordData;
    return String(
      evidence.text ||
        evidence.reason ||
        evidence.quote ||
        evidence.description ||
        "",
    );
  }
  return "";
}

export function ClassificationEditor({
  record,
  kind,
  action,
  onChanged,
}: {
  record: RecordData;
  kind: "materials" | "attachments";
  action: Action;
  onChanged?: () => Promise<void>;
}) {
  const labels = kind === "materials" ? postLabels : mediaLabels;
  const classification =
    typeof record.classification === "object"
      ? record.classification || {}
      : { label: record.classification };
  const [editing, setEditing] = useState(false);
  const [selection, setSelection] = useState(
    classification.label || "uncertain",
  );
  const [evidence, setEvidence] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!editing)
      setSelection(
        labels[classification.label] ? classification.label : "uncertain",
      );
  }, [classification.label, editing, labels]);
  const existingEvidence = evidenceText(classification.evidence);
  return (
    <section className="classification-card">
      <div className="classification-heading">
        <strong>{kind === "materials" ? "内容用途" : "附件类型"}</strong>
        <Badge
          value={classificationLabel(record, kind)}
          tone={
            classification.label === "uncertain" || !classification.label
              ? "amber"
              : "neutral"
          }
        />
        {!editing && (
          <button
            className="text-button"
            onClick={() => {
              setEvidence(existingEvidence);
              setEditing(true);
            }}
          >
            更正分类
          </button>
        )}
      </div>
      <p className="classification-evidence">
        {existingEvidence || "尚无充分依据，暂保留为待确认；不影响资料保存。"}
      </p>
      <p className="small">
        判断来源：
        {originLabels[classification.origin] ||
          (classification.origin ? "已有分类记录" : "尚无分类")}
        {classification.updated_at
          ? ` · ${dateLabel(classification.updated_at)}`
          : ""}
      </p>
      {editing && (
        <div className="classification-form">
          <Field label={kind === "materials" ? "内容用途更正" : "附件类型更正"}>
            <select
              value={selection}
              onChange={(e) => setSelection(e.target.value)}
            >
              {Object.entries(labels).map(([key, text]) => (
                <option key={key} value={key}>
                  {text}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="简短依据"
            hint="对照原文、图片或文档填写；不确定时可选择“待确认”。"
          >
            <textarea
              value={evidence}
              onChange={(e) => setEvidence(e.target.value)}
              rows={2}
              maxLength={1000}
              placeholder="例如：图片展示团期和线路安排，可识别为旅游产品海报。"
            />
          </Field>
          <div className="actions">
            <button
              className="button primary"
              disabled={busy || !evidence.trim()}
              onClick={async () => {
                setBusy(true);
                try {
                  const result = await action(async () => {
                    const updated = await api(
                      `/api/classifications/${kind}/${encodeURIComponent(record.id)}`,
                      "POST",
                      { label: selection, evidence: evidence.trim() },
                    );
                    await onChanged?.();
                    return updated;
                  }, "人工分类已保存，后续同步会保留此更正。");
                  if (result) setEditing(false);
                } finally {
                  setBusy(false);
                }
              }}
            >
              保存更正
            </button>
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setEditing(false)}
            >
              取消
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
