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
export type ImageRenderQuality = "auto" | "low" | "medium" | "high";
export type ImageBackground = "auto" | "opaque";
export type ImageOutputFormat = "png" | "jpeg" | "webp";

export const DEFAULT_IMAGE_RENDER_QUALITY: ImageRenderQuality = "auto";
export const DEFAULT_IMAGE_BACKGROUND: ImageBackground = "auto";
export const DEFAULT_IMAGE_OUTPUT_FORMAT: ImageOutputFormat = "png";

export const IMAGE_MODEL_OPTIONS = [
  {
    value: "gpt-image-2",
    label: "gpt-image-2",
    description: "标准清晰图片生成，适合大多数文生图与图生图场景。",
  },
  {
    value: "codex-gpt-image-2",
    label: "codex-gpt-image-2",
    description: "官网 api ",
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
  { value: "2k", label: "2K" },
  { value: "4k", label: "4K" },
] as const satisfies ReadonlyArray<{
  value: ImageOutputQuality;
  label: string;
}>;

export const IMAGE_RENDER_QUALITY_OPTIONS = [
  { value: "auto", label: "自动" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
] as const satisfies ReadonlyArray<{
  value: ImageRenderQuality;
  label: string;
}>;

export const IMAGE_BACKGROUND_OPTIONS = [
  { value: "auto", label: "自动" },
  { value: "opaque", label: "不透明" },
] as const satisfies ReadonlyArray<{
  value: ImageBackground;
  label: string;
}>;

export const IMAGE_OUTPUT_FORMAT_OPTIONS = [
  { value: "png", label: "PNG" },
  { value: "jpeg", label: "JPEG" },
  { value: "webp", label: "WebP" },
] as const satisfies ReadonlyArray<{
  value: ImageOutputFormat;
  label: string;
}>;

export type ImageJobRequestOptions = {
  size?: string;
  quality?: ImageRenderQuality;
  background?: ImageBackground;
  output_format?: ImageOutputFormat;
  compression?: number;
};

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

export function isCodexImageModel(model: ImageModel | string | null | undefined) {
  return model === "codex-gpt-image-2";
}

const IMAGE_NATIVE_LONG_EDGE = {
  original: 0,
  "2k": 2048,
  "4k": 3840,
} as const satisfies Record<ImageOutputQuality, number>;
const IMAGE_MIN_PIXELS = 655_360;
const IMAGE_MAX_PIXELS = 8_294_400;

export function resolveRequestedImageSize(
  aspectRatio: ImageAspectRatio | undefined,
  outputQuality: ImageOutputQuality,
) {
  if (!aspectRatio) {
    return undefined;
  }
  if (outputQuality === "original") {
    return aspectRatio;
  }

  const option = IMAGE_ASPECT_RATIO_OPTIONS.find((item) => item.ratio === aspectRatio);
  if (!option) {
    return aspectRatio;
  }

  let width: number;
  let height: number;
  const ratio = option.width / option.height;
  const longEdge = IMAGE_NATIVE_LONG_EDGE[outputQuality];
  if (ratio >= 1) {
    width = longEdge;
    height = Math.round(longEdge / ratio);
  } else {
    height = longEdge;
    width = Math.round(longEdge * ratio);
  }

  width = Math.max(16, Math.round(width / 16) * 16);
  height = Math.max(16, Math.round(height / 16) * 16);

  const pixels = width * height;
  if (pixels > IMAGE_MAX_PIXELS) {
    const scale = Math.sqrt(IMAGE_MAX_PIXELS / pixels);
    width = Math.max(16, Math.floor((width * scale) / 16) * 16);
    height = Math.max(16, Math.floor((height * scale) / 16) * 16);
  }

  if (width * height < IMAGE_MIN_PIXELS) {
    return aspectRatio;
  }
  return `${width}x${height}`;
}

export function getImageOutputQualityLabel(value: ImageOutputQuality | undefined) {
  return IMAGE_OUTPUT_QUALITY_OPTIONS.find((option) => option.value === value)?.label ?? "原图";
}

export function getImageRenderQualityLabel(value: ImageRenderQuality | undefined) {
  return IMAGE_RENDER_QUALITY_OPTIONS.find((option) => option.value === value)?.label ?? "自动";
}

export function getImageBackgroundLabel(value: ImageBackground | undefined) {
  return IMAGE_BACKGROUND_OPTIONS.find((option) => option.value === value)?.label ?? "自动";
}

export function getImageOutputFormatLabel(value: ImageOutputFormat | undefined) {
  return IMAGE_OUTPUT_FORMAT_OPTIONS.find((option) => option.value === value)?.label ?? "PNG";
}

export function isImageOutputQuality(value: unknown): value is ImageOutputQuality {
  return IMAGE_OUTPUT_QUALITY_OPTIONS.some((option) => option.value === value);
}

export function isImageAspectRatio(value: unknown): value is ImageAspectRatio {
  return IMAGE_ASPECT_RATIO_OPTIONS.some((option) => option.ratio === value);
}

export function isImageRenderQuality(value: unknown): value is ImageRenderQuality {
  return IMAGE_RENDER_QUALITY_OPTIONS.some((option) => option.value === value);
}

export function isImageBackground(value: unknown): value is ImageBackground {
  return IMAGE_BACKGROUND_OPTIONS.some((option) => option.value === value);
}

export function isImageOutputFormat(value: unknown): value is ImageOutputFormat {
  return IMAGE_OUTPUT_FORMAT_OPTIONS.some((option) => option.value === value);
}

export function normalizeImageCompression(value: string | number | null | undefined) {
  if (value == null || value === "") {
    return undefined;
  }
  const numeric = typeof value === "number" ? value : Number.parseInt(String(value), 10);
  if (!Number.isFinite(numeric)) {
    return undefined;
  }
  return Math.max(0, Math.min(100, Math.round(numeric)));
}

export function buildImageJobRequestOptions({
  model,
  aspectRatio,
  outputQuality,
  renderQuality = DEFAULT_IMAGE_RENDER_QUALITY,
  background = DEFAULT_IMAGE_BACKGROUND,
  outputFormat = DEFAULT_IMAGE_OUTPUT_FORMAT,
  compression,
}: {
  model: ImageModel;
  aspectRatio: ImageAspectRatio | undefined;
  outputQuality: ImageOutputQuality;
  renderQuality?: ImageRenderQuality;
  background?: ImageBackground;
  outputFormat?: ImageOutputFormat;
  compression?: string | number | null;
}): ImageJobRequestOptions {
  const size = isCodexImageModel(model)
    ? resolveRequestedImageSize(aspectRatio, outputQuality)
    : aspectRatio;
  const options: ImageJobRequestOptions = size ? { size } : {};

  if (!isCodexImageModel(model)) {
    return options;
  }
  if (renderQuality !== DEFAULT_IMAGE_RENDER_QUALITY) {
    options.quality = renderQuality;
  }
  if (background !== DEFAULT_IMAGE_BACKGROUND) {
    options.background = background;
  }
  if (outputFormat !== DEFAULT_IMAGE_OUTPUT_FORMAT) {
    options.output_format = outputFormat;
  }
  const normalizedCompression =
    outputFormat === "png" ? undefined : normalizeImageCompression(compression);
  if (normalizedCompression !== undefined) {
    options.compression = normalizedCompression;
  }
  return options;
}
