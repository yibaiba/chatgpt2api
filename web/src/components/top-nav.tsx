"use client";

import Link from "next/link";
import { Github } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import webConfig from "@/constants/common-env";
import { getCachedOrSyncAuthSession } from "@/lib/auth-session";
import { logout } from "@/lib/api";
import type { AuthSession } from "@/lib/auth-types";
import { clearStoredAuthKey } from "@/store/auth";
import { cn } from "@/lib/utils";

export function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);

  useEffect(() => {
    if (pathname === "/login") {
      return;
    }
    let cancelled = false;
    void getCachedOrSyncAuthSession()
      .then((value) => {
        if (!cancelled) {
          setSession(value);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSession(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  const handleLogout = async () => {
    await logout();
    await clearStoredAuthKey();
    router.replace("/login");
  };

  if (pathname === "/login") {
    return null;
  }

  const navItems =
    session?.role === "admin"
      ? [
          { href: "/image", label: "画图" },
          { href: "/accounts", label: "号池管理" },
          { href: "/register", label: "注册" },
          { href: "/logs", label: "日志" },
          { href: "/settings", label: "设置" },
        ]
      : [{ href: "/image", label: "画图" }];

  return (
    <header className="border-b border-stone-100/50 bg-white/80 backdrop-blur-md">
      <div className="flex h-12 items-center justify-between gap-3 px-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-2 sm:gap-3">
          <Link
            href="/image"
            className="shrink-0 py-1 text-[14px] font-bold tracking-tight text-stone-950 transition hover:text-stone-700 sm:text-[15px]"
          >
            chatgpt2api
          </Link>
          <a
            href="https://github.com/basketikun/chatgpt2api"
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center gap-1.5 py-1 text-sm text-stone-400 transition hover:text-stone-700"
            aria-label="GitHub repository"
          >
            <Github className="size-4" />
            <span className="hidden md:inline">GitHub</span>
          </a>
        </div>
        <div className="flex min-w-0 flex-1 justify-center gap-3 sm:gap-8">
          {navItems.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "relative shrink-0 py-1 text-[13px] font-medium transition sm:text-[15px]",
                  active ? "font-semibold text-stone-950" : "text-stone-500 hover:text-stone-900",
                )}
              >
                {item.label}
                {active ? <span className="absolute inset-x-0 -bottom-[3px] h-0.5 bg-stone-950" /> : null}
              </Link>
            );
          })}
        </div>
        <div className="flex min-w-0 flex-1 items-center justify-end gap-2 sm:gap-3">
          {session ? (
            <span className="hidden truncate rounded-md bg-stone-100 px-2 py-1 text-[11px] font-medium text-stone-500 sm:inline-block">
              {session.role === "admin" ? "管理员" : session.name}
            </span>
          ) : null}
          <span className="hidden rounded-md bg-stone-100 px-2 py-1 text-[11px] font-medium text-stone-500 sm:inline-block">
            v{webConfig.appVersion}
          </span>
          <button
            type="button"
            className="shrink-0 py-1 text-sm text-stone-400 transition hover:text-stone-700"
            onClick={() => void handleLogout()}
          >
            退出
          </button>
        </div>
      </div>
    </header>
  );
}
