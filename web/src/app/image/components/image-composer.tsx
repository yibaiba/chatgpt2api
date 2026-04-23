"use client";
import { ArrowUp, ImagePlus, LoaderCircle, X } from "lucide-react";
import { useMemo, useState, type ClipboardEvent, type DragEvent, type ReactNode, type RefObject } from "react";

import { ImageLightbox } from "@/components/image-lightbox";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { ImageModel } from "@/lib/api";
import type { ImageConversationMode } from "@/store/image-conversations";
import { cn } from "@/lib/utils";

type ImageComposerProps = {
  mode: ImageConversationMode;
  prompt: string;
  model: ImageModel;
  imageCount: string;
  availableQuota: string;
  hasAnyGenerating: boolean;
  generatingCount: number;
  referenceImages: Array<{ name: string; dataUrl: string }>;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  fileInputRef: RefObject<HTMLInputElement | null>;
  imageModelOptions: Array<{ label: string; value: ImageModel }>;
  imageCountOptions: Array<{ label: string; value: string }>;
  onModeChange: (value: ImageConversationMode) => void;
  onPromptChange: (value: string) => void;
  onModelChange: (value: ImageModel) => void;
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
  imageCount,
  availableQuota,
  hasAnyGenerating,
  generatingCount,
  referenceImages,
  textareaRef,
  fileInputRef,
  imageModelOptions,
  imageCountOptions,
  onModeChange,
  onPromptChange,
  onModelChange,
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
  const isSubmitDisabled = !prompt.trim() || (mode === "edit" && referenceImages.length === 0);
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
      <div style={{ width: "min(920px, 100%)" }}>
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
          <div className="mb-2.5 flex flex-wrap gap-2 px-1">
            {referenceImages.map((image, index) => (
              <div key={`${image.name}-${index}`} className="relative size-14">
                <button
                  type="button"
                  onClick={() => {
                    setLightboxIndex(index);
                    setLightboxOpen(true);
                  }}
                  className="group size-14 overflow-hidden rounded-2xl border border-white/70 bg-white/70 shadow-sm transition hover:border-stone-300"
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
            "overflow-hidden rounded-[24px] border border-white/70 bg-white/80 shadow-[0_12px_40px_rgba(28,25,23,0.08)] backdrop-blur-xl transition sm:rounded-[30px]",
            isDropActive ? "border-stone-300 bg-white/92 shadow-[0_16px_44px_rgba(28,25,23,0.12)]" : "",
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
          <div>
            <ImageLightbox
              images={lightboxImages}
              currentIndex={lightboxIndex}
              open={lightboxOpen}
              onOpenChange={setLightboxOpen}
              onIndexChange={setLightboxIndex}
            />
            <div
              className="cursor-text"
              onClick={() => {
                textareaRef.current?.focus();
              }}
            >
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
                className="min-h-[96px] resize-none rounded-[24px] border-0 bg-transparent px-4 pt-4 pb-3 text-[14px] leading-6 text-stone-900 shadow-none placeholder:text-stone-400 focus-visible:ring-0 sm:min-h-[108px] sm:rounded-[30px] sm:px-5 sm:pt-4"
              />
            </div>

            <div className="border-t border-white/70 bg-stone-50/45 px-4 py-3 sm:px-5 sm:py-3.5" onClick={(event) => event.stopPropagation()}>
              <div className="mb-2 px-1 text-[11px] leading-4 text-stone-500">
                {mode === "edit"
                  ? "可把生成图拖到这里继续编辑；手机端可直接点图片下方“作为参考图”。"
                  : "切到编辑图后，可把生成图拖到这里继续编辑。"}
              </div>
              <div className="flex flex-col gap-2">
                <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="rounded-full bg-white/75 px-2.5 py-1.5 text-[11px] font-medium text-stone-600 shadow-sm">剩余额度 {availableQuota}</div>
                    {hasAnyGenerating && (
                      <div className="flex items-center gap-1.5 rounded-full bg-amber-50/85 px-2.5 py-1.5 text-[11px] font-medium text-amber-700 shadow-sm">
                        <LoaderCircle className="size-3 animate-spin" />
                        {generatingCount} 个任务进行中
                      </div>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {mode === "edit" && (
                      <Button
                        type="button"
                        variant="outline"
                        className="h-9 rounded-full border-white/70 bg-white/80 px-3.5 text-xs font-medium text-stone-700 shadow-sm"
                        onClick={onPickReferenceImage}
                      >
                        <ImagePlus className="size-4" />
                        {referenceImages.length > 0 ? "继续添加参考图" : "上传参考图"}
                      </Button>
                    )}
                    <div className="inline-flex rounded-full bg-white/80 p-0.5 shadow-[inset_0_0_0_1px_rgba(231,229,228,1)]">
                      <ModeButton active={mode === "generate"} onClick={() => onModeChange("generate")}>
                        文生图
                      </ModeButton>
                      <ModeButton active={mode === "edit"} onClick={() => onModeChange("edit")}>
                        编辑图
                      </ModeButton>
                    </div>
                    <button
                      type="button"
                      onClick={() => void onSubmit()}
                      disabled={isSubmitDisabled}
                      className="inline-flex h-9 items-center justify-center gap-2 rounded-full bg-stone-950 px-4 text-xs font-semibold text-white shadow-sm transition hover:bg-stone-800 disabled:cursor-not-allowed disabled:bg-stone-300"
                      aria-label={mode === "edit" ? "编辑图片" : "生成图片"}
                    >
                      <span>{mode === "edit" ? "开始编辑" : "开始生成"}</span>
                      <ArrowUp className="size-3.5" />
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-1.5">
                  <ControlField label="模型">
                    <Select value={model} onValueChange={(value) => onModelChange(value as ImageModel)}>
                      <SelectTrigger className="h-9 w-full rounded-xl border-stone-200/80 bg-white/75 text-sm font-medium text-stone-700 shadow-none focus-visible:ring-0">
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
                  </ControlField>

                  <ControlField label="张数">
                    <Select value={imageCount} onValueChange={onImageCountChange}>
                      <SelectTrigger className="h-9 w-full rounded-xl border-stone-200/80 bg-white/75 text-sm font-medium text-stone-700 shadow-none focus-visible:ring-0">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {imageCountOptions.map((item) => (
                          <SelectItem key={item.value} value={item.value}>
                            {item.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </ControlField>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ControlField({
  label,
  helper,
  className,
  children,
}: {
  label: string;
  helper?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("rounded-[18px] border border-white/75 bg-white/58 p-2.5 shadow-[0_1px_2px_rgba(28,25,23,0.04)] backdrop-blur-sm", className)}>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-stone-500">{label}</span>
        {helper ? <span className="text-[10px] text-stone-400">{helper}</span> : null}
      </div>
      {children}
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
        "rounded-full px-3.5 py-1.5 text-xs font-medium transition",
        active ? "bg-stone-950 text-white shadow-sm" : "text-stone-600 hover:text-stone-900",
      )}
    >
      {children}
    </button>
  );
}
