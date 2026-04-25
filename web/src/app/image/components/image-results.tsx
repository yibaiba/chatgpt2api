"use client";

import { Clock3, CornerDownLeft, LoaderCircle, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ImageGenerationRoute } from "@/lib/api";
import { getImageOutputQualityLabel } from "@/lib/image-options";
import type { ImageConversation, ImageTurnStatus, StoredImage } from "@/store/image-conversations";

export type ImageLightboxItem = {
  id: string;
  src: string;
};

type ImageResultsProps = {
  selectedConversation: ImageConversation | null;
  showConversationOwner?: boolean;
  onOpenLightbox: (images: ImageLightboxItem[], index: number) => void;
  onReuseAsReference: (payload: { conversationId?: string; id?: string; dataUrl: string }) => void | Promise<void>;
  onReusePrompt: (payload: { conversationId?: string; prompt: string }) => void | Promise<void>;
  formatConversationTime: (value: string) => string;
};

export function ImageResults({
  selectedConversation,
  showConversationOwner = false,
  onOpenLightbox,
  onReuseAsReference,
  onReusePrompt,
  formatConversationTime,
}: ImageResultsProps) {
  if (!selectedConversation) {
    return (
      <div className="flex h-full min-h-[420px] items-center justify-center text-center">
        <div className="w-full max-w-4xl">
          <h1
            className="text-3xl font-semibold tracking-tight text-stone-950 md:text-5xl"
            style={{
              fontFamily: '"Palatino Linotype","Book Antiqua","URW Palladio L","Times New Roman",serif',
            }}
          >
            Turn ideas into images
          </h1>
          <p
            className="mt-4 text-[15px] italic tracking-[0.01em] text-stone-500"
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

  return (
    <div className="mx-auto flex w-full max-w-[980px] flex-col gap-8">
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
          <div key={turn.id} className="flex flex-col gap-4">
            <div className="flex justify-end">
              <div className="max-w-[82%] px-1 py-1 text-[15px] leading-7 text-stone-900">
                <div className="mb-2 flex flex-wrap justify-end gap-2 text-[11px] text-stone-400">
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
                    className="min-h-11 rounded-full border-stone-200 bg-white text-stone-700 hover:bg-stone-50"
                    onClick={() =>
                      void onReusePrompt({
                        conversationId: selectedConversation.id,
                        prompt: turn.prompt,
                      })
                    }
                  >
                    <CornerDownLeft className="size-4" />
                    填入输入框
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
                            className="rounded-full border-stone-200 bg-white text-stone-700 hover:bg-stone-50"
                            onClick={() =>
                              void onReuseAsReference({
                                conversationId: selectedConversation.id,
                                id: `${turn.id}-reference-${index}`,
                                dataUrl: image.dataUrl,
                              })
                            }
                          >
                            <Sparkles className="size-4" />
                            加入编辑
                          </Button>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-stone-500">
                  <span className="rounded-full bg-stone-100 px-3 py-1">{turn.count} 张</span>
                  {turn.aspectRatio ? <span className="rounded-full bg-stone-100 px-3 py-1">{turn.aspectRatio}</span> : null}
                  {turn.outputQuality ? (
                    <span className="rounded-full bg-stone-100 px-3 py-1">{getImageOutputQualityLabel(turn.outputQuality)}</span>
                  ) : null}
                  <span className="rounded-full bg-stone-100 px-3 py-1">{getTurnStatusLabel(turn.status)}</span>
                  {turn.status === "queued" ? (
                    <span className="rounded-full bg-amber-50 px-3 py-1 text-amber-700">等待当前对话中的前序任务完成</span>
                  ) : null}
                </div>

                <div className="columns-1 gap-4 space-y-4 sm:columns-2 xl:columns-3">
                  {turn.images.map((image, index) => {
                    if (image.status === "success" && image.b64_json) {
                      const currentIndex = successfulTurnImages.findIndex((item) => item.id === image.id);

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
                            />
                          </button>
                          <div className="flex items-center justify-between gap-2 px-3 py-3">
                            <div className="flex items-center gap-2 text-xs text-stone-500">
                              <span>结果 {index + 1}</span>
                              {image.generation_route ? (
                                <span className={getGenerationRouteBadgeClassName(image.generation_route)}>
                                  {getGenerationRouteLabel(image.generation_route)}
                                </span>
                              ) : null}
                            </div>
                            <Button
                              variant="outline"
                              size="sm"
                              className="rounded-full border-stone-200 bg-white text-stone-700 hover:bg-stone-50"
                              onClick={() =>
                                void onReuseAsReference({
                                  conversationId: selectedConversation.id,
                                  id: image.id,
                                  dataUrl: buildImageDataUrl(image),
                                })
                              }
                            >
                              <Sparkles className="size-4" />
                              加入编辑
                            </Button>
                          </div>
                        </div>
                      );
                    }

                    if (image.status === "error") {
                      return (
                        <div
                          key={image.id}
                          className="break-inside-avoid overflow-hidden border border-rose-200 bg-rose-50"
                        >
                          <div className="flex min-h-[320px] items-center justify-center px-6 py-8 text-center text-sm leading-6 text-rose-600">
                            {image.error || "生成失败"}
                          </div>
                        </div>
                      );
                    }

                    return (
                      <div
                        key={image.id}
                        className="break-inside-avoid overflow-hidden border border-stone-200/80 bg-stone-100/80"
                      >
                        <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 px-6 py-8 text-center text-stone-500">
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

function buildImageDataUrl(image: StoredImage) {
  return `data:${image.mime_type || "image/png"};base64,${image.b64_json || ""}`;
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
