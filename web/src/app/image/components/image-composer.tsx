"use client";
import { ArrowUp, ImagePlus, LoaderCircle, X } from "lucide-react";
import { useMemo, useState, type ClipboardEvent, type DragEvent, type RefObject } from "react";

import { ImageLightbox } from "@/components/image-lightbox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { ImageBackground, ImageModel, ImageOutputFormat, ImageQuality } from "@/lib/api";
import type { ImageConversationMode } from "@/store/image-conversations";
import { cn } from "@/lib/utils";

type ImageComposerProps = {
  mode: ImageConversationMode;
  prompt: string;
  model: ImageModel;
  size: string;
  quality: ImageQuality;
  background: ImageBackground;
  outputFormat: ImageOutputFormat;
  compression: string;
  imageCount: string;
  availableQuota: string;
  hasAnyGenerating: boolean;
  generatingCount: number;
  referenceImages: Array<{ name: string; dataUrl: string }>;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  fileInputRef: RefObject<HTMLInputElement | null>;
  imageModelOptions: Array<{ label: string; value: ImageModel }>;
  imageSizeSuggestions: string[];
  imageQualityOptions: Array<{ label: string; value: ImageQuality }>;
  imageBackgroundOptions: Array<{ label: string; value: ImageBackground }>;
  imageOutputFormatOptions: Array<{ label: string; value: ImageOutputFormat }>;
  supportsTransparentBackground: boolean;
  supportsCompression: boolean;
  onModeChange: (value: ImageConversationMode) => void;
  onPromptChange: (value: string) => void;
  onModelChange: (value: ImageModel) => void;
  onSizeChange: (value: string) => void;
  onQualityChange: (value: ImageQuality) => void;
  onBackgroundChange: (value: ImageBackground) => void;
  onOutputFormatChange: (value: ImageOutputFormat) => void;
  onCompressionChange: (value: string) => void;
  onImageCountChange: (value: string) => void;
  onSubmit: () => void | Promise<void>;
  onPickReferenceImage: () => void;
  onReferenceImageChange: (files: File[]) => void | Promise<void>;
  onReferenceImageReuse: (payload: { id?: string; dataUrl: string }) => void | Promise<void>;
  onRemoveReferenceImage: (index: number) => void;
};

