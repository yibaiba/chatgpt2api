"use client";

import type { ReactNode } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ImageModel } from "@/lib/api";
import {
  getImageModelDescription,
  IMAGE_ASPECT_RATIO_OPTIONS,
  IMAGE_MODEL_OPTIONS,
  IMAGE_OUTPUT_QUALITY_OPTIONS,
  type ImageAspectRatio,
  type ImageOutputQuality,
} from "@/lib/image-options";
import { cn } from "@/lib/utils";
import type { ImageConversationMode } from "@/store/image-conversations";

type ImagePanelControlsProps = {
  mode: ImageConversationMode;
  model: ImageModel;
  aspectRatio: ImageAspectRatio;
  imageCount: string;
  outputQuality: ImageOutputQuality;
  onModeChange: (value: ImageConversationMode) => void;
  onModelChange: (value: ImageModel) => void;
  onAspectRatioChange: (value: ImageAspectRatio) => void;
  onImageCountChange: (value: string) => void;
  onOutputQualityChange: (value: ImageOutputQuality) => void;
};

export function ImagePanelControls({
  mode,
  model,
  aspectRatio,
  imageCount,
  outputQuality,
  onModeChange,
  onModelChange,
  onAspectRatioChange,
  onImageCountChange,
  onOutputQualityChange,
}: ImagePanelControlsProps) {
  const currentModelDescription = getImageModelDescription(model);
  const normalizedCount = Math.max(1, Math.min(10, Number(imageCount) || 1));

  return (
    <div className="border-b border-stone-200/80 px-4 py-4 sm:px-6">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-start gap-3">
          <CompactField label="图片模型" className="min-w-[260px] flex-1">
            <div className="flex items-center gap-1 rounded-full border border-stone-200 bg-stone-50 p-1">
              {IMAGE_MODEL_OPTIONS.map((option) => (
                <CompactToggle
                  key={option.value}
                  active={model === option.value}
                  onClick={() => onModelChange(option.value)}
                  className="justify-center px-3"
                >
                  {getModelShortLabel(option.value)}
                </CompactToggle>
              ))}
            </div>
          </CompactField>

          <CompactField label="模式">
            <div className="flex items-center gap-1 rounded-full border border-stone-200 bg-stone-50 p-1">
              <CompactToggle active={mode === "generate"} onClick={() => onModeChange("generate")}>
                文生图
              </CompactToggle>
              <CompactToggle active={mode === "edit"} onClick={() => onModeChange("edit")}>
                图生图
              </CompactToggle>
            </div>
          </CompactField>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <CompactField label="比例">
            <Select value={aspectRatio} onValueChange={(value) => onAspectRatioChange(value as ImageAspectRatio)}>
              <SelectTrigger className="h-9 min-w-[108px] rounded-full border-stone-200 bg-white px-3 shadow-none">
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

          <CompactField label="张数">
            <Select value={String(normalizedCount)} onValueChange={onImageCountChange}>
              <SelectTrigger className="h-9 min-w-[88px] rounded-full border-stone-200 bg-white px-3 shadow-none">
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

          <CompactField label="输出尺寸" className="min-w-[180px]">
            <div className="inline-flex items-center gap-1 rounded-full border border-stone-200 bg-stone-50 p-0.5">
              {IMAGE_OUTPUT_QUALITY_OPTIONS.map((option) => (
                <CompactToggle
                  key={option.value}
                  active={outputQuality === option.value}
                  onClick={() => onOutputQualityChange(option.value)}
                  className="min-w-[74px] justify-center px-2.5"
                >
                  {option.label}
                </CompactToggle>
              ))}
            </div>
          </CompactField>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-stone-500">
          <span>{currentModelDescription}</span>
          <span>比例会自动作为 prompt 首行前缀发送</span>
          <span>2K / 4K 为浏览器端本地高清放大</span>
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
        "inline-flex h-8 items-center rounded-full px-3 text-sm font-medium transition",
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
  if (model === "gpt-image-1") {
    return "兼容";
  }
  return "标准";
}
