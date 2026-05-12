"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Circle, Eraser, ImagePlus, Paintbrush, RotateCcw, X } from "lucide-react";
import { toast } from "sonner";

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
  onSubmit: (annotatedImageFile: File, prompt: string, refImages: File[]) => void | Promise<void>;
};

const MIN_BRUSH = 8;
const MAX_BRUSH = 80;
const DEFAULT_BRUSH = 28;
const RED_ANNOTATION_COLOR = "rgba(239, 68, 68, 0.95)";
const BLUE_ANNOTATION_COLOR = "rgba(59, 130, 246, 0.95)";
const RED_ANNOTATION_FILL = "rgba(239, 68, 68, 0.12)";
const BLUE_ANNOTATION_FILL = "rgba(59, 130, 246, 0.12)";

type EditorTool = "brush" | "ellipse" | "eraser";
type AnnotationColor = "red" | "blue";

export function MaskEditorDialog({ open, imageDataUrl, defaultPrompt = "", availableImages = [], onClose, onSubmit }: MaskEditorDialogProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const canvasWrapRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const drawingRef = useRef(false);
  const lastPosRef = useRef<{ x: number; y: number } | null>(null);
  const toolRef = useRef<EditorTool>("brush");
  const colorRef = useRef<AnnotationColor>("red");
  const ellipseStartRef = useRef<{ x: number; y: number } | null>(null);
  const canvasSnapshotRef = useRef<ImageData | null>(null);

  const [tool, setTool] = useState<EditorTool>("brush");
  const [annotationColor, setAnnotationColor] = useState<AnnotationColor>("red");
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
      setTool("brush");
      setAnnotationColor("red");
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

  useEffect(() => {
    colorRef.current = annotationColor;
  }, [annotationColor]);

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

  const getAnnotationStrokeStyle = useCallback((value: AnnotationColor) => (
    value === "red" ? RED_ANNOTATION_COLOR : BLUE_ANNOTATION_COLOR
  ), []);

  const getAnnotationFillStyle = useCallback((value: AnnotationColor) => (
    value === "red" ? RED_ANNOTATION_FILL : BLUE_ANNOTATION_FILL
  ), []);

  const drawBrush = useCallback((canvas: HTMLCanvasElement, x: number, y: number, fromX?: number, fromY?: number) => {
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const scaledBrush = brushSize * (canvas.width / canvas.getBoundingClientRect().width);
    ctx.save();
    ctx.globalCompositeOperation = toolRef.current === "eraser" ? "destination-out" : "source-over";
    ctx.fillStyle = getAnnotationStrokeStyle(colorRef.current);
    ctx.strokeStyle = getAnnotationStrokeStyle(colorRef.current);
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
  }, [brushSize, getAnnotationStrokeStyle]);

  const drawEllipse = useCallback((
    canvas: HTMLCanvasElement,
    start: { x: number; y: number },
    end: { x: number; y: number },
  ) => {
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const radiusX = Math.abs(end.x - start.x) / 2;
    const radiusY = Math.abs(end.y - start.y) / 2;
    if (radiusX < 1 || radiusY < 1) {
      return;
    }
    const centerX = Math.min(start.x, end.x) + radiusX;
    const centerY = Math.min(start.y, end.y) + radiusY;
    const scaledBrush = Math.max(2, brushSize * 0.22 * (canvas.width / canvas.getBoundingClientRect().width));
    ctx.save();
    ctx.globalCompositeOperation = "source-over";
    ctx.strokeStyle = getAnnotationStrokeStyle(colorRef.current);
    ctx.fillStyle = getAnnotationFillStyle(colorRef.current);
    ctx.lineWidth = scaledBrush;
    ctx.beginPath();
    ctx.ellipse(centerX, centerY, radiusX, radiusY, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }, [brushSize, getAnnotationFillStyle, getAnnotationStrokeStyle]);

  const handlePointerDown = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.setPointerCapture(e.pointerId);
    drawingRef.current = true;
    const pos = getCanvasPos(canvas, e.clientX, e.clientY);
    lastPosRef.current = pos;
    if (toolRef.current === "ellipse") {
      const ctx = canvas.getContext("2d");
      canvasSnapshotRef.current = ctx?.getImageData(0, 0, canvas.width, canvas.height) ?? null;
      ellipseStartRef.current = pos;
      return;
    }
    drawBrush(canvas, pos.x, pos.y);
  }, [drawBrush, getCanvasPos]);

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
    if (toolRef.current === "ellipse") {
      const ctx = canvas.getContext("2d");
      const snapshot = canvasSnapshotRef.current;
      const ellipseStart = ellipseStartRef.current;
      if (!ctx || !snapshot || !ellipseStart) {
        return;
      }
      ctx.putImageData(snapshot, 0, 0);
      drawEllipse(canvas, ellipseStart, pos);
      return;
    }
    const last = lastPosRef.current;
    drawBrush(canvas, pos.x, pos.y, last?.x, last?.y);
    lastPosRef.current = pos;
  }, [drawBrush, drawEllipse, getCanvasPos]);

  const handlePointerUp = useCallback((e?: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    const ellipseStart = ellipseStartRef.current;
    if (canvas && ellipseStart && drawingRef.current && toolRef.current === "ellipse" && e) {
      const ctx = canvas.getContext("2d");
      const snapshot = canvasSnapshotRef.current;
      const pos = getCanvasPos(canvas, e.clientX, e.clientY);
      if (ctx && snapshot) {
        ctx.putImageData(snapshot, 0, 0);
        drawEllipse(canvas, ellipseStart, pos);
      }
    }
    drawingRef.current = false;
    lastPosRef.current = null;
    ellipseStartRef.current = null;
    canvasSnapshotRef.current = null;
  }, [drawEllipse, getCanvasPos]);

  const handleClear = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx?.clearRect(0, 0, canvas.width, canvas.height);
  }, []);

  const buildAnnotationSummary = useCallback((canvas: HTMLCanvasElement) => {
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return { hasBlue: false, hasRed: false };
    }
    const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
    let hasRed = false;
    let hasBlue = false;
    for (let index = 0; index < data.length; index += 4) {
      const alpha = data[index + 3];
      if (alpha <= 0) {
        continue;
      }
      const red = data[index];
      const blue = data[index + 2];
      if (red >= blue + 20) {
        hasRed = true;
      } else if (blue >= red + 20) {
        hasBlue = true;
      }
      if (hasRed && hasBlue) {
        break;
      }
    }
    return { hasBlue, hasRed };
  }, []);

  const exportAnnotatedImageAsFile = useCallback((): { file: File; hasBlue: boolean; hasRed: boolean } | null => {
    const canvas = canvasRef.current;
    const img = imageRef.current;
    if (!canvas || !img) return null;
    const offscreen = document.createElement("canvas");
    offscreen.width = canvas.width;
    offscreen.height = canvas.height;
    const ctx = offscreen.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    ctx.drawImage(canvas, 0, 0);

    const { hasBlue, hasRed } = buildAnnotationSummary(canvas);
    const dataUrl = offscreen.toDataURL("image/png");
    const byteString = atob(dataUrl.split(",")[1]);
    const ab = new ArrayBuffer(byteString.length);
    const ia = new Uint8Array(ab);
    for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
    return {
      file: new File([ab], "annotated-edit.png", { type: "image/png" }),
      hasBlue,
      hasRed,
    };
  }, [buildAnnotationSummary]);

  const buildSubmissionPrompt = useCallback((value: string, hasRed: boolean, hasBlue: boolean) => {
    const instruction = value.trim();
    if (!instruction) {
      return "";
    }
    const parts = [
      "请基于上传的带标注截图进行图生图编辑。",
    ];
    if (hasRed) {
      parts.push(`请把红色标注出来的区域修改为：${instruction}。`);
    } else {
      parts.push(`请根据用户要求完成修改：${instruction}。`);
    }
    if (hasBlue) {
      parts.push("蓝色标注区域代表风格、材质、配色或造型参考，请参考这些区域，但不要把蓝色标记本身生成为最终图像。");
    }
    parts.push("除非用户描述明确要求，否则尽量保持未标注区域不变，并去掉所有圈线、涂抹和标记。");
    return parts.join(" ");
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!prompt.trim()) return;
    const annotated = exportAnnotatedImageAsFile();
    if (!annotated) return;
    if (!annotated.hasRed && !annotated.hasBlue) {
      toast.error("请先在图片上用红色或蓝色做标注");
      return;
    }
    const submissionPrompt = buildSubmissionPrompt(prompt, annotated.hasRed, annotated.hasBlue);
    if (!submissionPrompt) {
      return;
    }
    setSubmitting(true);
    try {
      await onSubmit(annotated.file, submissionPrompt, refImages.map((r) => r.file));
    } finally {
      setSubmitting(false);
    }
  }, [buildSubmissionPrompt, exportAnnotatedImageAsFile, onSubmit, prompt, refImages]);

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="flex max-h-[95dvh] w-full max-w-4xl flex-col gap-4 overflow-hidden p-5 sm:p-6">
        <DialogHeader className="shrink-0">
          <DialogTitle className="text-base font-semibold">编辑图片</DialogTitle>
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
            variant={tool === "ellipse" ? "default" : "outline"}
            size="sm"
            className="h-8 gap-1.5 text-xs"
            onClick={() => setTool("ellipse")}
          >
            <Circle className="size-3.5" />
            椭圆
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
          <div className="flex items-center gap-1">
            <span className="text-xs text-stone-500">颜色</span>
            <Button
              variant={annotationColor === "red" ? "default" : "outline"}
              size="sm"
              className="h-8 gap-1.5 text-xs"
              onClick={() => setAnnotationColor("red")}
              disabled={tool === "eraser"}
            >
              <span className="size-2 rounded-full bg-red-500" />
              红色
            </Button>
            <Button
              variant={annotationColor === "blue" ? "default" : "outline"}
              size="sm"
              className="h-8 gap-1.5 text-xs"
              onClick={() => setAnnotationColor("blue")}
              disabled={tool === "eraser"}
            >
              <span className="size-2 rounded-full bg-blue-500" />
              蓝色
            </Button>
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
                    : annotationColor === "red"
                      ? "2px dashed rgba(239,68,68,0.95)"
                      : "2px dashed rgba(59,130,246,0.95)",
                  boxShadow: tool === "eraser"
                    ? "0 0 0 1.5px rgba(159,18,57,0.5)"
                    : annotationColor === "red"
                      ? "0 0 0 1.5px rgba(153,27,27,0.35)"
                      : "0 0 0 1.5px rgba(30,64,175,0.4)",
                  backgroundColor: tool === "eraser"
                    ? "rgba(254,205,211,0.25)"
                    : annotationColor === "red"
                      ? "rgba(252,165,165,0.28)"
                      : "rgba(147,210,252,0.35)",
                  pointerEvents: "none",
                  zIndex: 20,
                }}
              />
            )}
          </div>
        </div>

        <p className="shrink-0 text-xs text-stone-500">
          红色标注表示 <span className="font-medium text-red-500">要修改的区域</span>，蓝色标注表示
          <span className="font-medium text-blue-500"> 风格 / 参考提示区域</span>。导出时会上传带标注截图做图生图参考。
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
            placeholder="例如：把红色圈起来的葡萄帽改成草莓帽，蓝色区域的光感和材质作为参考"
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
