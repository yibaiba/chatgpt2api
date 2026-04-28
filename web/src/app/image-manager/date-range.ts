"use client";

export type ConversationDatePreset = "all" | "today" | "7d" | "30d" | "90d" | "custom";

export const DATE_PRESET_OPTIONS: ReadonlyArray<{
  value: Exclude<ConversationDatePreset, "custom">;
  label: string;
}> = [
  { value: "all", label: "全部时间" },
  { value: "today", label: "今天" },
  { value: "7d", label: "近 7 天" },
  { value: "30d", label: "近 30 天" },
  { value: "90d", label: "近 90 天" },
];

const SHANGHAI_DATE_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const DAY_MS = 24 * 60 * 60 * 1000;

function toValidDate(value: string | Date | null | undefined) {
  if (!value) {
    return null;
  }
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatShanghaiDateKey(value: string | Date | null | undefined) {
  const date = toValidDate(value);
  if (!date) {
    return "";
  }
  const parts = SHANGHAI_DATE_FORMATTER.formatToParts(date).reduce<Record<string, string>>((accumulator, part) => {
    if (part.type !== "literal") {
      accumulator[part.type] = part.value;
    }
    return accumulator;
  }, {});
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export function buildPresetDateRange(preset: Exclude<ConversationDatePreset, "custom">) {
  if (preset === "all") {
    return { start: "", end: "" };
  }
  const end = formatShanghaiDateKey(new Date());
  if (preset === "today") {
    return { start: end, end };
  }
  const offsetDays = preset === "7d" ? 6 : preset === "30d" ? 29 : 89;
  return {
    start: formatShanghaiDateKey(new Date(Date.now() - offsetDays * DAY_MS)),
    end,
  };
}

export function isDateRangeInvalid(start: string, end: string) {
  return Boolean(start && end && start > end);
}

export function matchesDateRange(dateKey: string, start: string, end: string) {
  if (!dateKey || isDateRangeInvalid(start, end)) {
    return false;
  }
  if (start && dateKey < start) {
    return false;
  }
  if (end && dateKey > end) {
    return false;
  }
  return true;
}

export function describeDateRange(preset: ConversationDatePreset, start: string, end: string) {
  if (isDateRangeInvalid(start, end)) {
    return "时间范围无效";
  }
  if (preset === "all" && !start && !end) {
    return "全部时间";
  }
  if (preset === "today") {
    return "今天";
  }
  if (preset === "7d") {
    return "近 7 天";
  }
  if (preset === "30d") {
    return "近 30 天";
  }
  if (preset === "90d") {
    return "近 90 天";
  }
  if (start && end) {
    return `${start} 至 ${end}`;
  }
  if (start) {
    return `${start} 之后`;
  }
  if (end) {
    return `${end} 之前`;
  }
  return "自定义";
}
