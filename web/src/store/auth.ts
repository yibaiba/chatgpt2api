"use client";

import localforage from "localforage";

import type { AuthSession } from "@/lib/auth-types";

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
  return {
    role: session.role,
    name: String(session.name || "").trim() || (session.role === "admin" ? "管理员" : "普通用户"),
    image_quota: session.image_quota == null ? null : Math.max(0, Number(session.image_quota) || 0),
    total_generated: session.total_generated == null ? null : Math.max(0, Number(session.total_generated) || 0),
    last_used_at: session.last_used_at ? String(session.last_used_at) : null,
  };
}

export async function getStoredAuthKey() {
  if (typeof window === "undefined") {
    return "";
  }
  const value = await authStorage.getItem<string>(AUTH_KEY_STORAGE_KEY);
  return String(value || "").trim();
}

export async function setStoredAuthKey(authKey: string) {
  const normalizedAuthKey = String(authKey || "").trim();
  if (!normalizedAuthKey) {
    await clearStoredAuthKey();
    return;
  }
  await authStorage.setItem(AUTH_KEY_STORAGE_KEY, normalizedAuthKey);
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
  await Promise.all([
    authStorage.removeItem(AUTH_KEY_STORAGE_KEY),
    authStorage.removeItem(AUTH_SESSION_STORAGE_KEY),
  ]);
}
