"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { getCachedOrSyncAuthSession, getDefaultRoute } from "@/lib/auth-session";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    void getCachedOrSyncAuthSession()
      .then((session) => {
        if (!cancelled) {
          router.replace(session ? getDefaultRoute(session.role) : "/login");
        }
      })
      .catch(() => {
        if (!cancelled) {
          router.replace("/login");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  return null;
}
