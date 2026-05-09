"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Eraser, ImagePlus, Paintbrush, RotateCcw, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

type AvailableImage = { dataUrl: string; id: string };

type MaskEditorDialogProps = {
  open: boolean;
  imageDataUrl: string;
  defaultPrompt?: string;
  /** 当前对话已生成的图，可直接选为参考图 */
  availableImages?: AvailableImage[];
  onClose: () => void;
  onSubmit: (maskFile: File, prompt: string, refImages: File[]) => void | Promise<void>;
};

const MIN_BRUSH = 8;
const MAX_BRUSH = 80;
const DEFAULT_BRUSH = 28;

export function MaskEditorDialog({ open, imageDataUrl, defaultPrompt = "", availableImages = [], onClose, onSubmit }: MaskEditorDialogProps) {
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
  const [loadedImageDataUrl, setLoadedImageDataUrl] = useState<string>("");
  // canvasReady 派生自 loadedImageDataUrl，无需 effect 内同步 setState
  const canvasReady = open && loadedImageDataUrl === imageDataUrl;
  // 自定义光标位置（相对于画布 wrapper）
  const [cursorPos, setCursorPos] = useState<{ x: number; y: number } | null>(null);
  // 参考图
  const [refImages, setRefImages] = useState<{ file: File; preview: string }[]>([]);
  const refInputRef = useRef<HTMLInputElement>(null);
  // 追踪 open / defaultPrompt 的前一值，用于渲染期间检测变化（React 19 推荐方式）
  const [prevOpen, setPrevOpen] = useState(open);
  const [prevDefaultPrompt, setPrevDefaultPrompt] = useState(defaultPrompt);
  // 追踪当前 refImages，供关闭时清理 object URL——不在渲染体中赋值（React 19 禁止），
  // 改为在无 deps useEffect 中同步，保证每次渲染后都是最新值。
  const refImagesRef = useRef(refImages);

  // 渲染期间 setState —— React 19 推荐的「属性变化时重置 state」方式。
  // 不在 effect 内调用，避免 "Calling setState synchronously within an effect" 警告。
  if (open !== prevOpen) {
    setPrevOpen(open);
    setLoadedImageDataUrl(""); // 重置 canvasReady 派生状态
    if (open) {
      setPrompt(defaultPrompt);
      setPrevDefaultPrompt(defaultPrompt);
      setRefImages([]);
    }
  }
  if (open && defaultPrompt !== prevDefaultPrompt) {
    setPrevDefaultPrompt(defaultPrompt);
    setPrompt(defaultPrompt);
  }

  /** 从 File 对象追加参考图（通用，最多到 6 张）*/
  const appendRefFiles = useCallback((files: File[]) => {
    if (!files.length) return;
    setRefImages((prev) => {
      const remaining = 6 - prev.length;
      const toAdd = files.slice(0, remaining).map((f) => ({
        file: f,
        preview: URL.createObjectURL(f),
      }));
      return [...prev, ...toAdd];
    });
  }, []);

  const handleRefImageAdd = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    appendRefFiles(files);
    e.target.value = "";
  }, [appendRefFiles]);

  /** 从历史生成图（dataUrl）追加参考图 */
  const handlePickAvailableImage = useCallback((img: AvailableImage) => {
    setRefImages((prev) => {
      if (prev.length >= 6) return prev;
      // 已选过则不重复添加（同 dataUrl）
      if (prev.some((r) => r.preview === img.dataUrl)) return prev;
      // dataUrl 直接当 preview，同时用它构造 File
      const byteString = atob(img.dataUrl.split(",")[1] ?? "");
      const mimeMatch = /data:(.*?);base64/.exec(img.dataUrl);
      const mime = mimeMatch?.[1] ?? "image/png";
      const ab = new ArrayBuffer(byteString.length);
      const ia = new Uint8Array(ab);
      for (let i = 0; i < byteString.length; i++) ia[i] = byteString.codePointAt(i) ?? 0;
      const file = new File([ab], `ref-${img.id}.png`, { type: mime });
      return [...prev, { file, preview: img.dataUrl }];
    });
  }, []);

  /** Ctrl+V / Cmd+V 粘贴图片 */
  const handlePaste = useCallback((e: React.ClipboardEvent | ClipboardEvent) => {
    if (!open) return;
    const items = Array.from((e as ClipboardEvent).clipboardData?.items ?? []);
    const imageItems = items.filter((item) => item.type.startsWith("image/"));
    if (!imageItems.length) return;
    e.preventDefault();
    const files = imageItems.map((item) => item.getAsFile()).filter((f): f is File => f !== null);
    appendRefFiles(files);
  }, [open, appendRefFiles]);

  // 监听全局粘贴（对话框打开时）
  useEffect(() => {
    if (!open) return;
    const handler = (e: ClipboardEvent) => handlePaste(e);
    document.addEventListener("paste", handler);
    return () => document.removeEventListener("paste", handler);
  }, [open, handlePaste]);

  const handleRefImageRemove = useCallback((preview: string) => {
    setRefImages((prev) => {
      const target = prev.find((r) => r.preview === preview);
      if (target) URL.revokeObjectURL(target.preview);
      return prev.filter((r) => r.preview !== preview);
    });
  }, []);

  // 同步 toolRef 以避免闭包陈旧引用
  useEffect(() => {
    toolRef.current = tool;
  }, [tool]);

  // 保持 refImagesRef 始终指向最新 refImages（每次渲染后执行，无 deps）
  // 不能在渲染体中直接赋值（React 19 报 "Cannot update ref during render"）
  useEffect(() => {
    refImagesRef.current = refImages;
  });

  // 对话框关闭时清理 object URL（纯副作用，不调用 setState）
  useEffect(() => {
    if (!open) {
      refImagesRef.current.forEach((r) => {
        if (r.preview.startsWith("blob:")) URL.revokeObjectURL(r.preview);
      });
    }
  }, [open]);

  // 异步加载图片并初始化 canvas（setState 在 onload 回调中，符合 React 19 规范）
  useEffect(() => {
    if (!open) return;
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
      setLoadedImageDataUrl(imageDataUrl);
    };
    img.src = imageDataUrl;
  }, [open, imageDataUrl]);

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

    // Step 1：对用户笔刷 canvas 做羽化（blur）处理，使边缘自然过渡。
    // 羽化半径与图片宽度成正比，保证在不同分辨率下视觉一致。
    const blurRadius = Math.max(4, Math.round(canvas.width / 120));
    const blurred = document.createElement("canvas");
    blurred.width = canvas.width;
    blurred.height = canvas.height;
    const blurCtx = blurred.getContext("2d");
    if (!blurCtx) return null;
    blurCtx.filter = `blur(${blurRadius}px)`;
    blurCtx.drawImage(canvas, 0, 0);
    blurCtx.filter = "none";

    // Step 2：合成最终 mask。
    // API 约定：白色 = 待编辑区域，黑色 = 保留区域。
    // 关键改进：用羽化后的 alpha 值映射为灰度（而非硬二值化），
    // 让边界区域呈现灰色渐变 → API 在边缘实现自然融合，与官网效果一致。
    const offscreen = document.createElement("canvas");
    offscreen.width = canvas.width;
    offscreen.height = canvas.height;
    const ctx = offscreen.getContext("2d");
    if (!ctx) return null;

    ctx.fillStyle = "black";
    ctx.fillRect(0, 0, offscreen.width, offscreen.height);

    const srcData = blurCtx.getImageData(0, 0, canvas.width, canvas.height);
    const dstData = ctx.getImageData(0, 0, offscreen.width, offscreen.height);
    for (let i = 0; i < srcData.data.length; i += 4) {
      const alpha = srcData.data[i + 3]; // 羽化后的 alpha（0‒255）
      // alpha 直接作为灰度强度：核心区域近白，边缘渐变为黑，保留保留区域为纯黑
      dstData.data[i]     = alpha; // R
      dstData.data[i + 1] = alpha; // G
      dstData.data[i + 2] = alpha; // B
      dstData.data[i + 3] = 255;   // A（始终不透明）
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
      await onSubmit(maskFile, prompt.trim(), refImages.map((r) => r.file));
    } finally {
      setSubmitting(false);
    }
  }, [prompt, exportMaskAsFile, onSubmit, refImages]);

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

        {/* 参考图上传区 */}
        <div className="flex shrink-0 flex-col gap-2">
          <div className="flex items-center gap-2">
            <span className="text-xs text-stone-500">参考图（可选，最多 6 张）</span>
            {refImages.length < 6 && (
              <>
                <input
                  ref={refInputRef}
                  type="file"
                  accept="image/*"
                  multiple
                  className="hidden"
                  onChange={handleRefImageAdd}
                />
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1 text-xs"
                  onClick={() => refInputRef.current?.click()}
                  disabled={submitting}
                >
                  <ImagePlus className="size-3.5" />
                  上传
                </Button>
              </>
            )}
            <span className="text-xs text-stone-400">或 Ctrl+V 粘贴</span>
          </div>

          {/* 从已生成图中选择 */}
          {availableImages.length > 0 && refImages.length < 6 && (
            <div className="flex flex-col gap-1.5">
              <span className="text-xs text-stone-400">从已生成图中选择：</span>
              <div className="flex flex-wrap gap-1.5">
                {availableImages.map((img) => {
                  const selected = refImages.some((r) => r.preview === img.dataUrl);
                  return (
                    <button
                      key={img.id}
                      type="button"
                      onClick={() => handlePickAvailableImage(img)}
                      disabled={submitting || (selected) || refImages.length >= 6}
                      className={`relative size-14 shrink-0 overflow-hidden rounded-md border-2 transition-all ${
                        selected
                          ? "border-sky-500 opacity-60 cursor-default"
                          : "border-transparent hover:border-sky-400 cursor-pointer"
                      }`}
                      aria-label={selected ? "已选择" : "选为参考图"}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={img.dataUrl} alt="历史图" className="size-full object-cover" />
                      {selected && (
                        <div className="absolute inset-0 flex items-center justify-center bg-sky-500/20">
                          <span className="text-[10px] font-medium text-sky-700">已选</span>
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {refImages.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {refImages.map((r) => (
                <div key={r.preview} className="group relative size-16 shrink-0 overflow-hidden rounded-md border border-stone-200">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={r.preview} alt="参考图" className="size-full object-cover" />
                  <button
                    type="button"
                    onClick={() => handleRefImageRemove(r.preview)}
                    className="absolute right-0.5 top-0.5 flex size-4 items-center justify-center rounded-full bg-black/60 text-white opacity-0 transition-opacity group-hover:opacity-100"
                    aria-label="删除参考图"
                  >
                    <X className="size-2.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

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
