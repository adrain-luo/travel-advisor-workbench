export type RecordData = Record<string, any>;
export type AppState = {
  settings: RecordData;
  capabilities: RecordData;
  accounts: RecordData[];
  sources: RecordData[];
  jobs: RecordData[];
  native_sessions: RecordData[];
  page_observations: RecordData[];
  materials: RecordData[];
  products: RecordData[];
  cases: RecordData[];
  recommendations: RecordData[];
  weekly: RecordData[];
  background: RecordData;
};
export const emptyState: AppState = {
  settings: { timezone: "Asia/Shanghai", provider: {} },
  capabilities: {},
  accounts: [],
  sources: [],
  jobs: [],
  native_sessions: [],
  page_observations: [],
  materials: [],
  products: [],
  cases: [],
  recommendations: [],
  weekly: [],
  background: {
    binding: {},
    capabilities: {},
    sources: [],
    jobs: [],
    summary: {},
  },
};
export async function api(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<any> {
  const isForm = body instanceof FormData;
  const response = await fetch(path, {
    method,
    headers:
      body && !isForm ? { "Content-Type": "application/json" } : undefined,
    body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
  });
  const data = await response
    .json()
    .catch(() => ({ detail: "服务暂时没有返回有效数据，请检查本地服务。" }));
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "操作未完成，请检查输入内容后重试。",
    );
  return data;
}
export const statusLabels: Record<string, string> = {
  QUEUED: "等待处理",
  RUNNING: "正在采集微信",
  PAUSING: "正在暂停",
  PAUSED: "已暂停",
  NEEDS_USER_ACTION: "需要操作",
  COMPATIBILITY_BLOCKED: "技术适配受阻",
  BACKGROUND_UNVERIFIED: "后台采集兼容性核验中",
  FOREGROUND_COLLECTION_DISABLED: "前台微信采集已停用",
  STAGED: "等待本轮来源确认",
  ESTABLISHING: "正在校验当前页面",
  EXPIRED: "本轮来源绑定已失效",
  UNPARSED: "页面观察 · 尚未解析为记录",
  OPERATOR_POSITIONED: "人工定位后自动采集",
  COMPLETED: "处理结束",
  PARTIAL: "部分完成",
  FAILED: "处理失败",
  CANCELED: "已取消",
  PASS: "已验证",
  BLOCKED: "受阻",
  NOT_TESTED: "尚未验证",
  UNKNOWN: "尚不明确",
  REQUESTED_BOUNDARY_REACHED: "已到达请求时间边界",
  ACCESSIBLE_END_REACHED: "已到达可访问终点",
  STALLED_UNPROVEN_END: "停止遍历，终点尚未证实",
  PARTIAL_WITH_GAPS: "有遗漏，等待补全",
  PENDING: "等待处理",
  PENDING_AI: "等待配置 AI",
  NEEDS_AI: "需要 AI 识别",
  EXTRACTED: "已提取文字",
  UNSUPPORTED: "暂不支持分析",
  READY: "已就绪",
  STORED: "原件已保存",
  RETRY: "等待重试",
  PREVIEW: "预览图",
  SCREENSHOT: "截图",
  UI_SCREENSHOT: "界面截图",
  CLIENT_SAVED: "微信客户端保存（原件质量未验证）",
  ORIGINAL: "原件",
  UPLOADED: "已导入",
  NOT_CONFIGURED: "未配置",
  PENDING_EXTRACTION: "等待提取",
  ANALYZING: "正在分析",
  NEEDS_CONFIGURATION: "等待配置 AI",
  NEEDS_VISION: "需要图像识别",
  ANALYZED: "已分析",
  SAVED: "已保存",
  SUCCESS: "已完成",
  PREPARED: "已准备",
  NEEDS_REVIEW: "需要核对",
  NEEDS_MANUAL: "需要人工整理",
  NEEDS_SPLIT: "需要拆分素材",
  INVALID_RESPONSE: "返回格式不正确",
  RETRYABLE_ERROR: "可重试错误",
  PARTIAL_NEEDS_VISION: "部分内容需图像识别",
  RULES_ONLY: "仅规则提取",
  AI_PARSED: "AI 已解析",
  TEXT_EXTRACTED: "已提取文字",
  WAITING: "等待下次同步",
  SCHEDULED: "等待下次同步",
  IDLE: "等待下次同步",
  BACKOFF: "稍后重试",
  RETRY_WAIT: "等待重试",
  INVALIDATED: "账号状态已变化，需重新核验",
  UNBOUND: "尚未核验账号",
  BOUND: "账号已核验",
  VERIFIED: "已验证",
  IMPLEMENTED_UNVERIFIED: "已实现，待真实新增验证",
  AWAITING_SAMPLE: "等待真实样本",
  LOCAL_EXHAUSTED: "本地记录已读取，完整性未知",
  LOCAL_SNAPSHOT_EXHAUSTED: "本地快照已读取，完整性未知",
  UNKNOWN_CDN_RENDITION: "已取得图片，原件质量未验证",
  THUMBNAIL: "缩略图",
  REFERENCE_DISCOVERED: "已发现附件引用",
  BYTES_PENDING: "等待取回文件",
  BYTES_SAVED: "文件已保存",
  VALIDATED: "文件已校验",
  UNAVAILABLE: "暂时无法取回",
  COMPLETED_LOCAL: "本地遍历完成，完整性未知",
  UNKNOWN_CACHED_RENDITION: "本地缓存图片，原件质量未验证",
  UNKNOWN_CACHED_TRANSCODED: "本地缓存转码图片，原件质量未验证",
  HASH_VERIFIED_FILE: "已核对文件内容",
  RETRY_PENDING: "待重试取回",
  INITIAL_HISTORY_PENDING: "等待首次历史检查",
  INITIAL_HISTORY_RUNNING: "正在检查首次历史",
  INITIAL_LOCAL_HISTORY_PROCESSED: "首次本地历史已处理",
  INCREMENTAL_ACTIVE: "增量更新已开启",
  KEEP_PRODUCT_RELEVANT: "已保留为产品资料",
  SKIP_IRRELEVANT: "已跳过无关内容",
  PENDING_RELEVANCE: "待识别",
  RETRY_ACQUISITION: "等待取得内容",
};
export function label(value: unknown): string {
  return value == null
    ? "待确认"
    : statusLabels[String(value).toUpperCase()] || String(value);
}
export function display(value: unknown): string {
  if (value == null || value === "") return "待确认";
  if (Array.isArray(value)) return value.map(display).join("；");
  if (typeof value === "object")
    return Object.entries(value as RecordData)
      .map(([k, v]) => `${k}：${display(v)}`)
      .join("；");
  return String(value);
}
let businessTimezone = "Asia/Shanghai";
export function setDateTimezone(value: string) {
  try {
    new Intl.DateTimeFormat("zh-CN", { timeZone: value });
    businessTimezone = value;
  } catch {
    businessTimezone = "Asia/Shanghai";
  }
}
export function dateLabel(value: unknown): string {
  if (!value) return "时间未知";
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(value))) return String(value);
  const d = new Date(String(value));
  return Number.isNaN(d.getTime())
    ? String(value)
    : d.toLocaleString("zh-CN", { timeZone: businessTimezone, hour12: false });
}
export function price(offer: RecordData | undefined): string {
  if (!offer || offer.price == null) return "价格待确认";
  const currency =
    offer.currency === "CNY"
      ? "¥"
      : offer.currency
        ? `${offer.currency} `
        : "币种待确认 ";
  const amount = Number(offer.price).toLocaleString("zh-CN");
  const priceRange =
    offer.price_kind === "range"
      ? `–${offer.price_max == null ? "上限待确认" : Number(offer.price_max).toLocaleString("zh-CN")}`
      : "";
  const qualifier =
    offer.price_kind === "from"
      ? " 起"
      : offer.price_kind == null
        ? "（价格性质待确认）"
        : "";
  const unit =
    ({ per_person: "人", per_party: "组", per_room: "间房" } as RecordData)[
      offer.unit
    ] || "计价单位待确认";
  return `${currency}${amount}${priceRange}${qualifier} / ${unit}`;
}
export const fieldLabels: Record<string, string> = {
  destination: "目的地",
  departure_city: "出发城市",
  date_start: "最早出发",
  date_end: "最晚出发",
  budget: "预算上限",
  budget_max: "预算上限",
  budget_unit: "预算口径",
  duration_days: "行程天数",
  shopping: "购物要求",
  adults: "成人",
  children: "儿童",
  currency: "币种",
  traveler: "旅客类别",
  occupancy: "入住条件",
  transport_included: "大交通是否包含",
  hotels: "酒店要求",
  hotel_preferences: "酒店偏好",
  pace: "行程节奏",
  exclusions: "明确排除项",
  preferences: "客户偏好",
  hard_constraints: "硬性条件",
  questions: "待补充问题",
  transport: "交通",
  extras: "附加费用",
  price: "报价",
  availability: "余位",
  other: "其他",
  text: "文字",
  vision: "图像",
  structured: "结构化输出",
  embeddings: "向量能力",
  status: "状态",
  message: "说明",
  reason: "原因",
  issues: "待处理问题",
  name: "名称",
  amount: "金额",
  required: "是否必付",
  state: "状态",
  unit: "计价口径",
  known: "已知",
  unknown: "未知",
  zero: "明确为零",
  not_applicable: "不适用",
  files: "文件",
  history: "历史遍历",
  selected_contact_history: "指定联系人历史",
  original_media: "原始附件",
  account_verification: "账号校验",
  source_verification: "来源校验",
  multi_page: "多页遍历",
  resume: "恢复采集",
  timestamps: "时间证据",
  download: "下载",
  group: "微信群",
  moments: "朋友圈",
  chat: "一对一聊天",
  upload: "用户上传",
};
const valueLabels: Record<string, string> = {
  none: "无购物",
  included: "含购物",
  optional: "可选购物",
  any: "无特别限制",
  adult: "成人",
  child: "儿童",
  senior: "老人",
  all: "所有旅客",
  per_person: "每人",
  per_party: "每组",
  per_room: "每间房",
  exact: "具体报价",
  from: "起价",
  range: "价格区间",
  known: "已知",
  unknown: "未知",
  zero: "明确为零",
  not_applicable: "不适用",
  CNY: "人民币",
  RULES_ONLY: "仅规则提取",
  AI_PARSED: "AI 已解析",
  NEEDS_MANUAL: "需要人工整理",
  INVALID_RESPONSE: "返回格式不正确",
  RETRYABLE_ERROR: "可重试错误",
  NEEDS_CONFIGURATION: "等待配置 AI",
  NOT_CONFIGURED: "未配置",
  PARTIAL: "部分可用",
  NOT_TESTED: "尚未验证",
  PASS: "已验证",
  BLOCKED: "受阻",
};
export function humanValue(value: unknown): string {
  if (value === true) return "是";
  if (value === false) return "否";
  if (value == null || value === "") return "未明确";
  if (Array.isArray(value))
    return value.length ? value.map(humanValue).join("；") : "未填写";
  if (typeof value === "object")
    return Object.entries(value as RecordData)
      .map(([k, v]) => `${fieldLabels[k] || "信息"}：${humanValue(v)}`)
      .join("；");
  return (
    valueLabels[String(value)] ||
    fieldLabels[String(value)] ||
    statusLabels[String(value)] ||
    String(value)
  );
}
