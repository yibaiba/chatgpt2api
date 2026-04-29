"use client";

import localforage from "localforage";

import type { UserRole } from "@/lib/auth-types";
import type { ImageGenerationRoute, ImageModel } from "@/lib/api";
import {
  isImageAspectRatio,
  isImageOutputQuality,
  type ImageAspectRatio,
  type ImageOutputQuality,
} from "@/lib/image-options";
import { httpRequest } from "@/lib/request";

export type ImageConversationMode = "generate" | "edit";
export type ImageTurnStatus = "queued" | "generating" | "success" | "error";

export type StoredReferenceImage = {
  name: string;
  type: string;
  dataUrl: string;
};

export type StoredImage = {
  id: string;
  status?: "loading" | "success" | "error";
  b64_json?: string;
  mime_type?: string;
  error?: string;
  job_id?: string;
  generation_route?: ImageGenerationRoute;
};

export type ImageTurn = {
  id: string;
  prompt: string;
  model: ImageModel;
  mode: ImageConversationMode;
  aspectRatio?: ImageAspectRatio;
  outputQuality?: ImageOutputQuality;
  referenceImages: StoredReferenceImage[];
  count: number;
  images: StoredImage[];
  createdAt: string;
  status: ImageTurnStatus;
  error?: string;
};

export type ImageConversation = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  turns: ImageTurn[];
  ownerRole: UserRole;
  ownerId: string;
  ownerName: string;
};

export type ImageConversationStats = {
  queued: number;
  running: number;
};

const BROWSER_IMAGE_HISTORY_STORAGE_PREFIX = "chatgpt2api_image_history";
const browserImageHistoryStorage = localforage.createInstance({
  name: "chatgpt2api",
  storeName: "image_history",
});

function isImageGenerationRoute(value: unknown): value is ImageGenerationRoute {
  return value === "regular" || value === "thinking" || value === "fallback";
}

function normalizeStoredImage(image: StoredImage): StoredImage {
  const normalizedMimeType = image.mime_type || "image/png";
  const normalizedJobId = typeof image.job_id === "string" && image.job_id.trim() ? image.job_id.trim() : undefined;
  if (image.status === "loading" || image.status === "error" || image.status === "success") {
    return {
      ...image,
      mime_type: image.b64_json ? normalizedMimeType : image.mime_type,
      job_id: normalizedJobId,
      generation_route: isImageGenerationRoute(image.generation_route) ? image.generation_route : undefined,
    };
  }
  return {
    ...image,
    status: image.b64_json ? "success" : "loading",
    mime_type: image.b64_json ? normalizedMimeType : image.mime_type,
    job_id: normalizedJobId,
    generation_route: isImageGenerationRoute(image.generation_route) ? image.generation_route : undefined,
  };
}

function normalizeReferenceImage(image: StoredReferenceImage): StoredReferenceImage {
  return {
    name: image.name || "reference.png",
    type: image.type || "image/png",
    dataUrl: image.dataUrl,
  };
}

function dataUrlMimeType(dataUrl: string) {
  const match = dataUrl.match(/^data:(.*?);base64,/);
  return match?.[1] || "image/png";
}

function getLegacyReferenceImages(source: Record<string, unknown>): StoredReferenceImage[] {
  if (Array.isArray(source.referenceImages)) {
    return source.referenceImages
      .filter((image): image is StoredReferenceImage => {
        if (!image || typeof image !== "object") {
          return false;
        }
        const candidate = image as StoredReferenceImage;
        return typeof candidate.dataUrl === "string" && candidate.dataUrl.length > 0;
      })
      .map(normalizeReferenceImage);
  }

  if (source.sourceImage && typeof source.sourceImage === "object") {
    const image = source.sourceImage as { dataUrl?: unknown; fileName?: unknown };
    if (typeof image.dataUrl === "string" && image.dataUrl) {
      return [
        {
          name: typeof image.fileName === "string" && image.fileName ? image.fileName : "reference.png",
          type: dataUrlMimeType(image.dataUrl),
          dataUrl: image.dataUrl,
        },
      ];
    }
  }

  return [];
}

function normalizeTurn(turn: ImageTurn & Record<string, unknown>): ImageTurn {
  const normalizedImages = Array.isArray(turn.images) ? turn.images.map(normalizeStoredImage) : [];
  const derivedStatus: ImageTurnStatus =
    normalizedImages.some((image) => image.status === "loading")
      ? "generating"
      : normalizedImages.some((image) => image.status === "error")
        ? "error"
        : "success";

  return {
    id: String(turn.id || `${Date.now()}`),
    prompt: String(turn.prompt || ""),
    model: (turn.model as ImageModel) || "gpt-image-2",
    mode: turn.mode === "edit" ? "edit" : "generate",
    aspectRatio: isImageAspectRatio(turn.aspectRatio) ? turn.aspectRatio : undefined,
    outputQuality: isImageOutputQuality(turn.outputQuality) ? turn.outputQuality : undefined,
    referenceImages: getLegacyReferenceImages(turn),
    count: Math.max(1, Number(turn.count || normalizedImages.length || 1)),
    images: normalizedImages,
    createdAt: String(turn.createdAt || new Date().toISOString()),
    status:
      turn.status === "queued" ||
      turn.status === "generating" ||
      turn.status === "success" ||
      turn.status === "error"
        ? turn.status
        : derivedStatus,
    error: typeof turn.error === "string" ? turn.error : undefined,
  };
}

