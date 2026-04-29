"use client";
import {
  ArrowUp,
  ChevronDown,
  ImagePlus,
  LoaderCircle,
  SlidersHorizontal,
  X,
} from "lucide-react";
import {
  useMemo,
  useState,
  type ClipboardEvent,
  type DragEvent,
  type RefObject,
} from "react";

import { ImageLightbox } from "@/components/image-lightbox";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { ImageModel } from "@/lib/api";
import {
  getImageOutputQualityLabel,
  type ImageAspectRatio,
  type ImageOutputQuality,
} from "@/lib/image-options";
import type { ImageConversationMode } from "@/store/image-conversations";
import { cn } from "@/lib/utils";

import { ImagePanelControls } from "./image-panel-controls";
import { ImagePromptGallery } from "./image-prompt-gallery";

type ImageComposerProps = {
  mode: ImageConversationMode;
  model: ImageModel;
  prompt: string;
  aspectRatio: ImageAspectRatio;
  imageCount: string;
  outputQuality: ImageOutputQuality;
  availableQuota: string;
  activeTaskCount: number;
  referenceImages: Array<{ name: string; dataUrl: string }>;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onModeChange: (value: ImageConversationMode) => void;
  onModelChange: (value: ImageModel) => void;
  onPromptChange: (value: string) => void;
  onAspectRatioChange: (value: ImageAspectRatio) => void;
  onImageCountChange: (value: string) => void;
  onOutputQualityChange: (value: ImageOutputQuality) => void;
  onSubmit: () => void | Promise<void>;
  onPickReferenceImage: () => void;
  onReferenceImageChange: (files: File[]) => void | Promise<void>;
  onReferenceImageReuse: (payload: {
    conversationId?: string;
    id?: string;
    dataUrl: string;
  }) => void | Promise<void>;
  onRemoveReferenceImage: (index: number) => void;
};

