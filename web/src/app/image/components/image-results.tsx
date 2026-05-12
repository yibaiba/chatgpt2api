"use client";

import { useState } from "react";
import { Clock3, CornerDownLeft, LoaderCircle, Paintbrush, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ImageGenerationRoute, ImageModel } from "@/lib/api";
import {
  getImageBackgroundLabel,
  getImageOutputFormatLabel,
  getImageOutputQualityLabel,
  getImageRenderQualityLabel,
  isCodexImageModel,
  type ImageBackground,
  type ImageAspectRatio,
  type ImageOutputFormat,
  type ImageOutputQuality,
  type ImageRenderQuality,
} from "@/lib/image-options";
import type {
  ImageConversation,
  ImageConversationMode,
  ImageTurnStatus,
  StoredImage,
  StoredReferenceImage,
} from "@/store/image-conversations";

export type ImageLightboxItem = {
  id: string;
  src: string;
};

type ImageResultsProps = {
  selectedConversation: ImageConversation | null;
  showConversationOwner?: boolean;
  onOpenLightbox: (images: ImageLightboxItem[], index: number) => void;
  onReuseAsReference: (payload: { conversationId?: string; id?: string; dataUrl: string }) => void | Promise<void>;
  onInpaint: (payload: { imageDataUrl: string; prompt: string }) => void | Promise<void>;
  onReusePrompt: (payload: {
    conversationId?: string;
    prompt: string;
    mode: ImageConversationMode;
    model: ImageModel;
    aspectRatio?: ImageAspectRatio;
    outputQuality?: ImageOutputQuality;
    renderQuality?: ImageRenderQuality;
    background?: ImageBackground;
    outputFormat?: ImageOutputFormat;
    compression?: number;
    referenceImages: StoredReferenceImage[];
  }) => void | Promise<void>;
  formatConversationTime: (value: string) => string;
};

