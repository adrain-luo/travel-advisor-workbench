import { useState } from "react";
import type { AppState, RecordData } from "./api";
import { api, dateLabel, display, price, fieldLabels, humanValue } from "./api";
import type { Action } from "./App";
import { Badge, Empty, Field, Icon, Modal, SectionHead, useSaved } from "./ui";

const initialRequirements = {
  destination: "",
  departure_city: "",
  date_start: "",
  date_end: "",
  duration_days: null,
  budget_max: null,
  budget_unit: "per_person",
  adults: null,
  children: null,
  shopping: null,
  transport_included: null,
  hotel_preferences: "",
  pace: "",
  exclusions: "",
  preferences: "",
  hard_constraints: [
    "destination",
    "departure_city",
    "date_start",
    "date_end",
    "duration_days",
    "budget_max",
    "shopping",
    "transport_included",
  ],
};
function nullableNumber(value: string) {
  return value === "" ? null : Number(value);
}
function shopping(value: unknown) {
  return value === "none"
    ? "无购物"
    : value === "included"
      ? "含购物安排"
      : value === "optional"
        ? "可选购物"
        : "购物安排待确认";
}
function normalizedRequirements(value: RecordData) {
  const split = (v: unknown) =>
    Array.isArray(v)
      ? v
      : typeof v === "string"
        ? v
            .split(/[；;\n]/)
            .map((s) => s.trim())
            .filter(Boolean)
        : [];
  return {
    ...value,
    budget: value.budget_max ?? value.budget ?? null,
    currency: value.currency || "CNY",
    hotels: value.hotel_preferences || value.hotels || null,
    exclusions: split(value.exclusions),
    preferences: split(value.preferences),
    hard_constraints: (value.hard_constraints || []).filter(
      (k: string) =>
        value[k] !== null && value[k] !== undefined && value[k] !== "",
    ),
  };
}
function travelerLabel(value: unknown) {
  return (
    (
      {
        adult: "成人",
        child: "儿童",
        senior: "老人",
        all: "所有旅客",
      } as RecordData
    )[String(value)] || display(value)
  );
}
function extraText(value: unknown) {
  if (value == null) return "额外费用待确认";
  if (Array.isArray(value))
    return value.length
      ? value
          .map(
            (e) =>
              `${e.name || "附加费用"}：${e.state === "not_applicable" ? "不适用" : e.amount == null ? "金额待确认" : `¥${e.amount}`}（${e.required === true ? "必付" : e.required === false ? "可选" : "是否必付待确认"}）`,
          )
          .join("；")
      : "已明确无必付附加费用";
  return display(value);
}

