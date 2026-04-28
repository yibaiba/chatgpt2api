"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import {
  fetchRegisterConfig,
  resetRegisterRunner,
  startRegisterRunner,
  stopRegisterRunner,
  updateRegisterConfig,
  type RegisterConfig,
} from "@/lib/api";
import { syncStoredAuthSession } from "@/lib/auth-session";

import { RegisterCard } from "./components/register-card";

function buildEditablePayload(config: RegisterConfig) {
  return {
    mail: config.mail,
    proxy: config.proxy,
    total: config.total,
    threads: config.threads,
    mode: config.mode,
    target_quota: config.target_quota,
    target_available: config.target_available,
    check_interval: config.check_interval,
  };
}

function comparableConfig(config: RegisterConfig | null) {
  if (!config) {
    return "";
  }
  return JSON.stringify(buildEditablePayload(config));
}

export default function RegisterPage() {
  const router = useRouter();
  const [config, setConfig] = useState<RegisterConfig | null>(null);
  const [serverConfig, setServerConfig] = useState<RegisterConfig | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [actionLabel, setActionLabel] = useState<string | null>(null);
  const [isAccessReady, setIsAccessReady] = useState(false);
  const serverComparableRef = useRef("");

  const isDirty = useMemo(
    () => comparableConfig(config) !== comparableConfig(serverConfig),
    [config, serverConfig],
  );

  const loadRegister = useCallback(async (silent = false) => {
    if (!silent) {
      setIsLoading(true);
    }
    try {
      const data = await fetchRegisterConfig();
      const nextConfig = data.register;
      const previousComparable = serverComparableRef.current;
      serverComparableRef.current = comparableConfig(nextConfig);
      setServerConfig(nextConfig);
      setConfig((current) => {
        if (!current || comparableConfig(current) === previousComparable) {
          return nextConfig;
        }
        return {
          ...current,
          enabled: nextConfig.enabled,
          stats: nextConfig.stats,
          logs: nextConfig.logs,
        };
      });
    } catch (error) {
      if (!silent) {
        toast.error(error instanceof Error ? error.message : "加载注册 runner 失败");
      }
    } finally {
      if (!silent) {
        setIsLoading(false);
      }
    }
  }, []);

  const applyServerConfig = useCallback((nextConfig: RegisterConfig) => {
    serverComparableRef.current = comparableConfig(nextConfig);
    setServerConfig(nextConfig);
    setConfig(nextConfig);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const init = async () => {
      try {
        const session = await syncStoredAuthSession();
        if (cancelled) {
          return;
        }
        if (session.role !== "admin") {
          toast.error("只有管理员可以访问注册 runner");
          router.replace("/image");
          return;
        }
        setIsAccessReady(true);
        await loadRegister();
      } catch {
        if (!cancelled) {
          router.replace("/login");
        }
      }
    };
    void init();
    return () => {
      cancelled = true;
    };
  }, [loadRegister, router]);

  useEffect(() => {
    if (!isAccessReady) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadRegister(true);
    }, 3000);
    return () => {
      window.clearInterval(timer);
    };
  }, [isAccessReady, loadRegister]);

  const handleSave = useCallback(async () => {
    if (!config) {
      return;
    }
    setIsSaving(true);
    try {
      const data = await updateRegisterConfig(buildEditablePayload(config));
      applyServerConfig(data.register);
      toast.success("注册 runner 配置已保存");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存注册 runner 配置失败");
    } finally {
      setIsSaving(false);
    }
  }, [applyServerConfig, config]);

  const handleToggle = useCallback(async () => {
    if (!config) {
      return;
    }
    setActionLabel(config.enabled ? "stopping" : "starting");
    try {
      let result;
      if (config.enabled) {
        result = await stopRegisterRunner();
        toast.success("已请求停止注册 runner");
      } else {
        const saved = await updateRegisterConfig(buildEditablePayload(config));
        applyServerConfig(saved.register);
        result = await startRegisterRunner();
        toast.success("注册 runner 控制面已启动");
      }
      applyServerConfig(result.register);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "切换注册 runner 状态失败");
    } finally {
      setActionLabel(null);
    }
  }, [applyServerConfig, config]);

  const handleReset = useCallback(async () => {
    setActionLabel("resetting");
    try {
      const data = await resetRegisterRunner();
      applyServerConfig(data.register);
      toast.success("注册 runner 状态已重置");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "重置注册 runner 失败");
    } finally {
      setActionLabel(null);
    }
  }, [applyServerConfig]);

  if (isLoading && !config) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <section className="space-y-1">
        <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">Register</div>
        <h1 className="text-2xl font-semibold tracking-tight text-stone-950">注册 runner</h1>
        <p className="text-sm text-stone-500">
          当前已接入 `tempmail_lol` 的最小真实执行链路：可以保存配置、查看状态、启动/停止，并在成功后把新 token 回灌到现有号池。
        </p>
      </section>

      <RegisterCard
        config={config}
        isLoading={isLoading}
        isSaving={isSaving}
        actionLabel={actionLabel}
        isDirty={isDirty}
        onChange={setConfig}
        onSave={handleSave}
        onToggle={handleToggle}
        onReset={handleReset}
      />
    </div>
  );
}
