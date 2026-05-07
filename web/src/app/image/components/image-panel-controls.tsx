"use client";

import type { ReactNode } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import type { ImageModel } from "@/lib/api";
import {
  IMAGE_BACKGROUND_OPTIONS,
  getImageModelDescription,
  IMAGE_ASPECT_RATIO_OPTIONS,
  IMAGE_MODEL_OPTIONS,
  IMAGE_OUTPUT_QUALITY_OPTIONS,
  IMAGE_OUTPUT_FORMAT_OPTIONS,
  IMAGE_RENDER_QUALITY_OPTIONS,
  isCodexImageModel,
  type ImageBackground,
  type ImageAspectRatio,
  type ImageOutputFormat,
  type ImageOutputQuality,
  type ImageRenderQuality,
} from "@/lib/image-options";
import { cn } from "@/lib/utils";
import type { ImageConversationMode } from "@/store/image-conversations";

type ImagePanelControlsProps = {
  mode: ImageConversationMode;
  model: ImageModel;
  aspectRatio: ImageAspectRatio;
  imageCount: string;
  outputQuality: ImageOutputQuality;
  renderQuality: ImageRenderQuality;
  background: ImageBackground;
  outputFormat: ImageOutputFormat;
  compressionValue: string;
  onModeChange: (value: ImageConversationMode) => void;
  onModelChange: (value: ImageModel) => void;
  onAspectRatioChange: (value: ImageAspectRatio) => void;
  onImageCountChange: (value: string) => void;
  onOutputQualityChange: (value: ImageOutputQuality) => void;
  onRenderQualityChange: (value: ImageRenderQuality) => void;
  onBackgroundChange: (value: ImageBackground) => void;
  onOutputFormatChange: (value: ImageOutputFormat) => void;
  onCompressionChange: (value: string) => void;
};