export function ImageComposer({
  mode,
  model,
  prompt,
  aspectRatio,
  imageCount,
  outputQuality,
  availableQuota,
  activeTaskCount,
  referenceImages,
  textareaRef,
  fileInputRef,
  onModeChange,
  onModelChange,
  onPromptChange,
  onAspectRatioChange,
  onImageCountChange,
  onOutputQualityChange,
  onSubmit,
  onPickReferenceImage,
  onReferenceImageChange,
  onReferenceImageReuse,
  onRemoveReferenceImage,
}: ImageComposerProps) {
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [isDropActive, setIsDropActive] = useState(false);
  const [mobileSettingsOpen, setMobileSettingsOpen] = useState(false);
  const lightboxImages = useMemo(
    () =>
      referenceImages.map((image, index) => ({
        id: `${image.name}-${index}`,
        src: image.dataUrl,
      })),
    [referenceImages],
  );

  const handleTextareaPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const imageFiles = Array.from(event.clipboardData.files).filter((file) =>
      file.type.startsWith("image/"),
    );
    if (imageFiles.length === 0) {
      return;
    }

    event.preventDefault();
    if (mode !== "edit") {
      onModeChange("edit");
    }
    void onReferenceImageChange(imageFiles);
  };

  const handleDragState = (
    event: DragEvent<HTMLDivElement | HTMLTextAreaElement>,
  ) => {
    if (
      event.dataTransfer.types.includes("Files") ||
      event.dataTransfer.types.includes(
        "application/x-chatgpt2api-reference-image",
      )
    ) {
      if (mode !== "edit") {
        onModeChange("edit");
      }
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      setIsDropActive(true);
    }
  };

  const handleDrop = (
    event: DragEvent<HTMLDivElement | HTMLTextAreaElement>,
  ) => {
    const droppedFiles = Array.from(event.dataTransfer.files).filter((file) =>
      file.type.startsWith("image/"),
    );
    const rawPayload = event.dataTransfer.getData(
      "application/x-chatgpt2api-reference-image",
    );
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
      const payload = JSON.parse(rawPayload) as {
        conversationId?: string;
        id?: string;
        dataUrl?: string;
      };
      if (payload.dataUrl) {
        void onReferenceImageReuse({
          conversationId: payload.conversationId,
          id: payload.id,
          dataUrl: payload.dataUrl,
        });
      }
    } catch {
      // Ignore unrelated drag data.
    }
  };

  return (
    <div className="shrink-0 flex justify-center px-1 sm:px-0">
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
          <div className="mb-2 flex gap-2 overflow-x-auto px-1 pb-1 sm:mb-3 sm:flex-wrap sm:overflow-visible sm:pb-0">
            {referenceImages.map((image, index) => (
              <div key={`${image.name}-${index}`} className="relative size-14 shrink-0 sm:size-16">
                <button
                  type="button"
                  onClick={() => {
                    setLightboxIndex(index);
                    setLightboxOpen(true);
                  }}
                  className="group size-14 overflow-hidden rounded-2xl border border-stone-200 bg-stone-50 transition hover:border-stone-300 sm:size-16"
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
            "overflow-hidden rounded-[24px] border bg-white transition shadow-[0_14px_60px_-42px_rgba(15,23,42,0.45)] sm:rounded-[32px] sm:shadow-none",
            isDropActive
              ? "border-stone-900 bg-stone-50 shadow-[0_0_0_1px_rgba(28,25,23,0.1)]"
              : "border-stone-200",
          )}
          onDragEnter={handleDragState}
          onDragOver={handleDragState}
          onDragLeave={(event) => {
            if (
              event.currentTarget.contains(event.relatedTarget as Node | null)
            ) {
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
            <MobileImageSettingsBar
              open={mobileSettingsOpen}
              mode={mode}
              model={model}
              aspectRatio={aspectRatio}
              imageCount={imageCount}
              outputQuality={outputQuality}
              onToggle={() => setMobileSettingsOpen((value) => !value)}
            />
            <div
              className={cn(
                "sm:block",
                mobileSettingsOpen ? "block" : "hidden",
              )}
            >
              <ImagePanelControls
                mode={mode}
                model={model}
                aspectRatio={aspectRatio}
                imageCount={imageCount}
                outputQuality={outputQuality}
                onModeChange={onModeChange}
                onModelChange={onModelChange}
                onAspectRatioChange={onAspectRatioChange}
                onImageCountChange={onImageCountChange}
                onOutputQualityChange={onOutputQualityChange}
              />
            </div>
            <Textarea
              ref={textareaRef}
              value={prompt}
              onChange={(event) => onPromptChange(event.target.value)}
              onPaste={handleTextareaPaste}
              placeholder={
                mode === "edit"
                  ? "描述你希望如何修改这张参考图，可直接粘贴、拖拽或点“加入编辑”"
                  : "输入你想要生成的画面，也可直接粘贴图片"
              }
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
              className="min-h-[82px] resize-none rounded-[24px] border-0 bg-transparent px-4 pt-4 pb-4 text-[15px] leading-6 text-stone-900 shadow-none placeholder:text-stone-400 focus-visible:ring-0 sm:min-h-[152px] sm:rounded-[32px] sm:px-6 sm:pt-5 sm:pb-6 sm:leading-7"
            />

            <div className="border-t border-stone-200/80 bg-white px-4 py-3 sm:px-6 sm:py-4">
              <div className="flex items-end justify-between gap-3">
                <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 sm:gap-3">
                  {mode === "generate" ? (
                    <ImagePromptGallery
                      selectedPrompt={prompt}
                      onSelectPrompt={(nextPrompt) => {
                        onPromptChange(nextPrompt);
                        window.requestAnimationFrame(() => {
                          const element = textareaRef.current;
                          if (!element) {
                            return;
                          }
                          element.focus();
                          const end = nextPrompt.length;
                          element.setSelectionRange(end, end);
                        });
                      }}
                    />
                  ) : null}
                  {mode === "edit" && (
                    <Button
                      type="button"
                      variant="outline"
                      className="h-10 max-w-full rounded-full border-stone-200 bg-white px-4 text-sm font-medium text-stone-700 shadow-none"
                      onClick={onPickReferenceImage}
                    >
                      <ImagePlus className="size-4" />
                      {referenceImages.length > 0
                        ? "继续添加参考图"
                        : "上传参考图"}
                    </Button>
                  )}
                  <div className="rounded-full bg-stone-100 px-3 py-2 text-xs font-medium text-stone-600">
                    剩余额度 {availableQuota}
                  </div>
                  {activeTaskCount > 0 && (
                    <div className="flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700">
                      <LoaderCircle className="size-3 animate-spin" />
                      {activeTaskCount} 个任务处理中或排队中
                    </div>
                  )}
                </div>

                <button
                  type="button"
                  onClick={() => void onSubmit()}
                  disabled={
                    !prompt.trim() ||
                    (mode === "edit" && referenceImages.length === 0)
                  }
                  className="inline-flex size-11 shrink-0 items-center justify-center rounded-full bg-stone-950 text-white transition hover:bg-stone-800 disabled:cursor-not-allowed disabled:bg-stone-300"
                  aria-label={mode === "edit" ? "编辑图片" : "生成图片"}
                >
                  <ArrowUp className="size-4" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function MobileImageSettingsBar({
  open,
  mode,
  model,
  aspectRatio,
  imageCount,
  outputQuality,
  onToggle,
}: {
  open: boolean;
  mode: ImageConversationMode;
  model: ImageModel;
  aspectRatio: ImageAspectRatio;
  imageCount: string;
  outputQuality: ImageOutputQuality;
  onToggle: () => void;
}) {
  const normalizedCount = Math.max(1, Math.min(10, Number(imageCount) || 1));
  const summary = [
    mode === "edit" ? "图生图" : "文生图",
    getImageModelShortLabel(model),
    aspectRatio,
    `${normalizedCount} 张`,
    getImageOutputQualityLabel(outputQuality),
  ];

  return (
    <div className="border-b border-stone-200/80 px-4 py-3 sm:hidden">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2 text-xs font-medium text-stone-500">
          <SlidersHorizontal className="size-4 shrink-0 text-stone-400" />
          <span className="truncate">{summary.join(" · ")}</span>
        </div>
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onToggle();
          }}
          className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border border-stone-200 bg-stone-50 px-3 text-xs font-semibold text-stone-700 transition hover:bg-white"
          aria-expanded={open}
          aria-label={open ? "收起图片参数" : "展开图片参数"}
        >
          参数
          <ChevronDown
            className={cn("size-3.5 transition", open ? "rotate-180" : "")}
          />
        </button>
      </div>
    </div>
  );
}

function getImageModelShortLabel(model: ImageModel) {
  return model === "gpt-image-think" ? "思考" : "标准";
}
