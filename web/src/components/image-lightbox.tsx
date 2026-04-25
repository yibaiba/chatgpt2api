"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { ChevronLeft, ChevronRight, Download, RotateCcw, X, ZoomIn, ZoomOut } from "lucide-react";

import { cn } from "@/lib/utils";

type LightboxImage = {
  id: string;
  src: string;
};

type ImageLightboxProps = {
  images: LightboxImage[];
  currentIndex: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onIndexChange: (index: number) => void;
};

const MIN_SCALE = 1;
const MAX_SCALE = 4;
const SCALE_STEP = 0.25;

type ImageOffset = {
  x: number;
  y: number;
};

type DragState = {
  pointerId: number;
  startX: number;
  startY: number;
  startOffset: ImageOffset;
};

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function getClampedOffset(
  offset: ImageOffset,
  scale: number,
  frame: HTMLDivElement | null,
  image: HTMLImageElement | null,
) {
  if (!frame || !image || scale <= MIN_SCALE) {
    return { x: 0, y: 0 };
  }

  const maxX = Math.max(0, (image.clientWidth * scale - frame.clientWidth) / 2);
  const maxY = Math.max(0, (image.clientHeight * scale - frame.clientHeight) / 2);

  return {
    x: clamp(offset.x, -maxX, maxX),
    y: clamp(offset.y, -maxY, maxY),
  };
}

