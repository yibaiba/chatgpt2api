"use client";

import type { ImageModel } from "@/lib/api";
import { httpRequest } from "@/lib/request";
import type { UserRole } from "@/lib/auth-types";

export type ImageConversationMode = "generate" | "edit";

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

export type ImageConversationStatus = "generating" | "success" | "error";

export type ImageConversation = {
  id: string;
  title: string;
  prompt: string;
  model: ImageModel;
  mode?: ImageConversationMode;
  referenceImages?: StoredReferenceImage[];
  count: number;
  images: StoredImage[];
  createdAt: string;
  updatedAt?: string;
  status: ImageConversationStatus;
  error?: string;
  ownerRole: UserRole;
  ownerId: string;
  ownerName: string;
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

function normalizeConversation(conversation: ImageConversation): ImageConversation {
  return {
    ...conversation,
    mode: conversation.mode === "edit" ? "edit" : "generate",
    images: (conversation.images || []).map(normalizeStoredImage),
    updatedAt: String(conversation.updatedAt || conversation.createdAt || "").trim() || conversation.createdAt,
    ownerRole: conversation.ownerRole === "admin" ? "admin" : "user",
    ownerId: String(conversation.ownerId || "").trim() || (conversation.ownerRole === "admin" ? "admin" : "unknown"),
    ownerName:
      String(conversation.ownerName || "").trim() ||
      (conversation.ownerRole === "admin" ? "管理员" : "普通用户"),
  };
}

export async function listImageConversations(): Promise<ImageConversation[]> {
  const data = await httpRequest<{ items: ImageConversation[] }>("/api/image-conversations");
  return data.items
    .map(normalizeConversation)
    .sort((a, b) => (b.updatedAt || b.createdAt).localeCompare(a.updatedAt || a.createdAt));
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
