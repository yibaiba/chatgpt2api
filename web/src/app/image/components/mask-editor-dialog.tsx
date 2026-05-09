"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Eraser, Paintbrush, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

type MaskEditorDialogProps = {
  open: boolean;
  imageDataUrl: string;
  defaultPrompt?: string;
  onClose: () => void;
  onSubmit: (maskFile: File, prompt: string) => void | Promise<void>;
};

const MIN_BRUSH = 8;
const MAX_BRUSH = 80;
const DEFAULT_BRUSH = 28;

export function MaskEditorDialog({ open, imageDataUrl, defaultPrompt = "", onClose, onSubmit }: MaskEditorDialogProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const canvasWrapRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const drawingRef = useRef(false);
  const lastPosRef = useRef<{ x: number; y: number } | null>(null);
  const toolRef = useRef<"brush" | "eraser">("brush");

  const [tool, setTool] = useState<"brush" | "eraser">("brush");
  const [brushSize, setBrushSize] = useState(DEFAULT_BRUSH);
  const [prompt, setPrompt] = useState(defaultPrompt);
  const [submitting, setSubmitting] = useState(false);
  const [canvasReady, setCanvasReady] = useState(false);
  // 自定义光标位置（相对于画布 wrapper）
  const [cursorPos, setCursorPos] = useState<{ x: number; y: number } | null>(null);

  // 同步 toolRef 以避免闭包陈旧引用
  useEffect(() => {
    toolRef.current = tool;
  }, [tool]);

  // 加载图片并初始化 canvas
  useEffect(() => {
    if (!open) return;
    setCanvasReady(false);
    const img = new Image();
    img.onload = () => {
      imageRef.current = img;
      const canvas = canvasRef.current;
      if (!canvas) return;
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      setCanvasReady(true);
    };
    img.src = imageDataUrl;
  }, [open, imageDataUrl]);

  // 重置时同步 prompt
  useEffect(() => {
    if (open) setPrompt(defaultPrompt);
  }, [open, defaultPrompt]);

  const getCanvasPos = useCallback((canvas: HTMLCanvasElement, clientX: number, clientY: number) => {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: (clientX - rect.left) * scaleX,
      y: (clientY - rect.top) * scaleY,
    };
  }, []);

  const draw = useCallback((canvas: HTMLCanvasElement, x: number, y: number, fromX?: number, fromY?: number) => {
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const scaledBrush = brushSize * (canvas.width / canvas.getBoundingClientRect().width);
    ctx.save();
    ctx.globalCompositeOperation = toolRef.current === "eraser" ? "destination-out" : "source-over";
    // 画布上显示浅蓝色（视觉反馈），导出时会转成黑白 mask
    ctx.fillStyle = "rgba(96, 165, 250, 0.85)";
    ctx.strokeStyle = "rgba(96, 165, 250, 0.85)";
    ctx.lineWidth = scaledBrush;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    if (fromX !== undefined && fromY !== undefined) {
      ctx.beginPath();
      ctx.moveTo(fromX, fromY);
      ctx.lineTo(x, y);
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(x, y, scaledBrush / 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }, [brushSize]);

  const handlePointerDown = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.setPointerCapture(e.pointerId);
    drawingRef.current = true;
    const pos = getCanvasPos(canvas, e.clientX, e.clientY);
    lastPosRef.current = pos;
    draw(canvas, pos.x, pos.y);
  }, [draw, getCanvasPos]);

  const handlePointerMove = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    // 更新自定义光标位置（相对于 wrapper div）
    const wrap = canvasWrapRef.current;
    if (wrap) {
      const rect = wrap.getBoundingClientRect();
      setCursorPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
    }
    if (!drawingRef.current) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const pos = getCanvasPos(canvas, e.clientX, e.clientY);
    const last = lastPosRef.current;
    draw(canvas, pos.x, pos.y, last?.x, last?.y);
    lastPosRef.current = pos;
  }, [draw, getCanvasPos]);

  const handlePointerUp = useCallback(() => {
    drawingRef.current = false;
    lastPosRef.current = null;
  }, []);

  const handleClear = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx?.clearRect(0, 0, canvas.width, canvas.height);
  }, []);

  const exportMaskAsFile = useCallback((): File | null => {
    const canvas = canvasRef.current;
    const img = imageRef.current;
    if (!canvas || !img) return null;

    // 合成最终 mask：黑色背景 + 白色遮罩区域（将蓝色涂层中有 alpha 的像素转为白色）
    const offscreen = document.createElement("canvas");
    offscreen.width = canvas.width;
    offscreen.height = canvas.height;
    const ctx = offscreen.getContext("2d");
    if (!ctx) return null;

    // 黑色背景
    ctx.fillStyle = "black";
    ctx.fillRect(0, 0, offscreen.width, offscreen.height);

    // 读取遮罩 canvas 像素，将有 alpha 的像素转换为不透明白色
    const srcCtx = canvas.getContext("2d");
    if (!srcCtx) return null;
    const srcData = srcCtx.getImageData(0, 0, canvas.width, canvas.height);
    const dstData = ctx.getImageData(0, 0, offscreen.width, offscreen.height);
    for (let i = 0; i < srcData.data.length; i += 4) {
      if (srcData.data[i + 3] > 10) {
        // 有内容的区域 → 白色
        dstData.data[i] = 255;
        dstData.data[i + 1] = 255;
        dstData.data[i + 2] = 255;
        dstData.data[i + 3] = 255;
      }
      // 透明区域保持黑色（已在背景填充）
    }
    ctx.putImageData(dstData, 0, 0);

    const dataUrl = offscreen.toDataURL("image/png");
    const byteString = atob(dataUrl.split(",")[1]);
    const ab = new ArrayBuffer(byteString.length);
    const ia = new Uint8Array(ab);
    for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
    return new File([ab], "mask.png", { type: "image/png" });
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!prompt.trim()) return;
    const maskFile = exportMaskAsFile();
    if (!maskFile) return;
    setSubmitting(true);
    try {
      await onSubmit(maskFile, prompt.trim());
    } finally {
      setSubmitting(false);
    }
  }, [prompt, exportMaskAsFile, onSubmit]);

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="flex max-h-[95dvh] w-full max-w-4xl flex-col gap-4 overflow-hidden p-5 sm:p-6">
        <DialogHeader className="shrink-0">
          <DialogTitle className="text-base font-semibold">遮罩编辑</DialogTitle>
        </DialogHeader>

        {/* 工具栏 */}
        <div className="flex shrink-0 flex-wrap items-center gap-3">
          <Button
            variant={tool === "brush" ? "default" : "outline"}
            size="sm"
            className="h-8 gap-1.5 text-xs"
            onClick={() => setTool("brush")}
          >
            <Paintbrush className="size-3.5" />
            笔刷
          </Button>
          <Button
            variant={tool === "eraser" ? "default" : "outline"}
            size="sm"
            className="h-8 gap-1.5 text-xs"
            onClick={() => setTool("eraser")}
          >
            <Eraser className="size-3.5" />
            橡皮擦
          </Button>
          <div className="flex items-center gap-2">
            <span className="text-xs text-stone-500">大小</span>
            <input
              type="range"
              min={MIN_BRUSH}
              max={MAX_BRUSH}
              value={brushSize}
              onChange={(e) => setBrushSize(Number(e.target.value))}
              className="w-24 accent-stone-800"
            />
            <span className="w-6 text-xs tabular-nums text-stone-500">{brushSize}</span>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="ml-auto h-8 gap-1.5 text-xs text-stone-600"
            onClick={handleClear}
          >
            <RotateCcw className="size-3.5" />
            清除
          </Button>
        </div>

        {/* 画布区域 */}
        <div className="relative min-h-0 flex-1 overflow-auto rounded-lg border border-stone-200 bg-stone-100">
          <div ref={canvasWrapRef} className="relative inline-block w-full">
            {/* 原图底层 */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={imageDataUrl}
              alt="待编辑图片"
              className="block h-auto w-full select-none"
              draggable={false}
            />
            {/* 遮罩画布叠层 */}
            <canvas
              ref={canvasRef}
              className="absolute inset-0 h-full w-full"
              style={{
                opacity: 0.55,
                cursor: "none",
                touchAction: "none",
              }}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerLeave={() => { handlePointerUp(); setCursorPos(null); }}
            />
            {/* ChatGPT 风格光标：虚线圆 + 浅蓝色半透明填充 */}
            {cursorPos && (
              <div
                aria-hidden
                style={{
                  position: "absolute",
                  left: cursorPos.x,
                  top: cursorPos.y,
                  width: brushSize,
                  height: brushSize,
                  transform: "translate(-50%, -50%)",
                  borderRadius: "50%",
                  border: tool === "eraser"
                    ? "2px dashed rgba(251,113,133,0.9)"
                    : "2px dashed rgba(255,255,255,0.95)",
                  boxShadow: tool === "eraser"
                    ? "0 0 0 1.5px rgba(159,18,57,0.5)"
                    : "0 0 0 1.5px rgba(30,64,175,0.4)",
                  backgroundColor: tool === "eraser"
                    ? "rgba(254,205,211,0.25)"
                    : "rgba(147,210,252,0.35)",
                  pointerEvents: "none",
                  zIndex: 20,
                }}
              />
            )}
          </div>
        </div>

        <p className="shrink-0 text-xs text-stone-500">
          用笔刷涂抹要修改的区域（<span className="font-medium text-sky-600">蓝色高亮 = 编辑区域</span>），然后输入描述并点击生成。
        </p>

        {/* Prompt 输入 */}
        <div className="flex shrink-0 flex-col gap-2">
          <Textarea
            placeholder="描述要如何修改遮罩区域..."
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            className="min-h-[72px] resize-none text-sm"
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !submitting) {
                void handleSubmit();
              }
            }}
          />
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" className="h-9 text-sm" onClick={onClose} disabled={submitting}>
              取消
            </Button>
            <Button
              size="sm"
              className="h-9 text-sm"
              onClick={() => void handleSubmit()}
              disabled={submitting || !prompt.trim() || !canvasReady}
            >
              {submitting ? "生成中..." : "生成"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