export function ImageLightbox({
  images,
  currentIndex,
  open,
  onOpenChange,
  onIndexChange,
}: ImageLightboxProps) {
  const current = images[currentIndex];
  const hasPrev = currentIndex > 0;
  const hasNext = currentIndex < images.length - 1;
  const frameRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const dragStateRef = useRef<DragState | null>(null);
  const [scale, setScale] = useState(MIN_SCALE);
  const [offset, setOffset] = useState<ImageOffset>({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);

  const goPrev = useCallback(() => {
    if (hasPrev) onIndexChange(currentIndex - 1);
  }, [hasPrev, currentIndex, onIndexChange]);

  const goNext = useCallback(() => {
    if (hasNext) onIndexChange(currentIndex + 1);
  }, [hasNext, currentIndex, onIndexChange]);

  const releaseActivePointerCapture = useCallback(() => {
    const frame = frameRef.current;
    const activePointerId = dragStateRef.current?.pointerId;
    if (frame && activePointerId !== undefined && frame.hasPointerCapture(activePointerId)) {
      frame.releasePointerCapture(activePointerId);
    }
    dragStateRef.current = null;
    setIsDragging(false);
  }, []);

  const resetTransform = useCallback(() => {
    releaseActivePointerCapture();
    setScale(MIN_SCALE);
    setOffset({ x: 0, y: 0 });
  }, [releaseActivePointerCapture]);

  const applyScale = useCallback((nextScale: number) => {
    const clampedScale = clamp(nextScale, MIN_SCALE, MAX_SCALE);
    setScale(clampedScale);
    setOffset((prev) => getClampedOffset(prev, clampedScale, frameRef.current, imageRef.current));
    if (clampedScale === MIN_SCALE) {
      releaseActivePointerCapture();
    }
  }, [releaseActivePointerCapture]);

  const zoomIn = useCallback(() => {
    applyScale(scale + SCALE_STEP);
  }, [applyScale, scale]);

  const zoomOut = useCallback(() => {
    applyScale(scale - SCALE_STEP);
  }, [applyScale, scale]);

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        goPrev();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        goNext();
      } else if (e.key === "+" || e.key === "=") {
        e.preventDefault();
        zoomIn();
      } else if (e.key === "-" || e.key === "_") {
        e.preventDefault();
        zoomOut();
      } else if (e.key === "0") {
        e.preventDefault();
        resetTransform();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, goPrev, goNext, resetTransform, zoomIn, zoomOut]);

  useEffect(() => {
    if (!open) {
      resetTransform();
      return;
    }
    resetTransform();
  }, [open, current?.id, resetTransform]);

  const handleDownload = useCallback(() => {
    if (!current) return;
    const link = document.createElement("a");
    link.href = current.src;
    link.download = `image-${current.id}.png`;
    link.click();
  }, [current]);

  const handleWheel = useCallback((event: ReactWheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (event.deltaY < 0) {
      zoomIn();
      return;
    }
    zoomOut();
  }, [zoomIn, zoomOut]);

  const handleDoubleClick = useCallback(() => {
    applyScale(scale > MIN_SCALE ? MIN_SCALE : 2);
  }, [applyScale, scale]);

  const handlePointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (scale <= MIN_SCALE) {
      return;
    }
    if (event.pointerType === "mouse" && event.button !== 0) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    dragStateRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      startOffset: offset,
    };
    setIsDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  }, [offset, scale]);

  const handlePointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }

    event.preventDefault();
    const nextOffset = {
      x: dragState.startOffset.x + event.clientX - dragState.startX,
      y: dragState.startOffset.y + event.clientY - dragState.startY,
    };
    setOffset(getClampedOffset(nextOffset, scale, frameRef.current, imageRef.current));
  }, [scale]);

  const handlePointerUp = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current;
    const isCaptured = event.currentTarget.hasPointerCapture(event.pointerId);
    if ((!dragState || dragState.pointerId !== event.pointerId) && !isCaptured) {
      return;
    }

    if (isCaptured) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (dragState?.pointerId === event.pointerId) {
      dragStateRef.current = null;
    }
    setIsDragging(false);
  }, []);

  if (!current) return null;

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          className="fixed inset-0 z-50 flex items-center justify-center outline-none"
          onPointerDownOutside={(e) => e.preventDefault()}
        >
          <DialogPrimitive.Title className="sr-only">
            图片预览
          </DialogPrimitive.Title>

          {/* toolbar */}
          <div className="absolute top-4 right-4 z-10 flex flex-wrap items-center justify-end gap-2">
            {images.length > 1 && (
              <span className="rounded-full bg-black/50 px-3 py-1.5 text-xs font-medium text-white/90">
                {currentIndex + 1} / {images.length}
              </span>
            )}
            <span className="rounded-full bg-black/50 px-3 py-1.5 text-xs font-medium text-white/90">
              {Math.round(scale * 100)}%
            </span>
            <button
              type="button"
              onClick={zoomOut}
              disabled={scale <= MIN_SCALE}
              className="inline-flex size-11 items-center justify-center rounded-full bg-black/50 text-white/90 transition hover:bg-black/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 disabled:cursor-not-allowed disabled:opacity-40"
              aria-label="缩小图片"
            >
              <ZoomOut className="size-4" />
            </button>
            <button
              type="button"
              onClick={zoomIn}
              disabled={scale >= MAX_SCALE}
              className="inline-flex size-11 items-center justify-center rounded-full bg-black/50 text-white/90 transition hover:bg-black/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 disabled:cursor-not-allowed disabled:opacity-40"
              aria-label="放大图片"
            >
              <ZoomIn className="size-4" />
            </button>
            <button
              type="button"
              onClick={resetTransform}
              disabled={scale === MIN_SCALE && offset.x === 0 && offset.y === 0}
              className="inline-flex size-11 items-center justify-center rounded-full bg-black/50 text-white/90 transition hover:bg-black/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 disabled:cursor-not-allowed disabled:opacity-40"
              aria-label="重置缩放"
            >
              <RotateCcw className="size-4" />
            </button>
            <button
              type="button"
              onClick={handleDownload}
              className="inline-flex size-11 items-center justify-center rounded-full bg-black/50 text-white/90 transition hover:bg-black/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
              aria-label="下载图片"
            >
              <Download className="size-4" />
            </button>
            <DialogPrimitive.Close className="inline-flex size-11 items-center justify-center rounded-full bg-black/50 text-white/90 transition hover:bg-black/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70">
              <X className="size-4" />
              <span className="sr-only">关闭</span>
            </DialogPrimitive.Close>
          </div>

          {/* prev */}
          {hasPrev && (
            <button
              type="button"
              onClick={goPrev}
              className="absolute left-4 z-10 inline-flex size-11 items-center justify-center rounded-full bg-black/40 text-white/90 transition hover:bg-black/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
              aria-label="上一张"
            >
              <ChevronLeft className="size-5" />
            </button>
          )}

          {/* image */}
          <div
            className="flex max-h-[90vh] max-w-[90vw] items-center justify-center"
            onClick={() => onOpenChange(false)}
          >
            <div
              ref={frameRef}
              className={cn(
                "relative flex max-h-[90vh] max-w-[90vw] items-center justify-center overflow-hidden rounded-lg",
                scale > MIN_SCALE ? "touch-none" : "touch-manipulation",
                scale > MIN_SCALE ? (isDragging ? "cursor-grabbing" : "cursor-grab") : "cursor-zoom-in",
              )}
              onClick={(event) => event.stopPropagation()}
              onWheel={handleWheel}
              onDoubleClick={handleDoubleClick}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={handlePointerUp}
            >
              <img
                ref={imageRef}
                src={current.src}
                alt={`预览图片 ${currentIndex + 1}`}
                className="max-h-[90vh] max-w-[90vw] rounded-lg object-contain select-none"
                style={{
                  transform: `translate3d(${offset.x}px, ${offset.y}px, 0) scale(${scale})`,
                  transition: isDragging ? "none" : "transform 180ms ease-out",
                }}
                draggable={false}
              />
            </div>
          </div>

          <div className="pointer-events-none absolute bottom-4 left-1/2 z-10 -translate-x-1/2 rounded-full bg-black/45 px-3 py-1.5 text-xs font-medium text-white/80">
            滚轮 / 双击可缩放，放大后可拖动查看细节
          </div>

          {/* next */}
          {hasNext && (
            <button
              type="button"
              onClick={goNext}
              className="absolute right-4 z-10 inline-flex size-11 items-center justify-center rounded-full bg-black/40 text-white/90 transition hover:bg-black/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
              aria-label="下一张"
            >
              <ChevronRight className="size-5" />
            </button>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