export function Workbench({
  state,
  action,
  onProduct,
}: {
  state: AppState;
  action: Action;
  onProduct: (p: RecordData) => void;
}) {
  const [requestText, setRequestText] = useSaved("request-text", "");
  const [requirements, setRequirements] = useSaved<RecordData>(
    "requirements",
    initialRequirements,
  );
  const [name, setName] = useSaved("customer-name", "");
  const [caseId, setCaseId] = useSaved<string | null>("active-case", null);
  const [selected, setSelected] = useSaved<string[]>("compare-products", []);
  const [matches, setMatches] = useState<RecordData | null>(null);
  const [text, setText] = useSaved("recommendation-draft", "");
  const [recommendationId, setRecommendationId] = useSaved<string | null>(
    "recommendation-id",
    null,
  );
  const [exported, setExported] = useState<RecordData | null>(null);
  const [draftBasis, setDraftBasis] = useSaved("recommendation-basis", "");
  const [inquiry, setInquiry] = useState<RecordData | null>(null);
  const [showAll, setShowAll] = useState(false);
  const picked: RecordData[] = state.products
    .filter((p) => selected.includes(p.id))
    .map((p) => {
      const e = [
        ...(matches?.matched || []),
        ...(matches?.needs_verification || []),
      ].find((e) => e.product?.id === p.id);
      return {
        ...p,
        applicable_offer: e?.applicable_offer || null,
        match_issues: e?.issues || [],
      };
    });
  const basis = JSON.stringify({
    requirements: normalizedRequirements(requirements),
    selected: state.products
      .filter((p) => selected.includes(p.id))
      .map((p) => [p.id, p.version]),
  });
  const draftStale = Boolean(text && draftBasis !== basis);
  const changed = (key: string, value: unknown) => {
    setRequirements({
      ...requirements,
      [key]: value,
      ...(key === "budget_max" ? { budget: value } : {}),
      ...(key === "hotel_preferences" ? { hotels: value } : {}),
    });
    setMatches(null);
    setRecommendationId(null);
    setExported(null);
  };
  const toggle = (id: string) => {
    setSelected(
      selected.includes(id)
        ? selected.filter((x) => x !== id)
        : [...selected, id],
    );
    setRecommendationId(null);
    setExported(null);
  };
  const saveCase = async () => {
    const r = await api("/api/cases", "POST", {
      id: caseId,
      name: name || "未命名接待",
      request_text: requestText,
      requirements: normalizedRequirements(requirements),
    });
    setCaseId(r.id);
    return r;
  };
  const prepare = async () => {
    const savedCase = await saveCase();
    const r = await api("/api/recommendations", "POST", {
      case_id: savedCase.id,
      product_ids: picked.map((p) => p.id),
      requirements: normalizedRequirements(requirements),
      ...(text ? { text } : {}),
    });
    setText(r.text || text);
    setDraftBasis(basis);
    setRecommendationId(r.id);
    return r;
  };
  const generateDraft = async () => {
    const savedCase = await saveCase();
    const r = await api("/api/recommendations", "POST", {
      case_id: savedCase.id,
      product_ids: picked.map((p) => p.id),
      requirements: normalizedRequirements(requirements),
    });
    setText(r.text || "");
    setDraftBasis(basis);
    setRecommendationId(r.id);
    setExported(null);
    return r;
  };
  const saveText = async () => {
    if (!recommendationId) return prepare();
    const r = await api(`/api/recommendations/${recommendationId}`, "PUT", {
      text,
    });
    setRecommendationId(r.id || recommendationId);
    return r;
  };
  const groups = matches
    ? [
        {
          title: "符合已填写条件",
          items: matches.matched || [],
          tone: "green",
        },
        {
          title: "待供应商确认",
          items: matches.needs_verification || [],
          tone: "amber",
        },
      ]
    : [
        {
          title: "产品库",
          items: state.products.map((p) => ({
            product: p,
            reasons: [],
            issues: [],
          })),
          tone: "neutral",
        },
      ];
  return (
    <>
      <div className="workbench-layout">
        <section className="panel requirements-panel">
          <SectionHead title="客户需求" subtitle="先明确不能妥协的条件" />
          <div className="requirements-body">
            <Field label="客户 / 接待名称">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="为本次接待起个名字"
              />
            </Field>
            <Field label="客户怎么说">
              <textarea
                rows={5}
                value={requestText}
                onChange={(e) => setRequestText(e.target.value)}
                placeholder="粘贴客户消息，例如：两位成人，想从上海去云南，11 月出发，6 天左右，不安排购物。"
              />
            </Field>
            <button
              className="button secondary full"
              disabled={!requestText.trim()}
              onClick={() =>
                action(async () => {
                  const result = await api("/api/parse-requirements", "POST", {
                    text: requestText,
                  });
                  const r = result.requirements || result;
                  setRequirements({
                    ...initialRequirements,
                    ...r,
                    budget_max: r.budget ?? r.budget_max ?? null,
                    hotel_preferences: r.hotels ?? r.hotel_preferences ?? "",
                    hard_constraints: (r.hard_constraints || []).map(
                      (k: string) =>
                        k === "budget"
                          ? "budget_max"
                          : k === "hotels"
                            ? "hotel_preferences"
                            : k,
                    ),
                  });
                  setMatches(null);
                  return result;
                }, "需求解析已返回，请核对下方条件；未识别的信息需要手动补充。")
              }
            >
              <Icon name="spark" />
              解析为可编辑条件
            </button>
            <p className="small">
              {requirements.status
                ? humanValue(requirements.status)
                : "AI 未配置时只做明确的规则提取，不会当作完整理解。"}
            </p>
            {(requirements.issues || []).map((issue: any, i: number) => (
              <p className="issue" key={i}>
                {display(issue)}
              </p>
            ))}
            <div className="divider" />
            <div className="form-grid">
              <Field label="目的地">
                <input
                  value={requirements.destination || ""}
                  onChange={(e) => changed("destination", e.target.value)}
                />
              </Field>
              <Field label="出发城市">
                <input
                  value={requirements.departure_city || ""}
                  onChange={(e) => changed("departure_city", e.target.value)}
                />
              </Field>
              <Field label="最早出发">
                <input
                  type="date"
                  value={requirements.date_start || ""}
                  onChange={(e) => changed("date_start", e.target.value)}
                />
              </Field>
              <Field label="最晚出发">
                <input
                  type="date"
                  value={requirements.date_end || ""}
                  onChange={(e) => changed("date_end", e.target.value)}
                />
              </Field>
              <Field label="行程天数">
                <input
                  type="number"
                  min="1"
                  value={requirements.duration_days ?? ""}
                  onChange={(e) =>
                    changed("duration_days", nullableNumber(e.target.value))
                  }
                />
              </Field>
              <Field
                label={
                  requirements.currency && requirements.currency !== "CNY"
                    ? `预算上限（${requirements.currency}）`
                    : "预算上限（元）"
                }
              >
                <input
                  type="number"
                  min="0"
                  value={requirements.budget_max ?? ""}
                  onChange={(e) =>
                    changed("budget_max", nullableNumber(e.target.value))
                  }
                />
              </Field>
              <Field label="预算口径">
                <select
                  value={requirements.budget_unit || "per_person"}
                  onChange={(e) => changed("budget_unit", e.target.value)}
                >
                  <option value="per_person">每人</option>
                  <option value="per_party">同行总额</option>
                </select>
              </Field>
              <Field label="购物要求">
                <select
                  value={requirements.shopping || ""}
                  onChange={(e) => changed("shopping", e.target.value || null)}
                >
                  <option value="">未明确</option>
                  <option value="none">不安排购物</option>
                  <option value="any">无特别限制</option>
                </select>
              </Field>
              <Field label="成人">
                <input
                  type="number"
                  min="0"
                  value={requirements.adults ?? ""}
                  onChange={(e) =>
                    changed("adults", nullableNumber(e.target.value))
                  }
                />
              </Field>
              <Field label="儿童">
                <input
                  type="number"
                  min="0"
                  value={requirements.children ?? ""}
                  onChange={(e) =>
                    changed("children", nullableNumber(e.target.value))
                  }
                />
              </Field>
            </div>
            <Field label="大交通要求">
              <select
                value={
                  requirements.transport_included == null
                    ? ""
                    : String(requirements.transport_included)
                }
                onChange={(e) =>
                  changed(
                    "transport_included",
                    e.target.value === "" ? null : e.target.value === "true",
                  )
                }
              >
                <option value="">未明确</option>
                <option value="true">报价必须包含大交通</option>
                <option value="false">自理大交通</option>
              </select>
            </Field>
            <Field label="酒店偏好">
              <input
                value={requirements.hotel_preferences || ""}
                onChange={(e) => changed("hotel_preferences", e.target.value)}
                placeholder="例如：市区酒店、舒适型"
              />
            </Field>
            <Field label="节奏与偏好">
              <input
                value={
                  Array.isArray(requirements.preferences)
                    ? requirements.preferences.join("；")
                    : requirements.preferences || ""
                }
                onChange={(e) => changed("preferences", e.target.value)}
                placeholder="例如：少换酒店、老人友好"
              />
            </Field>
            <Field label="其他明确排除项">
              <input
                value={
                  Array.isArray(requirements.exclusions)
                    ? requirements.exclusions.join("；")
                    : requirements.exclusions || ""
                }
                onChange={(e) => changed("exclusions", e.target.value)}
                placeholder="例如：不乘坐夜间长途车"
              />
            </Field>
            <details className="hard-constraints">
              <summary>不能妥协的条件</summary>
              <p className="small">
                勾选为硬性条件。无法证实满足的产品归入“待确认”，不会算作已满足。
              </p>
              {[
                ["destination", "目的地"],
                ["departure_city", "出发城市"],
                ["date_start", "出发日期下限"],
                ["date_end", "出发日期上限"],
                ["duration_days", "天数"],
                ["budget_max", "预算"],
                ["shopping", "购物要求"],
                ["transport_included", "大交通"],
              ].map(([key, title]) => (
                <label key={key}>
                  <input
                    type="checkbox"
                    checked={(requirements.hard_constraints || []).includes(
                      key,
                    )}
                    onChange={(e) =>
                      changed(
                        "hard_constraints",
                        e.target.checked
                          ? [...(requirements.hard_constraints || []), key]
                          : (requirements.hard_constraints || []).filter(
                              (x: string) => x !== key,
                            ),
                      )
                    }
                  />
                  {title}
                </label>
              ))}
            </details>
            <button
              className="button primary full"
              onClick={() =>
                action(async () => {
                  const r = await api("/api/match", "POST", {
                    requirements: normalizedRequirements(requirements),
                  });
                  setMatches(r);
                  return r;
                })
              }
            >
              <Icon name="search" />
              查找合适产品
            </button>
            <button
              className="button ghost full"
              onClick={() => action(saveCase, "客户需求已保存到接待记录。")}
            >
              <Icon name="save" />
              保存本次接待
            </button>
          </div>
        </section>
        <div className="shortlist-column">
          <section className="panel">
            <SectionHead
              title={matches ? "候选方案" : "先从产品库开始"}
              subtitle={
                matches
                  ? "先核对适用条件，再看偏好与取舍"
                  : "填写左侧需求，开始有依据的比较"
              }
            >
              <span className="count-label">已选 {picked.length} 个</span>
            </SectionHead>
            {matches?.questions?.length > 0 && (
              <div className="inline-questions">
                <Icon name="chat" />
                <div>
                  {matches?.questions?.slice(0, 2).map((q: any, i: number) => (
                    <p key={i}>{display(q)}</p>
                  ))}
                </div>
              </div>
            )}
            {groups.every((g) => !g.items.length) ? (
              <Empty
                icon="compass"
                title={matches ? "目前没有可直接推荐的方案" : "产品库还是空的"}
                text={
                  matches
                    ? matches.next_action ||
                      "保留原有要求，补充供应商资料或确认缺失条件后再次筛选。"
                    : "先从素材中心导入资料并整理产品。也可以手动录入。"
                }
              >
                <button
                  className="button secondary"
                  onClick={() => onProduct({})}
                >
                  <Icon name="plus" />
                  手动录入产品
                </button>
              </Empty>
            ) : (
              groups.map(
                (group) =>
                  group.items.length > 0 && (
                    <div className="candidate-group" key={group.title}>
                      <div className="candidate-group-title">
                        <span
                          className={`dot ${group.tone === "green" ? "online" : group.tone === "amber" ? "warning" : ""}`}
                        />
                        {group.title}
                        <small>{group.items.length} 个</small>
                      </div>
                      {(showAll ? group.items : group.items.slice(0, 3)).map(
                        (entry: RecordData) => {
                          const p = entry.product || entry;
                          const offer =
                            entry.applicable_offer ||
                            (p.offers?.length === 1 ? p.offers[0] : null);
                          return (
                            <article
                              className={`candidate ${selected.includes(p.id) ? "picked" : ""}`}
                              key={p.id}
                            >
                              <div className="candidate-heading">
                                <div>
                                  <span className="supplier-label">
                                    {p.supplier || "供应商待确认"}
                                  </span>
                                  <h3>{p.title}</h3>
                                  <p>
                                    {p.departure_city || "出发地待确认"} →{" "}
                                    {p.destination || "目的地待确认"}{" "}
                                    <span>
                                      ·{" "}
                                      {p.duration_days
                                        ? `${p.duration_days} 天`
                                        : "天数待确认"}
                                    </span>
                                  </p>
                                </div>
                                <button
                                  className={`button ${selected.includes(p.id) ? "primary" : "secondary"}`}
                                  onClick={() => toggle(p.id)}
                                >
                                  <Icon
                                    name={
                                      selected.includes(p.id) ? "check" : "plus"
                                    }
                                    size={15}
                                  />
                                  {selected.includes(p.id)
                                    ? "已加入"
                                    : "加入比较"}
                                </button>
                              </div>
                              <div className="candidate-price">
                                <strong>{price(offer)}</strong>
                                <span>
                                  {offer?.departure_date || "适用日期待确认"} ·{" "}
                                  {travelerLabel(offer?.traveler)}
                                </span>
                              </div>
                              {entry.reasons?.length > 0 && (
                                <div className="fit-reasons">
                                  {entry.reasons.map((r: any, i: number) => (
                                    <span key={i}>
                                      <Icon name="check" size={13} />
                                      {display(r)}
                                    </span>
                                  ))}
                                </div>
                              )}
                              <div className="candidate-facts">
                                <span>{shopping(p.shopping)}</span>
                                <span>
                                  {offer?.transport_included === true
                                    ? "报价含大交通"
                                    : offer?.transport_included === false
                                      ? "大交通另计"
                                      : "大交通待确认"}
                                </span>
                                <span>
                                  {p.hotels ? display(p.hotels) : "酒店待确认"}
                                </span>
                              </div>
                              {entry.issues?.length > 0 && (
                                <p className="issue">
                                  需核实：{entry.issues.map(display).join("；")}
                                </p>
                              )}
                              <div className="candidate-footer">
                                <span>
                                  {p.source_item_ids?.length || 0} 份来源 ·
                                  更新于{" "}
                                  {dateLabel(p.updated_at || p.created_at)}
                                </span>
                                <div>
                                  <button
                                    className="text-button"
                                    onClick={() => onProduct(p)}
                                  >
                                    查看依据
                                  </button>
                                  <button
                                    className="text-button"
                                    onClick={() =>
                                      setInquiry({
                                        product: p,
                                        text: `您好，请帮忙确认“${p.title}”${offer?.departure_date ? ` ${offer.departure_date} 出发` : "指定出发日期"}，${requirements.adults ?? "待定"} 位成人、${requirements.children ?? "待定"} 位儿童的方案：\n1. ${entry.issues?.length ? entry.issues.map(display).join("；") : "实际适用报价、余位与确认有效时间"}\n2. 费用包含、必选自费及购物安排\n3. 酒店、房型和大交通条件\n请说明以上答复对应的日期、旅客类别与房间安排。`,
                                      })
                                    }
                                  >
                                    供应商询问
                                  </button>
                                </div>
                              </div>
                            </article>
                          );
                        },
                      )}
                    </div>
                  ),
              )
            )}
            {groups.some((g) => g.items.length > 3) && (
              <button
                className="button ghost full"
                onClick={() => setShowAll(!showAll)}
              >
                {showAll ? "收起更多结果" : "查看全部候选"}
              </button>
            )}
            {matches?.excluded?.length > 0 && (
              <details className="excluded">
                <summary>
                  {matches?.excluded?.length} 个产品与硬性条件不符
                </summary>
                {matches?.excluded?.map((e: RecordData) => (
                  <p key={e.product?.id}>
                    <strong>{e.product?.title}</strong>：
                    {(e.exclusions || e.reasons || e.issues || [])
                      .map(display)
                      .join("；")}
                  </p>
                ))}
              </details>
            )}
          </section>
          {picked.length > 0 && (
            <section className="panel compare-panel">
              <SectionHead
                title="方案并排比较"
                subtitle="未知不等于没有，起价不等于适用报价。"
              />
              <div className="comparison-scroll">
                <table className="comparison-table">
                  <thead>
                    <tr>
                      <th>比较项目</th>
                      {picked.map((p) => (
                        <th key={p.id}>
                          {p.title}
                          <button
                            className="icon-button"
                            aria-label={`移除 ${p.title}`}
                            onClick={() => toggle(p.id)}
                          >
                            <Icon name="close" size={13} />
                          </button>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ["供应商", (p: RecordData) => p.supplier],
                      [
                        "日期 / 行程",
                        (p: RecordData) =>
                          `${p.applicable_offer?.departure_date || "日期待确认"} · ${p.duration_days ? `${p.duration_days} 天` : "天数待确认"}`,
                      ],
                      [
                        "价格与口径",
                        (p: RecordData) => price(p.applicable_offer),
                      ],
                      [
                        "报价适用说明",
                        (p: RecordData) => p.applicable_offer?.conditions,
                      ],
                      [
                        "旅客 / 入住",
                        (p: RecordData) =>
                          `${travelerLabel(p.applicable_offer?.traveler)} · ${p.applicable_offer?.occupancy || "入住条件待确认"}`,
                      ],
                      [
                        "额外费用",
                        (p: RecordData) =>
                          extraText(p.applicable_offer?.extras),
                      ],
                      [
                        "交通",
                        (p: RecordData) =>
                          `${p.applicable_offer?.transport_included === true ? "报价已含大交通" : p.applicable_offer?.transport_included === false ? "报价不含大交通" : "大交通是否包含待确认"}${p.transport ? `；${p.transport}` : ""}`,
                      ],
                      ["酒店", (p: RecordData) => p.hotels],
                      ["购物", (p: RecordData) => shopping(p.shopping)],
                      ["顾问判断", (p: RecordData) => p.notes],
                      [
                        "报价确认时间",
                        (p: RecordData) =>
                          p.applicable_offer?.confirmed_at
                            ? dateLabel(p.applicable_offer.confirmed_at)
                            : "尚未确认",
                      ],
                    ].map(([title, read]) => (
                      <tr key={String(title)}>
                        <th>{String(title)}</th>
                        {picked.map((p) => (
                          <td key={p.id}>
                            {display((read as (p: RecordData) => unknown)(p))}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      </div>
      {picked.length > 0 && (
        <section className="panel customer-preview">
          <SectionHead
            title="给客户的介绍"
            subtitle="可以先形成初步建议；保留重要条件与未知项。"
          >
            <button
              className="button secondary"
              onClick={() =>
                action(
                  generateDraft,
                  "推荐草稿已按适用报价生成，请核对并编辑。",
                )
              }
            >
              <Icon name="spark" />
              生成介绍草稿
            </button>
          </SectionHead>
          {draftStale && (
            <div className="warning-box draft-warning">
              <Icon name="alert" />
              <p>
                当前需求、所选产品或产品版本与草稿来源不同。请重新生成介绍，或按新条件编辑并核对后继续。
              </p>
              <button
                className="button secondary"
                onClick={() => {
                  setDraftBasis(basis);
                  setRecommendationId(null);
                }}
              >
                已按当前条件核对文字
              </button>
            </div>
          )}
          <div className="customer-preview-body">
            <textarea
              rows={12}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setExported(null);
              }}
              placeholder="生成介绍草稿或直接输入您的建议。准备输出时会保存对应的需求与产品版本。"
            />
            <div className="preview-sidebar">
              <h3>准备这次推荐</h3>
              <p>
                已选 {picked.length}{" "}
                个方案。输出会保存本次需求、适用报价和产品快照。
              </p>
              <button
                className="button primary full"
                disabled={!text.trim() || draftStale}
                onClick={() =>
                  action(async () => {
                    await saveText();
                    await navigator.clipboard.writeText(text);
                    return true;
                  }, "推荐版本已保存，介绍已复制。未自动发送。")
                }
              >
                <Icon name="copy" />
                复制介绍
              </button>
              <button
                className="button secondary full"
                disabled={!text.trim() || draftStale}
                onClick={() =>
                  action(async () => {
                    const saved = await saveText();
                    const r = await api(
                      `/api/recommendations/${saved.id || recommendationId}/export`,
                      "POST",
                    );
                    setExported(r);
                    return r;
                  }, "对比图已生成，请核对后保存。")
                }
              >
                <Icon name="image" />
                生成对比图
              </button>
              <button
                className="button ghost full"
                disabled={draftStale}
                onClick={() => action(prepare, "推荐版本已保存。")}
              >
                <Icon name="save" />
                保存推荐版本
              </button>
              {exported && (
                <div className="export-links">
                  {exported.image_url && (
                    <a
                      className="button primary full"
                      href={exported.image_url}
                      download
                    >
                      <Icon name="download" />
                      保存图片
                    </a>
                  )}
                  {exported.text_url && (
                    <a
                      className="button secondary full"
                      href={exported.text_url}
                      download
                    >
                      下载介绍文字
                    </a>
                  )}
                </div>
              )}
              <p className="small">
                复制、下载都不会自动发送给客户。之前准备的版本会持续保留。
              </p>
            </div>
          </div>
          {exported?.image_url && (
            <div className="export-preview">
              <img src={exported.image_url} alt="本次推荐的中文对比图预览" />
            </div>
          )}
        </section>
      )}
      {inquiry && (
        <Modal
          title="供应商询问草稿"
          subtitle={`${inquiry.product.supplier || "供应商待确认"} · ${inquiry.product.title}`}
          onClose={() => setInquiry(null)}
        >
          <div className="modal-body">
            <textarea
              className="full"
              rows={11}
              value={inquiry.text}
              onChange={(e) => setInquiry({ ...inquiry, text: e.target.value })}
            />
            <p className="small">
              询问仅供复制。收到答复后，在产品详情中逐项记录适用条件和确认依据。
            </p>
          </div>
          <div className="modal-footer">
            <button
              className="button secondary"
              onClick={() => {
                onProduct(inquiry.product);
                setInquiry(null);
              }}
            >
              记录供应商确认
            </button>
            <button
              className="button primary"
              onClick={() =>
                action(async () => {
                  await navigator.clipboard.writeText(inquiry.text);
                  return true;
                }, "询问已复制，未自动发送。")
              }
            >
              <Icon name="copy" />
              复制询问
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

const newOffer = () => ({
  price: null,
  price_kind: "exact",
  currency: "CNY",
  unit: "per_person",
  traveler: null,
  occupancy: null,
  departure_date: null,
  valid_from: null,
  valid_to: null,
  extras: null,
  transport_included: null,
  availability: null,
  confirmed_at: null,
});
export function ProductEditor({
  product,
  materials,
  action,
  onClose,
}: {
  product: RecordData;
  materials: RecordData[];
  action: Action;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<RecordData>({
    title: "",
    supplier: "",
    destination: "",
    departure_city: "",
    duration_days: null,
    shopping: null,
    transport: null,
    hotels: null,
    itinerary: null,
    notes: null,
    source_item_ids: [],
    offers: [],
    ...product,
  });
  const [tab, setTab] = useState("facts");
  const [confirm, setConfirm] = useState<RecordData>({
    field: "shopping",
    value: "",
    scope: "",
    evidence: "",
    confirmed_by: "",
  });
  const update = (k: string, v: unknown) => setDraft({ ...draft, [k]: v });
  const editOffer = (i: number, key: string, value: unknown) =>
    setDraft({
      ...draft,
      offers: draft.offers.map((o: RecordData, n: number) =>
        n === i ? { ...o, [key]: value } : o,
      ),
    });
  return (
    <Modal
      title={draft.id ? "产品详情与修订" : "手动整理产品"}
      subtitle="保留来源事实、人工修订与供应商确认。未知内容请留空。"
      onClose={onClose}
      wide
    >
      <div className="tab-row modal-tabs">
        <button
          className={tab === "facts" ? "selected" : ""}
          onClick={() => setTab("facts")}
        >
          产品与报价
        </button>
        <button
          className={tab === "sources" ? "selected" : ""}
          onClick={() => setTab("sources")}
        >
          来源依据
        </button>
        <button
          className={tab === "confirm" ? "selected" : ""}
          onClick={() => setTab("confirm")}
        >
          供应商确认
        </button>
      </div>
      <div className="modal-body">
        {tab === "facts" && (
          <>
            <div className="form-grid">
              <Field label="产品名称">
                <input
                  value={draft.title || ""}
                  onChange={(e) => update("title", e.target.value)}
                />
              </Field>
              <Field label="实际供应商">
                <input
                  value={draft.supplier || ""}
                  onChange={(e) => update("supplier", e.target.value)}
                  placeholder="不默认等于转发人或群名称"
                />
              </Field>
              <Field label="目的地">
                <input
                  value={draft.destination || ""}
                  onChange={(e) => update("destination", e.target.value)}
                />
              </Field>
              <Field label="出发城市">
                <input
                  value={draft.departure_city || ""}
                  onChange={(e) => update("departure_city", e.target.value)}
                />
              </Field>
              <Field label="行程天数">
                <input
                  type="number"
                  min="1"
                  value={draft.duration_days ?? ""}
                  onChange={(e) =>
                    update("duration_days", nullableNumber(e.target.value))
                  }
                />
              </Field>
              <Field label="购物安排">
                <select
                  value={draft.shopping || ""}
                  onChange={(e) => update("shopping", e.target.value || null)}
                >
                  <option value="">未知 / 待确认</option>
                  <option value="none">明确无购物</option>
                  <option value="included">含购物安排</option>
                  <option value="optional">可选购物</option>
                </select>
              </Field>
              <Field label="交通说明">
                <input
                  value={
                    typeof draft.transport === "string" ? draft.transport : ""
                  }
                  onChange={(e) => update("transport", e.target.value || null)}
                />
              </Field>
              <Field label="酒店说明">
                <input
                  value={
                    typeof draft.hotels === "string"
                      ? draft.hotels
                      : display(draft.hotels) === "待确认"
                        ? ""
                        : display(draft.hotels)
                  }
                  onChange={(e) => update("hotels", e.target.value || null)}
                />
              </Field>
            </div>
            <Field label="行程摘要">
              <textarea
                rows={4}
                value={
                  typeof draft.itinerary === "string"
                    ? draft.itinerary
                    : display(draft.itinerary) === "待确认"
                      ? ""
                      : display(draft.itinerary)
                }
                onChange={(e) => update("itinerary", e.target.value || null)}
              />
            </Field>
            <Field label="顾问判断 / 适合人群 / 主要取舍">
              <textarea
                rows={2}
                value={draft.notes || ""}
                onChange={(e) => update("notes", e.target.value || null)}
                placeholder="这属于顾问判断，不会标记成供应商已确认事实。"
              />
            </Field>
            <div className="divider" />
            <SectionHead
              title="报价与适用条件"
              subtitle="不同日期、旅客类别和套餐分别记录，未知费用留空。"
            >
              <button
                className="button secondary"
                onClick={() =>
                  update("offers", [...(draft.offers || []), newOffer()])
                }
              >
                <Icon name="plus" />
                新增报价
              </button>
            </SectionHead>
            {!(draft.offers || []).length && (
              <p className="muted">
                暂无报价，产品仍可保存。不要用 0 代表未知价格。
              </p>
            )}
            {(draft.offers || []).map((o: RecordData, i: number) => (
              <div className="offer-editor" key={i}>
                <div className="section-head">
                  <h3>报价 {i + 1}</h3>
                  <button
                    className="text-button danger-text"
                    onClick={() =>
                      update(
                        "offers",
                        draft.offers.filter((_: unknown, n: number) => n !== i),
                      )
                    }
                  >
                    移除此报价
                  </button>
                </div>
                <div className="form-grid three">
                  <Field label="金额">
                    <input
                      type="number"
                      min="0"
                      value={o.price ?? ""}
                      onChange={(e) =>
                        editOffer(i, "price", nullableNumber(e.target.value))
                      }
                    />
                  </Field>
                  <Field label="价格性质">
                    <select
                      value={o.price_kind || ""}
                      onChange={(e) =>
                        editOffer(i, "price_kind", e.target.value || null)
                      }
                    >
                      <option value="">待确认</option>
                      <option value="exact">具体报价（需核实适用条件）</option>
                      <option value="from">起价</option>
                      <option value="range">价格区间</option>
                    </select>
                  </Field>
                  <Field label="币种">
                    <input
                      value={o.currency || ""}
                      placeholder="币种待确认"
                      onChange={(e) =>
                        editOffer(i, "currency", e.target.value || null)
                      }
                    />
                  </Field>
                  <Field label="计价口径">
                    <select
                      value={o.unit || ""}
                      onChange={(e) =>
                        editOffer(i, "unit", e.target.value || null)
                      }
                    >
                      <option value="">待确认</option>
                      <option value="per_person">每人</option>
                      <option value="per_party">每组</option>
                      <option value="per_room">每间房</option>
                    </select>
                  </Field>
                  <Field label="旅客类别">
                    <select
                      value={o.traveler || ""}
                      onChange={(e) =>
                        editOffer(i, "traveler", e.target.value || null)
                      }
                    >
                      <option value="">待确认</option>
                      <option value="adult">成人</option>
                      <option value="child">儿童</option>
                      <option value="senior">老人</option>
                      <option value="all">所有旅客</option>
                    </select>
                  </Field>
                  <Field label="入住条件">
                    <input
                      value={o.occupancy || ""}
                      onChange={(e) =>
                        editOffer(i, "occupancy", e.target.value || null)
                      }
                      placeholder="例如双人间，2 人入住"
                    />
                  </Field>
                  <Field
                    label="具体出发日"
                    hint="年份不明时留空，在下方保留原文说明。"
                  >
                    <input
                      type="date"
                      value={o.departure_date || ""}
                      onChange={(e) =>
                        editOffer(i, "departure_date", e.target.value || null)
                      }
                    />
                  </Field>
                  <Field label="有效期开始">
                    <input
                      type="date"
                      value={o.valid_from || ""}
                      onChange={(e) =>
                        editOffer(i, "valid_from", e.target.value || null)
                      }
                    />
                  </Field>
                  <Field label="有效期结束">
                    <input
                      type="date"
                      value={o.valid_to || ""}
                      onChange={(e) =>
                        editOffer(i, "valid_to", e.target.value || null)
                      }
                    />
                  </Field>
                  <Field label="大交通是否包含">
                    <select
                      value={
                        o.transport_included == null
                          ? ""
                          : String(o.transport_included)
                      }
                      onChange={(e) =>
                        editOffer(
                          i,
                          "transport_included",
                          e.target.value === ""
                            ? null
                            : e.target.value === "true",
                        )
                      }
                    >
                      <option value="">待确认</option>
                      <option value="true">包含</option>
                      <option value="false">不含</option>
                    </select>
                  </Field>
                  <Field label="余位 / 可售说明">
                    <input
                      value={o.availability || ""}
                      onChange={(e) =>
                        editOffer(i, "availability", e.target.value || null)
                      }
                    />
                  </Field>
                  {o.price_kind === "range" && (
                    <Field label="区间上限">
                      <input
                        type="number"
                        min="0"
                        value={o.price_max ?? ""}
                        onChange={(e) =>
                          editOffer(
                            i,
                            "price_max",
                            nullableNumber(e.target.value),
                          )
                        }
                      />
                    </Field>
                  )}
                </div>
                <Field
                  label="团期与适用条件原文"
                  hint="例如“11 月每周六出发，年份未注明”。不将缺失年份自动补为本年。"
                >
                  <textarea
                    rows={3}
                    value={o.conditions || ""}
                    onChange={(e) =>
                      editOffer(i, "conditions", e.target.value || null)
                    }
                  />
                </Field>
                <OfferExtras
                  value={o.extras}
                  unit={o.unit}
                  currency={o.currency}
                  onChange={(v) => editOffer(i, "extras", v)}
                />
              </div>
            ))}
          </>
        )}
        {tab === "sources" && (
          <>
            <p className="muted">
              关联支持这一产品的原始资料。不会因为同名或图片相同而自动合并供应商。
            </p>
            {materials.length ? (
              <div className="weekly-products">
                {materials.map((m) => (
                  <label key={m.id}>
                    <input
                      type="checkbox"
                      checked={(draft.source_item_ids || []).includes(m.id)}
                      onChange={(e) =>
                        update(
                          "source_item_ids",
                          e.target.checked
                            ? [...(draft.source_item_ids || []), m.id]
                            : (draft.source_item_ids || []).filter(
                                (id: string) => id !== m.id,
                              ),
                        )
                      }
                    />
                    <span>
                      <strong>
                        {m.title ||
                          m.filename ||
                          m.text?.slice(0, 70) ||
                          "原始素材"}
                      </strong>
                      <small>
                        {m.supplier || "供应商未标注"} ·{" "}
                        {m.source_time_raw || "发布时间未知"}
                      </small>
                    </span>
                  </label>
                ))}
              </div>
            ) : (
              <p>尚无可关联素材，可先保存人工录入记录。</p>
            )}
            {draft.evidence && (
              <div className="inset-panel">
                <h3>已提取证据</h3>
                <div>
                  {draft.evidence.map((e: RecordData, i: number) => (
                    <p key={i}>
                      {fieldLabels[e.field] || "产品信息"} ·{" "}
                      {e.location || "原文"}：{e.quote || "请查看对应图片位置"}
                    </p>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
        {tab === "confirm" && (
          <>
            <div className="info-box">
              <Icon name="check" />
              <p>
                仅确认具体字段和适用范围。新采集资料不会刷新旧报价的确认时间，也不会一次确认所有事实。
              </p>
            </div>
            {!draft.id ? (
              <p>请先保存产品，再记录供应商答复。</p>
            ) : (
              <>
                <div className="form-grid">
                  <Field label="确认字段">
                    <select
                      value={confirm.field}
                      onChange={(e) =>
                        setConfirm({ ...confirm, field: e.target.value })
                      }
                    >
                      <option value="shopping">购物安排</option>
                      <option value="price">具体报价</option>
                      <option value="availability">余位</option>
                      <option value="transport">交通</option>
                      <option value="hotels">酒店</option>
                      <option value="extras">额外费用</option>
                      <option value="other">其他</option>
                    </select>
                  </Field>
                  <Field label="确认人 / 供应商">
                    <input
                      value={confirm.confirmed_by}
                      onChange={(e) =>
                        setConfirm({ ...confirm, confirmed_by: e.target.value })
                      }
                    />
                  </Field>
                </div>
                <Field label="确认结果">
                  <textarea
                    rows={2}
                    value={confirm.value}
                    onChange={(e) =>
                      setConfirm({ ...confirm, value: e.target.value })
                    }
                  />
                </Field>
                <Field label="适用范围（日期、旅客、房型、报价）">
                  <input
                    value={confirm.scope}
                    onChange={(e) =>
                      setConfirm({ ...confirm, scope: e.target.value })
                    }
                  />
                </Field>
                <Field label="答复原文 / 证据位置">
                  <textarea
                    rows={4}
                    value={confirm.evidence}
                    onChange={(e) =>
                      setConfirm({ ...confirm, evidence: e.target.value })
                    }
                  />
                </Field>
                <button
                  className="button primary"
                  disabled={
                    !confirm.value ||
                    !confirm.scope ||
                    !confirm.evidence ||
                    !confirm.confirmed_by
                  }
                  onClick={() =>
                    action(
                      () =>
                        api(
                          `/api/products/${draft.id}/confirm`,
                          "POST",
                          confirm,
                        ),
                      "已保存该字段的供应商确认记录。",
                    )
                  }
                >
                  保存这项确认
                </button>
                {(draft.verifications || []).map((v: RecordData) => (
                  <div className="verification" key={v.id}>
                    <strong>
                      {fieldLabels[v.field] || "确认内容"}：
                      {humanValue(v.value)}
                    </strong>
                    <p>{v.scope}</p>
                    <p>{v.evidence}</p>
                    <small>
                      {v.confirmed_by} · {dateLabel(v.confirmed_at)}
                    </small>
                  </div>
                ))}
              </>
            )}
          </>
        )}
      </div>
      <div className="modal-footer">
        <p className="small">保存会创建修订记录，保留此前版本。</p>
        <button className="button secondary" onClick={onClose}>
          关闭
        </button>
        <button
          className="button primary"
          disabled={!draft.title?.trim()}
          onClick={() =>
            action(async () => {
              const r = await api(
                draft.id ? `/api/products/${draft.id}` : "/api/products",
                draft.id ? "PUT" : "POST",
                draft,
              );
              onClose();
              return r;
            }, "产品版本已保存。")
          }
        >
          <Icon name="save" />
          保存产品
        </button>
      </div>
    </Modal>
  );
}

function OfferExtras({
  value,
  unit,
  currency,
  onChange,
}: {
  value: RecordData[] | null;
  unit: string;
  currency: string;
  onChange: (v: RecordData[] | null) => void;
}) {
  const extras = value || [];
  const change = (i: number, k: string, v: unknown) =>
    onChange(extras.map((e, n) => (n === i ? { ...e, [k]: v } : e)));
  return (
    <div className="extra-editor">
      <Field label="附加费用状态">
        <select
          value={value == null ? "unknown" : value.length ? "items" : "none"}
          onChange={(e) =>
            onChange(
              e.target.value === "unknown"
                ? null
                : e.target.value === "none"
                  ? []
                  : [
                      {
                        name: "",
                        amount: null,
                        required: null,
                        state: "unknown",
                        unit,
                        currency,
                      },
                    ],
            )
          }
        >
          <option value="unknown">未知，尚未向供应商核实</option>
          <option value="none">已明确没有必付附加费用</option>
          <option value="items">逐项记录附加费用</option>
        </select>
      </Field>
      {extras.map((x, i) => (
        <div className="extra-row" key={i}>
          <div className="form-grid three">
            <Field label="费用名称">
              <input
                value={x.name || ""}
                onChange={(e) => change(i, "name", e.target.value)}
              />
            </Field>
            <Field label="金额（未知留空）">
              <input
                type="number"
                min="0"
                value={x.amount ?? ""}
                onChange={(e) =>
                  onChange(
                    extras.map((v, n) =>
                      n === i
                        ? {
                            ...v,
                            amount: nullableNumber(e.target.value),
                            state:
                              e.target.value === ""
                                ? "unknown"
                                : Number(e.target.value) === 0
                                  ? "zero"
                                  : "known",
                          }
                        : v,
                    ),
                  )
                }
              />
            </Field>
            <Field label="是否必须支付">
              <select
                value={x.required == null ? "" : String(x.required)}
                onChange={(e) =>
                  change(
                    i,
                    "required",
                    e.target.value === "" ? null : e.target.value === "true",
                  )
                }
              >
                <option value="">待确认</option>
                <option value="true">必付</option>
                <option value="false">可选</option>
              </select>
            </Field>
            <Field label="适用情况">
              <select
                value={x.state || "unknown"}
                onChange={(e) => change(i, "state", e.target.value)}
              >
                <option value="unknown">未知</option>
                <option value="known">已知金额</option>
                <option value="zero">明确零元</option>
                <option value="not_applicable">不适用</option>
              </select>
            </Field>
            <Field label="计价口径">
              <select
                value={x.unit || unit}
                onChange={(e) => change(i, "unit", e.target.value)}
              >
                <option value="per_person">每人</option>
                <option value="per_party">每组</option>
                <option value="per_room">每间房</option>
              </select>
            </Field>
            <Field label="币种">
              <input
                value={x.currency || currency}
                onChange={(e) => change(i, "currency", e.target.value)}
              />
            </Field>
          </div>
          <button
            className="text-button danger-text"
            onClick={() => onChange(extras.filter((_, n) => n !== i))}
          >
            移除此费用
          </button>
        </div>
      ))}
      {value != null && (
        <button
          className="text-button"
          onClick={() =>
            onChange([
              ...extras,
              {
                name: "",
                amount: null,
                required: null,
                state: "unknown",
                unit,
                currency,
              },
            ])
          }
        >
          ＋ 增加一项费用
        </button>
      )}
    </div>
  );
}
