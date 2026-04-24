import type { ImageModel } from "@/lib/api";

export const IMAGE_ASPECT_RATIO_OPTIONS = [
  { label: "方形", ratio: "1:1", width: 1, height: 1 },
  { label: "横屏", ratio: "5:4", width: 5, height: 4 },
  { label: "故事", ratio: "9:16", width: 9, height: 16 },
  { label: "超宽屏", ratio: "21:9", width: 21, height: 9 },
  { label: "宽屏", ratio: "16:9", width: 16, height: 9 },
  { label: "横屏", ratio: "4:3", width: 4, height: 3 },
  { label: "宽幅", ratio: "3:2", width: 3, height: 2 },
  { label: "标准", ratio: "4:5", width: 4, height: 5 },
  { label: "竖版", ratio: "3:4", width: 3, height: 4 },
  { label: "竖版", ratio: "2:3", width: 2, height: 3 },
] as const;

export type ImageAspectRatio = (typeof IMAGE_ASPECT_RATIO_OPTIONS)[number]["ratio"];
export type ImageOutputQuality = "original" | "2k" | "4k";

export const IMAGE_MODEL_OPTIONS = [
  {
    value: "gpt-image-2",
    label: "gpt-image-2",
    description: "标准清晰图片生成，适合大多数文生图与图生图场景。",
  },
  {
    value: "gpt-image-think",
    label: "gpt-image-think",
    description: "思考模式，会先整理复杂意图，再生成更稳定的画面。",
  },
  {
    value: "gpt-image-1",
    label: "gpt-image-1",
    description: "兼容基础图片模型，适合保守测试与简单出图。",
  },
] as const satisfies ReadonlyArray<{
  value: ImageModel;
  label: string;
  description: string;
}>;

export const IMAGE_OUTPUT_QUALITY_OPTIONS = [
  { value: "original", label: "原图" },
  { value: "2k", label: "2K 高清" },
  { value: "4k", label: "4K 高清" },
] as const satisfies ReadonlyArray<{
  value: ImageOutputQuality;
  label: string;
}>;

export const IMAGE_PROMPT_EXAMPLES = [
  "一只金色胖柴犬穿西装坐在办公桌前，油画质感",
  "赛博朋克城市夜景，霓虹雨夜，电影感光影",
  "极简几何海报，蓝橙配色，主体是一只展翅的鹤",
  "童话风格蘑菇屋，黄昏光线，柔和景深",
] as const;

const ASPECT_RATIO_PREFIX_RE = /^\s*Make the aspect ratio\s+\S+\s*,\s*/i;

export function applyAspectRatioPrompt(prompt: string, aspectRatio?: ImageAspectRatio) {
  const normalizedPrompt = String(prompt || "").trim();
  if (!aspectRatio) {
    return normalizedPrompt;
  }

  const prefix = `Make the aspect ratio ${aspectRatio} , `;
  if (!normalizedPrompt) {
    return prefix.trim();
  }

  const lines = normalizedPrompt.split(/\r?\n/);
  if (lines.length > 0 && ASPECT_RATIO_PREFIX_RE.test(lines[0])) {
    lines[0] = lines[0].replace(ASPECT_RATIO_PREFIX_RE, prefix);
    return lines.join("\n");
  }
  return `${prefix}${normalizedPrompt}`;
}

export function getAspectRatioPreviewStyle(width: number, height: number) {
  const maxSize = 36;
  const ratio = width / height;
  const previewWidth = ratio >= 1 ? maxSize : Math.round(maxSize * ratio);
  const previewHeight = ratio >= 1 ? Math.round(maxSize / ratio) : maxSize;
  return {
    width: `${previewWidth}px`,
    height: `${previewHeight}px`,
  };
}

export function getImageModelDescription(model: ImageModel) {
  return IMAGE_MODEL_OPTIONS.find((option) => option.value === model)?.description ?? "";
}

export function getImageOutputQualityLabel(value: ImageOutputQuality | undefined) {
  return IMAGE_OUTPUT_QUALITY_OPTIONS.find((option) => option.value === value)?.label ?? "原图";
}

export function isImageOutputQuality(value: unknown): value is ImageOutputQuality {
  return IMAGE_OUTPUT_QUALITY_OPTIONS.some((option) => option.value === value);
}

export function isImageAspectRatio(value: unknown): value is ImageAspectRatio {
  return IMAGE_ASPECT_RATIO_OPTIONS.some((option) => option.ratio === value);
}
