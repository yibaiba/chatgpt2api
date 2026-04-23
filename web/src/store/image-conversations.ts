"use client";

import type { UserRole } from "@/lib/auth-types";
import type { ImageModel } from "@/lib/api";
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
};

export type ImageTurn = {
  id: string;
  prompt: string;
  model: ImageModel;
  mode: ImageConversationMode;
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

function normalizeStoredImage(image: StoredImage): StoredImage {
  const normalizedMimeType = image.mime_type || "image/png";
  if (image.status === "loading" || image.status === "error" || image.status === "success") {
    return {
      ...image,
      mime_type: image.b64_json ? normalizedMimeType : image.mime_type,
    };
  }
  return {
    ...image,
    status: image.b64_json ? "success" : "loading",
    mime_type: image.b64_json ? normalizedMimeType : image.mime_type,
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

export async function listImageConversations(): Promise<ImageConversation[]> {
  const data = await httpRequest<{ items: Array<ImageConversation & Record<string, unknown>> }>("/api/image-conversations");
  return sortImageConversations(data.items.map(normalizeConversation));
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

export async function deleteImageConversation(id: string): Promise<void> {
  await httpRequest<{ ok: boolean }>(`/api/image-conversations/${id}`, {
    method: "DELETE",
  });
}

export async function clearImageConversations(): Promise<void> {
  await httpRequest<{ removed: number }>("/api/image-conversations", {
    method: "DELETE",
  });
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
