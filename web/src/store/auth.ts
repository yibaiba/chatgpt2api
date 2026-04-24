"use client";

import localforage from "localforage";

import type {
  AuthSession,
  ImageHistoryPersistenceMode,
} from "@/lib/auth-types";

export const AUTH_KEY_STORAGE_KEY = "chatgpt2api_auth_key";
export const AUTH_SESSION_STORAGE_KEY = "chatgpt2api_auth_session";

const authStorage = localforage.createInstance({
  name: "chatgpt2api",
  storeName: "auth",
});

function normalizeStoredSession(value: unknown): AuthSession | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const session = value as Partial<AuthSession>;
  if (session.role !== "admin" && session.role !== "user") {
    return null;
  }
  const imageHistoryPersistenceMode: ImageHistoryPersistenceMode =
    session.image_history_persistence_mode === "server" ? "server" : "browser";
  return {
    id: String(session.id || "").trim() || (session.role === "admin" ? "admin" : "unknown"),
    role: session.role,
    name: String(session.name || "").trim() || (session.role === "admin" ? "管理员" : "普通用户"),
    image_quota: session.image_quota == null ? null : Math.max(0, Number(session.image_quota) || 0),
    total_generated: session.total_generated == null ? null : Math.max(0, Number(session.total_generated) || 0),
    last_used_at: session.last_used_at ? String(session.last_used_at) : null,
    image_history_persistence_mode: imageHistoryPersistenceMode,
  };
}

export async function getStoredAuthKey() {
  return "";
}

export async function setStoredAuthKey(authKey: string) {
  if (!String(authKey || "").trim()) {
    await clearStoredAuthKey();
  }
}

export async function getStoredAuthSession() {
  if (typeof window === "undefined") {
    return null;
  }
  const value = await authStorage.getItem<AuthSession>(AUTH_SESSION_STORAGE_KEY);
  return normalizeStoredSession(value);
}

export async function setStoredAuthSession(session: AuthSession | null) {
  if (typeof window === "undefined") {
    return;
  }
  const normalized = normalizeStoredSession(session);
  if (!normalized) {
    await authStorage.removeItem(AUTH_SESSION_STORAGE_KEY);
    return;
  }
  await authStorage.setItem(AUTH_SESSION_STORAGE_KEY, normalized);
}

export async function clearStoredAuthKey() {
  if (typeof window === "undefined") {
    return;
  }
  await authStorage.removeItem(AUTH_SESSION_STORAGE_KEY);
}
