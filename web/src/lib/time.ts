const SHANGHAI_TIME_ZONE = "Asia/Shanghai";

type DateFormatShape = {
  includeYear: boolean;
  includeSeconds: boolean;
};

function toValidDate(value: string | Date | null | undefined) {
  if (!value) {
    return null;
  }
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatShanghaiParts(
  value: string | Date | null | undefined,
  shape: DateFormatShape,
) {
  const date = toValidDate(value);
  if (!date) {
    return null;
  }

  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: SHANGHAI_TIME_ZONE,
    hour12: false,
    year: shape.includeYear ? "numeric" : undefined,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: shape.includeSeconds ? "2-digit" : undefined,
  }).formatToParts(date);

  return parts.reduce<Record<string, string>>((accumulator, part) => {
    if (part.type !== "literal") {
      accumulator[part.type] = part.value;
    }
    return accumulator;
  }, {});
}

export function formatDateTimeInShanghai(value: string | Date | null | undefined) {
  const parts = formatShanghaiParts(value, { includeYear: true, includeSeconds: true });
  if (!parts) {
    return "";
  }
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

export function formatMonthDayTimeInShanghai(value: string | Date | null | undefined) {
  const parts = formatShanghaiParts(value, { includeYear: false, includeSeconds: false });
  if (!parts) {
    return "";
  }
  return `${parts.month}/${parts.day} ${parts.hour}:${parts.minute}`;
}