export function ImageComposer({
  mode,
  prompt,
  model,
  size,
  quality,
  background,
  outputFormat,
  compression,
  imageCount,
  availableQuota,
  hasAnyGenerating,
  generatingCount,
  referenceImages,
  textareaRef,
  fileInputRef,
  imageModelOptions,
  imageSizeSuggestions,
  imageQualityOptions,
  imageBackgroundOptions,
  imageOutputFormatOptions,
  supportsTransparentBackground,
  supportsCompression,
  onModeChange,
  onPromptChange,
  onModelChange,
  onSizeChange,
  onQualityChange,
  onBackgroundChange,
  onOutputFormatChange,
  onCompressionChange,
  onImageCountChange,
  onSubmit,
  onPickReferenceImage,
  onReferenceImageChange,
  onReferenceImageReuse,
  onRemoveReferenceImage,
}: ImageComposerProps) {
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [isDropActive, setIsDropActive] = useState(false);
  const lightboxImages = useMemo(
    () => referenceImages.map((image, index) => ({ id: `${image.name}-${index}`, src: image.dataUrl })),
    [referenceImages],
  );

  const handleTextareaPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    if (mode !== "edit") {
      return;
    }

    const imageFiles = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith("image/"));
    if (imageFiles.length === 0) {
      return;
    }

    event.preventDefault();
    void onReferenceImageChange(imageFiles);
  };

  const handleDragState = (event: DragEvent<HTMLDivElement | HTMLTextAreaElement>) => {
    if (event.dataTransfer.types.includes("Files") || event.dataTransfer.types.includes("application/x-chatgpt2api-reference-image")) {
      if (mode !== "edit") {
        onModeChange("edit");
      }
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      setIsDropActive(true);
    }
  };

  const handleDrop = (event: DragEvent<HTMLDivElement | HTMLTextAreaElement>) => {
    const droppedFiles = Array.from(event.dataTransfer.files).filter((file) => file.type.startsWith("image/"));
    const rawPayload = event.dataTransfer.getData("application/x-chatgpt2api-reference-image");
    setIsDropActive(false);

    if (droppedFiles.length === 0 && !rawPayload) {
      return;
    }

    event.preventDefault();
    if (mode !== "edit") {
      onModeChange("edit");
    }

    if (droppedFiles.length > 0) {
      void onReferenceImageChange(droppedFiles);
      return;
    }

    try {
      const payload = JSON.parse(rawPayload) as { id?: string; dataUrl?: string };
      if (payload.dataUrl) {
        void onReferenceImageReuse({ id: payload.id, dataUrl: payload.dataUrl });
      }
    } catch {
      // Ignore unrelated drag data.
    }
  };

  return (
    <div className="shrink-0 flex justify-center">
      <div style={{ width: "min(980px, 100%)" }}>
        {mode === "edit" && (
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            onChange={(event) => {
              void onReferenceImageChange(Array.from(event.target.files || []));
            }}
          />
        )}

        {mode === "edit" && referenceImages.length > 0 ? (
          <div className="mb-3 flex flex-wrap gap-2 px-1">
            {referenceImages.map((image, index) => (
              <div key={`${image.name}-${index}`} className="relative size-16">
                <button
                  type="button"
                  onClick={() => {
                    setLightboxIndex(index);
                    setLightboxOpen(true);
                  }}
                  className="group size-16 overflow-hidden rounded-2xl border border-stone-200 bg-stone-50 transition hover:border-stone-300"
                  aria-label={`预览参考图 ${image.name || index + 1}`}
                >
                  <img
                    src={image.dataUrl}
                    alt={image.name || `参考图 ${index + 1}`}
                    className="h-full w-full object-cover"
                  />
                </button>
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onRemoveReferenceImage(index);
                  }}
                  className="absolute -right-1 -top-1 inline-flex size-5 items-center justify-center rounded-full border border-stone-200 bg-white text-stone-500 transition hover:border-stone-300 hover:text-stone-800"
                  aria-label={`移除参考图 ${image.name || index + 1}`}
                >
                  <X className="size-3" />
                </button>
              </div>
            ))}
          </div>
        ) : null}

        <div
          className={cn(
            "overflow-hidden rounded-[24px] border bg-white transition sm:rounded-[32px]",
            isDropActive ? "border-stone-900 bg-stone-50 shadow-[0_0_0_1px_rgba(28,25,23,0.1)]" : "border-stone-200",
          )}
          onDragEnter={handleDragState}
          onDragOver={handleDragState}
          onDragLeave={(event) => {
            if (event.currentTarget.contains(event.relatedTarget as Node | null)) {
              return;
            }
            setIsDropActive(false);
          }}
          onDrop={handleDrop}
        >
          <div
            className="relative cursor-text"
            onClick={() => {
              textareaRef.current?.focus();
            }}
          >
            <ImageLightbox
              images={lightboxImages}
              currentIndex={lightboxIndex}
              open={lightboxOpen}
              onOpenChange={setLightboxOpen}
              onIndexChange={setLightboxIndex}
            />
            <Textarea
              ref={textareaRef}
              value={prompt}
              onChange={(event) => onPromptChange(event.target.value)}
              onPaste={handleTextareaPaste}
              placeholder={mode === "edit" ? "描述你希望如何修改这张参考图，可直接粘贴、拖拽或点“作为参考图”" : "输入你想要生成的画面"}
              onDragEnter={handleDragState}
              onDragOver={handleDragState}
              onDrop={handleDrop}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing || event.keyCode === 229) {
                  return;
                }
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void onSubmit();
                }
              }}
              className="min-h-[132px] resize-none rounded-[24px] border-0 bg-transparent px-4 pt-5 pb-24 text-[15px] leading-7 text-stone-900 shadow-none placeholder:text-stone-400 focus-visible:ring-0 sm:min-h-[148px] sm:rounded-[32px] sm:px-6 sm:pt-6 sm:pb-20"
            />

            <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-white via-white/95 to-transparent px-4 pb-4 pt-6 sm:px-6">
              <div className="mb-3 px-1 text-xs text-stone-500">
                {mode === "edit"
                  ? "可把生成图拖到这里继续编辑；手机端可直接点图片下方“作为参考图”。"
                  : "切到编辑图后，可把生成图拖到这里继续编辑。"}
              </div>
              <div className="flex flex-col gap-3">
                <div className="flex min-w-0 flex-wrap items-center gap-2 sm:gap-3">
                  {mode === "edit" && (
                    <Button
                      type="button"
                      variant="outline"
                      className="h-9 rounded-full border-stone-200 bg-white px-4 text-sm font-medium text-stone-700 shadow-none sm:h-10"
                      onClick={onPickReferenceImage}
                    >
                      <ImagePlus className="size-4" />
                      {referenceImages.length > 0 ? "继续添加参考图" : "上传参考图"}
                    </Button>
                  )}
                  <div className="rounded-full bg-stone-100 px-3 py-2 text-xs font-medium text-stone-600">剩余额度 {availableQuota}</div>
                  {hasAnyGenerating && (
                    <div className="flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700">
                      <LoaderCircle className="size-3 animate-spin" />
                      {generatingCount} 个任务进行中
                    </div>
                  )}
                  <Select value={model} onValueChange={(value) => onModelChange(value as ImageModel)}>
                    <SelectTrigger className="h-9 w-[140px] rounded-full border-stone-200 bg-white text-sm font-medium text-stone-700 shadow-none focus-visible:ring-0 sm:h-10 sm:w-[164px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {imageModelOptions.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <div className="flex items-center gap-2 rounded-full border border-stone-200 bg-white px-3 py-1">
                    <span className="text-sm font-medium text-stone-700">张数</span>
                    <Input
                      type="number"
                      min="1"
                      max="10"
                      step="1"
                      value={imageCount}
                      onChange={(event) => onImageCountChange(event.target.value)}
                      className="h-8 w-[64px] border-0 bg-transparent px-0 text-center text-sm font-medium text-stone-700 shadow-none focus-visible:ring-0"
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <ModeButton active={mode === "generate"} onClick={() => onModeChange("generate")}>
                      文生图
                    </ModeButton>
                    <ModeButton active={mode === "edit"} onClick={() => onModeChange("edit")}>
                      编辑图
                    </ModeButton>
                  </div>
                </div>

                <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                  <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 sm:gap-3">
                    <div className="flex items-center gap-2 rounded-full border border-stone-200 bg-white px-3 py-1">
                      <span className="text-sm font-medium text-stone-700">尺寸</span>
                      <Input
                        type="text"
                        value={size}
                        onChange={(event) => onSizeChange(event.target.value)}
                        placeholder="自动 / 2160x3840"
                        list="image-size-suggestions"
                        className="h-8 w-[132px] border-0 bg-transparent px-0 text-center text-sm font-medium text-stone-700 shadow-none placeholder:text-stone-400 focus-visible:ring-0"
                      />
                    </div>
                    <datalist id="image-size-suggestions">
                      {imageSizeSuggestions.map((item) => (
                        <option key={item} value={item} />
                      ))}
                    </datalist>
                    <Select value={quality} onValueChange={(value) => onQualityChange(value as ImageQuality)}>
                      <SelectTrigger className="h-9 w-[112px] rounded-full border-stone-200 bg-white text-sm font-medium text-stone-700 shadow-none focus-visible:ring-0 sm:h-10 sm:w-[124px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {imageQualityOptions.map((item) => (
                          <SelectItem key={item.value} value={item.value}>
                            {item.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Select value={background} onValueChange={(value) => onBackgroundChange(value as ImageBackground)}>
                      <SelectTrigger className="h-9 w-[118px] rounded-full border-stone-200 bg-white text-sm font-medium text-stone-700 shadow-none focus-visible:ring-0 sm:h-10 sm:w-[132px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {imageBackgroundOptions.map((item) => (
                          <SelectItem
                            key={item.value}
                            value={item.value}
                            disabled={!supportsTransparentBackground && item.value === "transparent"}
                          >
                            {item.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Select value={outputFormat} onValueChange={(value) => onOutputFormatChange(value as ImageOutputFormat)}>
                      <SelectTrigger className="h-9 w-[110px] rounded-full border-stone-200 bg-white text-sm font-medium text-stone-700 shadow-none focus-visible:ring-0 sm:h-10 sm:w-[118px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {imageOutputFormatOptions.map((item) => (
                          <SelectItem key={item.value} value={item.value}>
                            {item.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <div
                      className={cn(
                        "flex items-center gap-2 rounded-full border bg-white px-3 py-1",
                        supportsCompression ? "border-stone-200" : "border-stone-100 bg-stone-50 text-stone-400",
                      )}
                    >
                      <span className="text-sm font-medium">压缩</span>
                      <Input
                        type="number"
                        min="0"
                        max="100"
                        step="1"
                        value={compression}
                        onChange={(event) => onCompressionChange(event.target.value)}
                        placeholder={supportsCompression ? "0-100" : "仅 JPEG/WEBP"}
                        disabled={!supportsCompression}
                        className="h-8 w-[96px] border-0 bg-transparent px-0 text-center text-sm font-medium text-stone-700 shadow-none placeholder:text-stone-400 focus-visible:ring-0 disabled:text-stone-400"
                      />
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => void onSubmit()}
                    disabled={!prompt.trim() || (mode === "edit" && referenceImages.length === 0)}
                    className="inline-flex size-11 shrink-0 self-end items-center justify-center rounded-full bg-stone-950 text-white transition hover:bg-stone-800 disabled:cursor-not-allowed disabled:bg-stone-300 sm:self-auto"
                    aria-label={mode === "edit" ? "编辑图片" : "生成图片"}
                  >
                    <ArrowUp className="size-4" />
                  </button>
                </div>
                <div className="px-1 text-[11px] leading-5 text-stone-500">
                  支持 size/quality/background 的 auto。尺寸需满足：最长边 ≤ 3840、宽高均为 16 的倍数、长宽比 ≤
                  3:1、总像素介于 655,360 到 8,294,400。超过 2560×1440 的输出属于实验性范围。
                  {!supportsTransparentBackground ? " gpt-image-2 不支持 transparent 背景。" : null}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ModeButton({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full px-4 py-2 text-sm font-medium transition",
        active ? "bg-stone-950 text-white" : "bg-stone-100 text-stone-600 hover:bg-stone-200",
      )}
    >
      {children}
    </button>
  );
}