function normalizeConversation(conversation: ImageConversation & Record<string, unknown>): ImageConversation {
  const turns = Array.isArray(conversation.turns)
    ? conversation.turns.map((turn) => normalizeTurn(turn as ImageTurn & Record<string, unknown>))
    : [];
  const lastTurn = turns.length > 0 ? turns[turns.length - 1] : null;

  return {
    id: String(conversation.id || `${Date.now()}`),
    title: String(conversation.title || ""),
    createdAt: String(conversation.createdAt || lastTurn?.createdAt || new Date().toISOString()),
    updatedAt: String(conversation.updatedAt || lastTurn?.createdAt || new Date().toISOString()),
    turns,
    ownerRole: conversation.ownerRole === "admin" ? "admin" : "user",
    ownerId: String(conversation.ownerId || "").trim() || (conversation.ownerRole === "admin" ? "admin" : "unknown"),
    ownerName:
      String(conversation.ownerName || "").trim() ||
      (conversation.ownerRole === "admin" ? "管理员" : "普通用户"),
  };
}

function sortImageConversations(conversations: ImageConversation[]): ImageConversation[] {
  return [...conversations].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

function normalizeBrowserImageConversations(value: unknown): ImageConversation[] {
  if (value == null) {
    return [];
  }
  if (!Array.isArray(value)) {
    throw new Error("浏览器中的图片历史数据格式无效，请清空本地记录后重试");
  }
  return sortImageConversations(
    value
      .filter((item): item is ImageConversation & Record<string, unknown> => !!item && typeof item === "object")
      .map(normalizeConversation),
  );
}

async function readBrowserImageConversations(storageKey: string): Promise<ImageConversation[]> {
  if (typeof window === "undefined") {
    return [];
  }
  const storedValue = await browserImageHistoryStorage.getItem<unknown>(storageKey);
  if (storedValue != null) {
    return normalizeBrowserImageConversations(storedValue);
  }

  const legacyRaw = window.localStorage.getItem(storageKey);
  if (!legacyRaw) {
    return [];
  }
  let parsedLegacyValue: unknown;
  try {
    parsedLegacyValue = JSON.parse(legacyRaw);
  } catch {
    throw new Error("浏览器中的图片历史数据已损坏，请清空本地记录后重试");
  }
  const normalized = normalizeBrowserImageConversations(parsedLegacyValue);
  await browserImageHistoryStorage.setItem(storageKey, normalized);
  window.localStorage.removeItem(storageKey);
  return normalized;
}

async function writeBrowserImageConversations(storageKey: string, conversations: ImageConversation[]): Promise<void> {
  if (typeof window === "undefined") {
    return;
  }
  const normalized = sortImageConversations(conversations.map(normalizeConversation));
  if (normalized.length === 0) {
    await browserImageHistoryStorage.removeItem(storageKey);
    window.localStorage.removeItem(storageKey);
    return;
  }
  await browserImageHistoryStorage.setItem(storageKey, normalized);
  window.localStorage.removeItem(storageKey);
}

export function buildBrowserImageHistoryStorageKey(ownerRole: UserRole, ownerId: string): string {
  const normalizedOwnerId = String(ownerId || "").trim() || (ownerRole === "admin" ? "admin" : "unknown");
  return `${BROWSER_IMAGE_HISTORY_STORAGE_PREFIX}:${ownerRole}:${normalizedOwnerId}`;
}

export async function listImageConversations(): Promise<ImageConversation[]> {
  const data = await httpRequest<{ items: Array<ImageConversation & Record<string, unknown>> }>("/api/image-conversations");
  return sortImageConversations(data.items.map(normalizeConversation));
}

export async function listBrowserImageConversations(storageKey: string): Promise<ImageConversation[]> {
  return readBrowserImageConversations(storageKey);
}

export async function saveImageConversations(conversations: ImageConversation[]): Promise<void> {
  for (const conversation of sortImageConversations(conversations.map(normalizeConversation))) {
    await saveImageConversation(conversation);
  }
}

export async function saveImageConversation(conversation: ImageConversation): Promise<void> {
  await httpRequest<{ item: ImageConversation }>("/api/image-conversations", {
    method: "POST",
    body: normalizeConversation(conversation),
  });
}

export async function saveBrowserImageConversation(
  storageKey: string,
  conversation: ImageConversation,
): Promise<void> {
  const normalizedConversation = normalizeConversation(conversation);
  const next = (await readBrowserImageConversations(storageKey)).filter((item) => item.id !== normalizedConversation.id);
  next.unshift(normalizedConversation);
  await writeBrowserImageConversations(storageKey, next);
}

export async function deleteImageConversation(id: string): Promise<void> {
  await httpRequest<{ ok: boolean }>(`/api/image-conversations/${id}`, {
    method: "DELETE",
  });
}

export async function deleteBrowserImageConversation(storageKey: string, id: string): Promise<void> {
  const next = (await readBrowserImageConversations(storageKey)).filter((conversation) => conversation.id !== id);
  await writeBrowserImageConversations(storageKey, next);
}

export async function clearImageConversations(): Promise<void> {
  await httpRequest<{ removed: number }>("/api/image-conversations", {
    method: "DELETE",
  });
}

export async function clearBrowserImageConversations(storageKey: string): Promise<void> {
  if (typeof window === "undefined") {
    return;
  }
  await browserImageHistoryStorage.removeItem(storageKey);
  window.localStorage.removeItem(storageKey);
}

export function getImageConversationStats(conversation: ImageConversation | null): ImageConversationStats {
  if (!conversation) {
    return { queued: 0, running: 0 };
  }

  return conversation.turns.reduce(
    (acc, turn) => {
      if (turn.status === "queued") {
        acc.queued += 1;
      } else if (turn.status === "generating") {
        acc.running += 1;
      }
      return acc;
    },
    { queued: 0, running: 0 },
  );
}
