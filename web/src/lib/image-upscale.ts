import type { ImageOutputQuality } from "@/lib/image-options";

const TARGET_LONG_EDGE: Record<Exclude<ImageOutputQuality, "original">, number> = {
  "2k": 2048,
  "4k": 4096,
};

function loadImage(dataUrl: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("图片解码失败"));
    image.src = dataUrl;
  });
}

export async function upscaleGeneratedImage(
  b64Json: string,
  mimeType: string | undefined,
  quality: ImageOutputQuality | undefined,
) {
  const normalizedMimeType = mimeType || "image/png";
  if (!b64Json || !quality || quality === "original" || typeof window === "undefined") {
    return {
      b64_json: b64Json,
      mime_type: normalizedMimeType,
    };
  }

  const image = await loadImage(`data:${normalizedMimeType};base64,${b64Json}`);
  const longEdge = Math.max(image.naturalWidth, image.naturalHeight);
  const targetLongEdge = TARGET_LONG_EDGE[quality];
  if (!Number.isFinite(longEdge) || longEdge <= 0 || longEdge >= targetLongEdge) {
    return {
      b64_json: b64Json,
      mime_type: normalizedMimeType,
    };
  }

  const scale = targetLongEdge / longEdge;
  const targetWidth = Math.max(1, Math.round(image.naturalWidth * scale));
  const targetHeight = Math.max(1, Math.round(image.naturalHeight * scale));
  const canvas = document.createElement("canvas");
  canvas.width = targetWidth;
  canvas.height = targetHeight;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("浏览器不支持本地高清放大");
  }

  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(image, 0, 0, targetWidth, targetHeight);

  const upscaledDataUrl = canvas.toDataURL("image/png");
  return {
    b64_json: upscaledDataUrl.split(",")[1] || b64Json,
    mime_type: "image/png",
  };
}