export function ImagePanelControls({
  mode,
  model,
  aspectRatio,
  imageCount,
  outputQuality,
  renderQuality,
  background,
  outputFormat,
  compressionValue,
  onModeChange,
  onModelChange,
  onAspectRatioChange,
  onImageCountChange,
  onOutputQualityChange,
  onRenderQualityChange,
  onBackgroundChange,
  onOutputFormatChange,
  onCompressionChange,
}: ImagePanelControlsProps) {
  const selectableModelOptions = IMAGE_MODEL_OPTIONS.filter((option) => {
    if (option.value === "gpt-image-1") {
      return false;
    }
    if (mode === "edit" && option.value === "gpt-image-think") {
      return false;
    }
    return true;
  });
  const currentModelDescription =
    mode === "edit"
      ? "图生图统一走上游 picture_v2 编辑链，可在官网 gpt-image-2 与 官网 api 独立额度间切换，不提供思考模式。"
      : getImageModelDescription(model);
  const supportsCodexNativeOptions = isCodexImageModel(model);
  const sizeBehaviorDescription =
    supportsCodexNativeOptions
      ? ""
      : "标准 / 思考模型：比例作为提示词，2K / 4K 浏览器本地放大。";
  const normalizedCount = Math.max(1, Math.min(10, Number(imageCount) || 1));

  return (
    <div className="border-b border-stone-200/80 px-4 py-4 sm:px-6">
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-start">
          <CompactField label="图片模型" className="w-full min-w-0 sm:min-w-[260px] sm:flex-1">
            <div className="flex w-full items-center gap-1 rounded-full border border-stone-200 bg-stone-50 p-1">
              {selectableModelOptions.map((option) => (
                <CompactToggle
                  key={option.value}
                  active={model === option.value}
                  onClick={() => onModelChange(option.value)}
                  className="min-w-0 flex-1 justify-center px-3 sm:flex-none"
                >
                  {getModelShortLabel(option.value)}
                </CompactToggle>
              ))}
            </div>
          </CompactField>

          <CompactField label="模式" className="w-full sm:w-auto">
            <div className="flex w-full items-center gap-1 rounded-full border border-stone-200 bg-stone-50 p-1">
              <CompactToggle active={mode === "generate"} onClick={() => onModeChange("generate")}>
                文生图
              </CompactToggle>
              <CompactToggle active={mode === "edit"} onClick={() => onModeChange("edit")}>
                图生图
              </CompactToggle>
            </div>
          </CompactField>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:flex sm:flex-wrap sm:items-end">
          <CompactField label="比例" className="min-w-0">
            <Select value={aspectRatio} onValueChange={(value) => onAspectRatioChange(value as ImageAspectRatio)}>
              <SelectTrigger className="h-11 w-full min-w-0 rounded-full border-stone-200 bg-white px-3 shadow-none sm:h-9 sm:min-w-[108px]">
                <SelectValue placeholder={aspectRatio} />
              </SelectTrigger>
              <SelectContent>
                {IMAGE_ASPECT_RATIO_OPTIONS.map((option) => (
                  <SelectItem key={option.ratio} value={option.ratio}>
                    {option.label} {option.ratio}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </CompactField>

          <CompactField label="张数" className="min-w-0">
            <Select value={String(normalizedCount)} onValueChange={onImageCountChange}>
              <SelectTrigger className="h-11 w-full min-w-0 rounded-full border-stone-200 bg-white px-3 shadow-none sm:h-9 sm:min-w-[88px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Array.from({ length: 10 }, (_, index) => (
                  <SelectItem key={index + 1} value={String(index + 1)}>
                    {index + 1} 张
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </CompactField>

          <CompactField label="输出尺寸" className="col-span-2 min-w-0 sm:min-w-[180px]">
            <div className="grid w-full grid-cols-3 items-center gap-1 rounded-[20px] border border-stone-200 bg-stone-50 p-0.5 sm:inline-flex sm:w-auto sm:rounded-full">
              {IMAGE_OUTPUT_QUALITY_OPTIONS.map((option) => (
                <CompactToggle
                  key={option.value}
                  active={outputQuality === option.value}
                  onClick={() => onOutputQualityChange(option.value)}
                  className="min-w-0 justify-center px-2.5 sm:min-w-[74px]"
                >
                  {option.label}
                </CompactToggle>
              ))}
            </div>
          </CompactField>
        </div>

        {supportsCodexNativeOptions ? (
          <div className="rounded-[24px] border border-blue-100 bg-blue-50/60 p-3 sm:p-4">
            <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-xs font-semibold text-stone-900">api参数</span>
             
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <CompactField label="生成质量" className="min-w-0">
                <Select value={renderQuality} onValueChange={(value) => onRenderQualityChange(value as ImageRenderQuality)}>
                  <SelectTrigger className="h-11 w-full min-w-0 rounded-full border-stone-200 bg-white px-3 shadow-none sm:h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {IMAGE_RENDER_QUALITY_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </CompactField>

              <CompactField label="背景" className="min-w-0">
                <Select value={background} onValueChange={(value) => onBackgroundChange(value as ImageBackground)}>
                  <SelectTrigger className="h-11 w-full min-w-0 rounded-full border-stone-200 bg-white px-3 shadow-none sm:h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {IMAGE_BACKGROUND_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </CompactField>

              <CompactField label="输出格式" className="min-w-0">
                <Select value={outputFormat} onValueChange={(value) => onOutputFormatChange(value as ImageOutputFormat)}>
                  <SelectTrigger className="h-11 w-full min-w-0 rounded-full border-stone-200 bg-white px-3 shadow-none sm:h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {IMAGE_OUTPUT_FORMAT_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </CompactField>

              <CompactField label="压缩级别" className="min-w-0">
                <Input
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  inputMode="numeric"
                  value={compressionValue}
                  disabled={outputFormat === "png"}
                  onChange={(event) => onCompressionChange(event.target.value)}
                  placeholder={outputFormat === "png" ? "PNG 不支持" : "0 - 100"}
                  className="h-11 rounded-full border-stone-200 px-3 shadow-none disabled:bg-stone-100 sm:h-9"
                />
              </CompactField>
            </div>
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-stone-500">
          <span>{currentModelDescription}</span>
          <span>{sizeBehaviorDescription}</span>
        </div>
      </div>
    </div>
  );
}

function CompactField({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="text-xs font-medium text-stone-500">{label}</div>
      {children}
    </div>
  );
}

function CompactToggle({
  active,
  children,
  onClick,
  className,
}: {
  active: boolean;
  children: string;
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "touch-manipulation inline-flex h-11 items-center justify-center rounded-full px-3 text-sm font-medium transition sm:h-9",
        active ? "bg-blue-600 text-white shadow-sm" : "text-stone-600 hover:bg-white hover:text-stone-800",
        className,
      )}
    >
      {children}
    </button>
  );
}

function getModelShortLabel(model: ImageModel) {
  if (model === "gpt-image-think") {
    return "思考";
  }
  if (model === "codex-gpt-image-2") {
    return "Codex";
  }
  return "标准";
}
