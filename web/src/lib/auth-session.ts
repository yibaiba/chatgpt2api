"use client";

import { fetchSession } from "@/lib/api";
import type { AuthSession, UserRole } from "@/lib/auth-types";
import { getStoredAuthSession, setStoredAuthSession } from "@/store/auth";

export function getDefaultRoute(role?: UserRole | null) {
  return role === "admin" ? "/accounts" : "/image";
}

export function isAdminSession(session: AuthSession | null | undefined) {
  return session?.role === "admin";
}

export async function syncStoredAuthSession() {
  const data = await fetchSession();
  await setStoredAuthSession(data.session);
  return data.session;
}

export async function syncStoredAuthSessionWithFallback() {
  const storedSession = await getStoredAuthSession();
  try {
    return await syncStoredAuthSession();
  } catch (error) {
    if (storedSession) {
      return storedSession;
    }
    throw error;
  }
}

export async function getCachedOrSyncAuthSession() {
  const storedSession = await getStoredAuthSession();
  if (storedSession) {
    return storedSession;
  }
  try {
    return await syncStoredAuthSession();
  } catch {
    return null;
  }
}
