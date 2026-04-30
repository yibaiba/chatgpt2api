"use client";

export const PROMPT_REVIEW_STORAGE_PREFIX = "chatgpt2api_prompt_review_threads:";

export function buildPromptReviewStorageKey(role: string, id: string) {
  const normalizedRole = String(role || "user").trim() || "user";
  const normalizedId = String(id || "unknown").trim() || "unknown";
  return `${PROMPT_REVIEW_STORAGE_PREFIX}${normalizedRole}:${normalizedId}`;
}

export function clearPromptReviewStorage() {
  if (typeof window === "undefined") {
    return;
  }
  for (let index = window.localStorage.length - 1; index >= 0; index -= 1) {
    const key = window.localStorage.key(index);
    if (key?.startsWith(PROMPT_REVIEW_STORAGE_PREFIX)) {
      window.localStorage.removeItem(key);
    }
  }
}
