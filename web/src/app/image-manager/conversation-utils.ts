"use client";

import type { ImageConversation, ImageConversationMode, ImageTurnStatus } from "@/store/image-conversations";

export type ConversationImageAsset = {
  id: string;
  src: string;
  fileName: string;
};

function sanitizeFileStem(value: string): string {
  const normalized = value
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "-")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^[-.]+|[-.]+$/g, "");
  return normalized || "image";
}

function imageExtensionFromMimeType(mimeType: string | undefined): string {
  if (mimeType === "image/jpeg") {
    return "jpg";
  }
  if (mimeType === "image/webp") {
    return "webp";
  }
  return "png";
}

export function getConversationStatus(conversation: ImageConversation): ImageTurnStatus {
  const lastTurn = conversation.turns[conversation.turns.length - 1];
  return lastTurn?.status ?? "success";
}

export function getConversationMode(conversation: ImageConversation): ImageConversationMode {
  return conversation.turns[conversation.turns.length - 1]?.mode ?? "generate";
}

export function getConversationPrompt(conversation: ImageConversation): string {
  return conversation.turns[conversation.turns.length - 1]?.prompt ?? "";
}

export function getConversationModel(conversation: ImageConversation): string {
  return conversation.turns[conversation.turns.length - 1]?.model ?? "";
}

export function getConversationImageCount(conversation: ImageConversation) {
  return conversation.turns.reduce(
    (sum, turn) => sum + turn.images.filter((image) => image.status === "success" && image.b64_json).length,
    0,
  );
}

export function getConversationImages(conversation: ImageConversation) {
  const fileStem = sanitizeFileStem(conversation.title);
  return conversation.turns.flatMap((turn) =>
    turn.images
      .filter((image) => image.status === "success" && image.b64_json)
      .map((image) => ({
        id: image.id,
        src: `data:${image.mime_type || "image/png"};base64,${image.b64_json}`,
        fileName: `${fileStem}-${image.id}.${imageExtensionFromMimeType(image.mime_type)}`,
      })),
  );
}

export function getStatusBadgeVariant(status: ImageTurnStatus) {
  if (status === "error") return "danger" as const;
  if (status === "generating") return "warning" as const;
  if (status === "queued") return "info" as const;
  return "success" as const;
}

export function getModeLabel(mode: ImageConversationMode) {
  return mode === "edit" ? "编辑" : "生成";
}
