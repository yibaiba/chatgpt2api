"use client";

import webConfig from "@/constants/common-env";
import { clearStoredAuthKey } from "@/store/auth";
import { clearPromptReviewStorage } from "@/lib/prompt-review-storage";

export type PromptReviewStreamResult = {
  finishReason: string | null;
  moderationError: string | null;
  text: string;
  threadId: string | null;
};

type PromptReviewStreamOptions = {
  model: string;
  prompt: string;
  signal?: AbortSignal;
  threadId?: string | null;
  onTextDelta?: (delta: string) => void;
  onThreadId?: (threadId: string) => void;
};

function redirectToLogin() {
  if (typeof window === "undefined" || window.location.pathname.startsWith("/login")) {
    return;
  }
  clearPromptReviewStorage();
  void clearStoredAuthKey().finally(() => {
    window.location.replace("/login");
  });
}

function readErrorMessage(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== "object") {
    return fallback;
  }
  const response = payload as {
    detail?: { error?: string };
    error?: string;
    message?: string;
  };
  return response.detail?.error || response.error || response.message || fallback;
}

function parseSseEvents(chunk: string) {
  return chunk
    .split("\n\n")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) =>
      part
        .split("\n")
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice(6))
        .join("\n"),
    )
    .filter(Boolean);
}

export async function streamPromptReview(options: PromptReviewStreamOptions): Promise<PromptReviewStreamResult> {
  const response = await fetch(`${webConfig.apiUrl.replace(/\/$/, "")}/v1/chat/completions`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: options.model,
      messages: [{ role: "user", content: options.prompt }],
      stream: true,
      ...(options.threadId ? { thread_id: options.threadId } : { threaded: true }),
    }),
    signal: options.signal,
  });
  if (response.status === 401) {
    redirectToLogin();
    throw new Error("登录已失效");
  }
  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    throw new Error(readErrorMessage(payload, `请求失败 (${response.status})`));
  }
  if (!response.body) {
    throw new Error("流式响应为空");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let threadId = options.threadId || null;
  let finishReason: string | null = null;
  let moderationError: string | null = null;
  let text = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const parts = buffer.split("\n\n");
    buffer = done ? "" : parts.pop() || "";
    for (const payload of parseSseEvents(parts.join("\n\n"))) {
      if (payload === "[DONE]") {
        return { finishReason, moderationError, text, threadId };
      }
      let chunk: Record<string, unknown>;
      try {
        chunk = JSON.parse(payload) as Record<string, unknown>;
      } catch {
        continue;
      }
      const nextThreadId = String(chunk.thread_id || "").trim();
      if (nextThreadId && nextThreadId !== threadId) {
        threadId = nextThreadId;
        options.onThreadId?.(nextThreadId);
      }
      const nextReason = String((chunk.choices as Array<{ finish_reason?: string }> | undefined)?.[0]?.finish_reason || "").trim();
      if (nextReason) {
        finishReason = nextReason;
      }
      const nextModerationError = String(chunk.moderation_error || "").trim();
      if (nextModerationError) {
        moderationError = nextModerationError;
      }
      const delta = String(
        ((chunk.choices as Array<{ delta?: { content?: string } }> | undefined)?.[0]?.delta?.content as string) || "",
      );
      if (!delta) {
        continue;
      }
      text += delta;
      options.onTextDelta?.(delta);
    }
    if (done) {
      return { finishReason, moderationError, text, threadId };
    }
  }
}