export function ImageResults({
  selectedConversation,
  showConversationOwner = false,
  onOpenLightbox,
  onReuseAsReference,
  onInpaint,
  onReusePrompt,
  formatConversationTime,
}: ImageResultsProps) {
  const [imageDimensions, setImageDimensions] = useState<Record<string, string>>({});

  const updateImageDimensions = (id: string, width: number, height: number) => {
    const dimensions = formatImageDimensions(width, height);
    setImageDimensions((current) => {
      if (current[id] === dimensions) {
        return current;
      }
      return {
        ...current,
        [id]: dimensions,
      };
    });
  };

  if (!selectedConversation) {
    return (
      <div className="flex h-full min-h-[260px] items-center justify-center text-center sm:min-h-[420px]">
        <div className="w-full max-w-4xl">
          <h1
            className="text-2xl font-semibold tracking-tight text-stone-950 sm:text-3xl md:text-5xl"
            style={{
              fontFamily: '"Palatino Linotype","Book Antiqua","URW Palladio L","Times New Roman",serif',
            }}
          >
            Turn ideas into images
          </h1>
          <p
            className="mx-auto mt-3 max-w-[280px] text-sm italic tracking-[0.01em] text-stone-500 sm:mt-4 sm:max-w-none sm:text-[15px]"
            style={{
              fontFamily: '"Palatino Linotype","Book Antiqua","URW Palladio L","Times New Roman",serif',
            }}
          >
            在同一窗口里保留本地历史与任务状态，并从已有结果图继续发起新的无状态编辑。
          </p>
        </div>
      </div>
    );
  }

  if (selectedConversation.turns.length === 0) {
    return (
      <div className="flex h-full min-h-[320px] items-center justify-center text-center">
        <div className="w-full max-w-2xl rounded-[32px] border border-dashed border-stone-200 bg-white/60 px-6 py-10 shadow-sm">
          <div className="text-sm font-semibold text-stone-900">新对话已创建</div>
          <p className="mt-2 text-sm leading-6 text-stone-500">
            在下方输入提示词并发送后，这条对话会自动保存到历史记录。
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-[980px] flex-col gap-5 sm:gap-8">
      {selectedConversation.turns.map((turn, turnIndex) => {
        const referenceLightboxImages = turn.referenceImages.map((image, index) => ({
          id: `${turn.id}-reference-${index}`,
          src: image.dataUrl,
        }));
        const successfulTurnImages = turn.images.flatMap((image) =>
          image.status === "success" && image.b64_json
            ? [{ id: image.id, src: buildImageDataUrl(image) }]
            : [],
        );

        return (
          <div key={turn.id} className="flex flex-col gap-3 sm:gap-4">
            <div className="flex justify-end">
              <div className="max-w-[90%] px-1 py-1 text-[14px] leading-6 text-stone-900 sm:max-w-[82%] sm:text-[15px] sm:leading-7">
                <div className="mb-1.5 flex flex-wrap justify-end gap-2 text-[11px] text-stone-400 sm:mb-2">
                  <span>第 {turnIndex + 1} 轮</span>
                  <span>
                    {turn.mode === "edit" ? "编辑图" : "文生图"}
                  </span>
                  {showConversationOwner ? <span>{selectedConversation.ownerName}</span> : null}
                  <span>{getTurnStatusLabel(turn.status)}</span>
                  <span>{formatConversationTime(turn.createdAt)}</span>
                </div>
                <div className="text-right">{turn.prompt}</div>
                <div className="mt-3 flex justify-end">
                  <Button
                    variant="outline"
                    size="sm"
                    className="min-h-11 rounded-full border-stone-200 bg-white text-stone-700 hover:bg-stone-50 touch-manipulation"
                    onClick={() =>
                      void onReusePrompt({
                        conversationId: selectedConversation.id,
                        prompt: turn.prompt,
                        mode: turn.mode,
                        model: turn.model,
                        aspectRatio: turn.aspectRatio,
                        outputQuality: turn.outputQuality,
                        renderQuality: turn.renderQuality,
                        background: turn.background,
                        outputFormat: turn.outputFormat,
                        compression: turn.compression,
                        referenceImages: turn.referenceImages,
                      })
                    }
                    aria-label={turn.referenceImages.length > 0 ? "恢复本轮提示词和参考图到输入区" : "恢复本轮提示词到输入区"}
                  >
                    <CornerDownLeft className="size-4" />
                    恢复到输入区
                  </Button>
                </div>
              </div>
            </div>

            <div className="flex justify-start">
              <div className="w-full p-1">
                {turn.referenceImages.length > 0 ? (
                  <div className="mb-4 flex flex-col items-end">
                    <div className="mb-3 text-xs font-medium text-stone-500">本轮参考图</div>
                    <div className="flex flex-wrap justify-end gap-3">
                      {turn.referenceImages.map((image, index) => (
                        <div key={`${turn.id}-${image.name}-${index}`} className="flex flex-col items-end gap-2">
                          <button
                            type="button"
                            onClick={() => onOpenLightbox(referenceLightboxImages, index)}
                            draggable
                            onDragStart={(event) => {
                              event.dataTransfer.effectAllowed = "copy";
                              event.dataTransfer.setData(
                                "application/x-chatgpt2api-reference-image",
                                JSON.stringify({
                                  conversationId: selectedConversation.id,
                                  id: `${turn.id}-reference-${index}`,
                                  dataUrl: image.dataUrl,
                                }),
                              );
                              event.dataTransfer.setData("text/plain", image.dataUrl);
                            }}
                            className="group relative h-24 w-24 overflow-hidden border border-stone-200/80 bg-stone-100/60 text-left transition hover:border-stone-300"
                            aria-label={`预览参考图 ${image.name || index + 1}`}
                          >
                            <img
                              src={image.dataUrl}
                              alt={image.name || `参考图 ${index + 1}`}
                              className="absolute inset-0 h-full w-full object-cover transition duration-200 group-hover:scale-[1.02]"
                            />
                          </button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 w-7 rounded-full border-stone-200 bg-white px-0 text-stone-700 hover:bg-stone-50 sm:h-8 sm:w-auto sm:px-3"
                            onClick={() =>
                              void onReuseAsReference({
                                conversationId: selectedConversation.id,
                                id: `${turn.id}-reference-${index}`,
                                dataUrl: image.dataUrl,
                              })
                            }
                            aria-label="加入编辑"
                          >
                            <Sparkles className="size-4" />
                            <span className="hidden sm:inline">加入编辑</span>
                          </Button>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="mb-3 flex flex-wrap items-center gap-1.5 text-[11px] text-stone-500 sm:mb-4 sm:gap-2 sm:text-xs">
                  <span className="rounded-full bg-stone-100 px-3 py-1">{turn.count} 张</span>
                  <span className="rounded-full bg-stone-100 px-3 py-1">{getModelLabel(turn.model)}</span>
                  {turn.aspectRatio ? <span className="rounded-full bg-stone-100 px-3 py-1">{turn.aspectRatio}</span> : null}
                  {turn.outputQuality ? (
                    <span className="rounded-full bg-stone-100 px-3 py-1">{getImageOutputQualityLabel(turn.outputQuality)}</span>
                  ) : null}
                  {isCodexImageModel(turn.model) && turn.renderQuality && turn.renderQuality !== "auto" ? (
                    <span className="rounded-full bg-blue-50 px-3 py-1 text-blue-700">
                      质量 {getImageRenderQualityLabel(turn.renderQuality)}
                    </span>
                  ) : null}
                  {isCodexImageModel(turn.model) && turn.background && turn.background !== "auto" ? (
                    <span className="rounded-full bg-blue-50 px-3 py-1 text-blue-700">
                      背景 {getImageBackgroundLabel(turn.background)}
                    </span>
                  ) : null}
                  {isCodexImageModel(turn.model) && turn.outputFormat && turn.outputFormat !== "png" ? (
                    <span className="rounded-full bg-blue-50 px-3 py-1 text-blue-700">
                      {getImageOutputFormatLabel(turn.outputFormat)}
                    </span>
                  ) : null}
                  {isCodexImageModel(turn.model) && typeof turn.compression === "number" ? (
                    <span className="rounded-full bg-blue-50 px-3 py-1 text-blue-700">
                      压缩 {turn.compression}
                    </span>
                  ) : null}
                  <span className="rounded-full bg-stone-100 px-3 py-1">{getTurnStatusLabel(turn.status)}</span>
                  {turn.status === "queued" ? (
                    <span className="rounded-full bg-amber-50 px-3 py-1 text-amber-700">等待当前对话中的前序任务完成</span>
                  ) : null}
                </div>

                <div className="columns-1 gap-3 space-y-3 sm:columns-2 sm:gap-4 sm:space-y-4 xl:columns-3">
                  {turn.images.map((image, index) => {
                    if (image.status === "success" && image.b64_json) {
                      const currentIndex = successfulTurnImages.findIndex((item) => item.id === image.id);
                      const imageMeta = [formatBase64ImageSize(image.b64_json), imageDimensions[image.id]]
                        .filter(Boolean)
                        .join(" · ");

                      return (
                        <div
                          key={image.id}
                          className="break-inside-avoid overflow-hidden"
                        >
                          <button
                            type="button"
                            onClick={() => onOpenLightbox(successfulTurnImages, currentIndex)}
                            draggable
                            onDragStart={(event) => {
                              const dataUrl = buildImageDataUrl(image);
                              event.dataTransfer.effectAllowed = "copy";
                              event.dataTransfer.setData(
                                "application/x-chatgpt2api-reference-image",
                                JSON.stringify({
                                  conversationId: selectedConversation.id,
                                  id: image.id,
                                  dataUrl,
                                }),
                              );
                              event.dataTransfer.setData("text/plain", dataUrl);
                            }}
                            className="group block w-full cursor-zoom-in"
                          >
                            <img
                              src={buildImageDataUrl(image)}
                              alt={`Generated result ${index + 1}`}
                              className="block h-auto w-full transition duration-200 group-hover:brightness-90"
                              onLoad={(event) => {
                                updateImageDimensions(
                                  image.id,
                                  event.currentTarget.naturalWidth,
                                  event.currentTarget.naturalHeight,
                                );
                              }}
                            />
                          </button>
                          <div className="flex items-center justify-between gap-2 px-3 py-3">
                            <div className="min-w-0 text-xs text-stone-500">
                              <span>结果 {index + 1}</span>
                              {imageMeta ? <span className="ml-2 text-stone-400">{imageMeta}</span> : null}
                              {image.generation_route ? (
                                <span className={`ml-2 ${getGenerationRouteBadgeClassName(image.generation_route)}`}>
                                  {getGenerationRouteLabel(image.generation_route)}
                                </span>
                              ) : null}
                            </div>
                            <div className="flex items-center gap-1.5">
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 w-7 rounded-full border-stone-200 bg-white px-0 text-stone-700 hover:bg-stone-50 sm:h-8 sm:w-auto sm:px-3"
                              onClick={() => {
                                const dataUrl = buildImageDataUrl(image);
                                const base64Part = dataUrl.split(",")[1] ?? "";
                                if (!base64Part) {
                                  // b64_json 为空，无法编辑
                                  return;
                                }
                                void onInpaint({
                                  imageDataUrl: dataUrl,
                                  prompt: turn.prompt,
                                });
                              }}
                              aria-label="编辑图片"
                            >
                              <Paintbrush className="size-4" />
                              <span className="hidden sm:inline">编辑图片</span>
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 w-7 rounded-full border-stone-200 bg-white px-0 text-stone-700 hover:bg-stone-50 sm:h-8 sm:w-auto sm:px-3"
                              onClick={() =>
                                void onReuseAsReference({
                                  conversationId: selectedConversation.id,
                                  id: image.id,
                                  dataUrl: buildImageDataUrl(image),
                                })
                              }
                              aria-label="加入编辑"
                            >
                              <Sparkles className="size-4" />
                              <span className="hidden sm:inline">加入编辑</span>
                            </Button>
                            </div>
                          </div>
                        </div>
                      );
                    }

                    if (image.status === "error") {
                      return (
                        <div
                          key={image.id}
                          className="break-inside-avoid overflow-hidden rounded-2xl border border-rose-200 bg-rose-50 sm:rounded-none"
                        >
                          <div className="flex min-h-16 items-center justify-center px-4 py-4 text-center text-sm leading-6 text-rose-600 sm:min-h-[320px] sm:px-6 sm:py-8">
                            {image.error || "生成失败"}
                          </div>
                        </div>
                      );
                    }

                    return (
                      <div
                        key={image.id}
                        className="break-inside-avoid overflow-hidden rounded-2xl border border-stone-200/80 bg-stone-100/80 sm:rounded-none"
                      >
                        <div className="flex min-h-16 flex-col items-center justify-center gap-3 px-4 py-4 text-center text-stone-500 sm:min-h-[320px] sm:px-6 sm:py-8">
                          <div className="rounded-full bg-white p-3 shadow-sm">
                            {turn.status === "queued" ? (
                              <Clock3 className="size-5" />
                            ) : (
                              <LoaderCircle className="size-5 animate-spin" />
                            )}
                          </div>
                          <p className="text-sm">{turn.status === "queued" ? "已加入当前对话队列..." : "正在处理图片..."}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {turn.status === "error" && turn.error ? (
                  <div className="mt-4 border-l-2 border-amber-300 bg-amber-50/70 px-4 py-3 text-sm leading-6 text-amber-700">
                    {turn.error}
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function getTurnStatusLabel(status: ImageTurnStatus) {
  if (status === "queued") {
    return "排队中";
  }
  if (status === "generating") {
    return "处理中";
  }
  if (status === "success") {
    return "已完成";
  }
  return "失败";
}

function getModelLabel(model: string) {
  if (model === "codex-gpt-image-2") {
    return "Codex";
  }
  if (model === "gpt-image-think") {
    return "思考";
  }
  return "标准";
}

function buildImageDataUrl(image: StoredImage) {
  return `data:${image.mime_type || "image/png"};base64,${image.b64_json || ""}`;
}

function formatBase64ImageSize(base64: string) {
  const normalized = base64.replace(/\s/g, "");
  const padding = normalized.endsWith("==") ? 2 : normalized.endsWith("=") ? 1 : 0;
  const bytes = Math.max(0, Math.floor((normalized.length * 3) / 4) - padding);
  if (bytes >= 1024 * 1024) {
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${bytes} B`;
}

function formatImageDimensions(width: number, height: number) {
  return `${width} x ${height}`;
}

function getGenerationRouteLabel(route: ImageGenerationRoute) {
  if (route === "thinking") {
    return "思考";
  }
  if (route === "fallback") {
    return "思考回退";
  }
  return "标准";
}

function getGenerationRouteBadgeClassName(route: ImageGenerationRoute) {
  if (route === "thinking") {
    return "rounded-full bg-violet-100 px-2.5 py-1 text-[11px] font-medium text-violet-700";
  }
  if (route === "fallback") {
    return "rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-medium text-amber-700";
  }
  return "rounded-full bg-stone-100 px-2.5 py-1 text-[11px] font-medium text-stone-600";
}
