"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  Images,
  LoaderCircle,
  Link2,
  RefreshCcw,
  ShieldCheck,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  fetchCPAPools,
  fetchSub2APIServers,
  type Account,
  type CPAImportJob,
  type CPAPool,
  type Sub2APIServer,
} from "@/lib/api";
import { getCachedOrSyncAuthSession } from "@/lib/auth-session";
import {
  buildBrowserImageHistoryStorageKey,
  listBrowserImageConversations,
  listImageConversations,
  type ImageConversation,
} from "@/store/image-conversations";
import { markImageOnboardingIntent } from "@/lib/onboarding";
import { cn } from "@/lib/utils";

type FirstSuccessChecklistProps = {
  accounts: Account[];
};

type ChecklistSnapshot = {
  pools: CPAPool[];
  servers: Sub2APIServer[];
  hasGeneratedImage: boolean;
  partiallyUnavailable: boolean;
};

type LatestImportSummary = {
  sourceId: string;
  sourceType: "CPA" | "Sub2API";
  sourceName: string;
  status: CPAImportJob["status"];
  updatedAt: string;
  added: number;
  refreshed: number;
  failed: number;
};

function hasSuccessfulImage(conversations: ImageConversation[]) {
  return conversations.some((conversation) =>
    conversation.turns.some((turn) => turn.images.some((image) => image.status === "success" && image.b64_json)),
  );
}

function formatRelativeTime(value?: string | null) {
  if (!value) {
    return "暂无记录";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const diff = date.getTime() - Date.now();
  const formatter = new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" });
  const minutes = Math.round(diff / (1000 * 60));
  if (Math.abs(minutes) < 60) {
    return formatter.format(minutes, "minute");
  }
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) {
    return formatter.format(hours, "hour");
  }
  const days = Math.round(hours / 24);
  return formatter.format(days, "day");
}

function pickLatestImport(pools: CPAPool[], servers: Sub2APIServer[]): LatestImportSummary | null {
  const candidates: LatestImportSummary[] = [];
  for (const pool of pools) {
    if (!pool.import_job) {
      continue;
    }
    candidates.push({
      sourceId: pool.id,
      sourceType: "CPA",
      sourceName: pool.name || "未命名 CPA",
      status: pool.import_job.status,
      updatedAt: pool.import_job.updated_at,
      added: pool.import_job.added,
      refreshed: pool.import_job.refreshed,
      failed: pool.import_job.failed,
    });
  }
  for (const server of servers) {
    if (!server.import_job) {
      continue;
    }
    candidates.push({
      sourceId: server.id,
      sourceType: "Sub2API",
      sourceName: server.name || "未命名 Sub2API",
      status: server.import_job.status,
      updatedAt: server.import_job.updated_at,
      added: server.import_job.added,
      refreshed: server.import_job.refreshed,
      failed: server.import_job.failed,
    });
  }
  if (candidates.length === 0) {
    return null;
  }
  return candidates.sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))[0] ?? null;
}

function buildAccountFilterHref(filters: { focus?: "attention"; status?: Account["status"] }) {
  const params = new URLSearchParams();
  if (filters.focus) {
    params.set("focus", filters.focus);
  }
  if (filters.status) {
    params.set("status", filters.status);
  }
  const search = params.toString();
  return `/accounts${search ? `?${search}` : ""}#account-list`;
}

function buildSourceHref(item: LatestImportSummary) {
  const anchor = item.sourceType === "CPA" ? `cpa-connection-${item.sourceId}` : `sub2api-connection-${item.sourceId}`;
  return `/settings#${anchor}`;
}

function buildLatestImportLabel(latestImport: LatestImportSummary | null) {
  if (!latestImport) {
    return "还没有导入或同步记录";
  }
  if (latestImport.status === "pending" || latestImport.status === "running") {
    return `${latestImport.sourceType} · ${latestImport.sourceName} 正在同步`;
  }
  if (latestImport.status === "failed") {
    return `${latestImport.sourceType} · ${latestImport.sourceName} 同步失败`;
  }
  return `${latestImport.sourceType} · ${latestImport.sourceName} 最近一次已完成`;
}

export function FirstSuccessChecklist({ accounts }: FirstSuccessChecklistProps) {
  const [snapshot, setSnapshot] = useState<ChecklistSnapshot>({
    pools: [],
    servers: [],
    hasGeneratedImage: false,
    partiallyUnavailable: false,
  });
  const [isLoading, setIsLoading] = useState(true);

  const loadSnapshot = useCallback(async () => {
    const session = await getCachedOrSyncAuthSession();
    if (!session || session.role !== "admin") {
      return {
        pools: [],
        servers: [],
        hasGeneratedImage: false,
        partiallyUnavailable: false,
      } satisfies ChecklistSnapshot;
    }

    const browserHistoryStorageKey = buildBrowserImageHistoryStorageKey("admin", session.id || "admin");
    const [poolsResult, serversResult, historyResult] = await Promise.allSettled([
      fetchCPAPools(),
      fetchSub2APIServers(),
      session.image_history_persistence_mode === "server"
        ? listImageConversations()
        : listBrowserImageConversations(browserHistoryStorageKey),
    ]);

    const pools = poolsResult.status === "fulfilled" ? poolsResult.value.pools : [];
    const servers = serversResult.status === "fulfilled" ? serversResult.value.servers : [];
    const conversations = historyResult.status === "fulfilled" ? historyResult.value : [];

    return {
      pools,
      servers,
      hasGeneratedImage: hasSuccessfulImage(conversations),
      partiallyUnavailable:
        poolsResult.status === "rejected" || serversResult.status === "rejected" || historyResult.status === "rejected",
    } satisfies ChecklistSnapshot;
  }, []);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setIsLoading(true);
      const nextSnapshot = await loadSnapshot();
      if (!cancelled) {
        setSnapshot(nextSnapshot);
        setIsLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [loadSnapshot]);

  useEffect(() => {
    const hasRunningImport = [...snapshot.pools, ...snapshot.servers].some(
      (item) => item.import_job?.status === "pending" || item.import_job?.status === "running",
    );
    if (!hasRunningImport) {
      return;
    }
    let cancelled = false;
    const timer = window.setInterval(() => {
      void loadSnapshot()
        .then((nextSnapshot) => {
          if (!cancelled) {
            setSnapshot(nextSnapshot);
          }
        })
        .catch(() => {
          if (!cancelled) {
            setSnapshot((current) => ({ ...current, partiallyUnavailable: true }));
          }
        });
    }, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [loadSnapshot, snapshot.pools, snapshot.servers]);

  const sourceCount = snapshot.pools.length + snapshot.servers.length;
  const autoSyncCount =
    snapshot.pools.filter((item) => item.auto_sync_enabled).length +
    snapshot.servers.filter((item) => item.auto_sync_enabled).length;
  const availableCount = accounts.filter((item) => item.status === "正常").length;
  const abnormalCount = accounts.filter((item) => item.status === "异常").length;
  const limitedCount = accounts.filter((item) => item.status === "限流").length;
  const hasProvisionedSources = sourceCount > 0 || accounts.length > 0;
  const hasLocalImportedAccounts = sourceCount === 0 && accounts.length > 0;
  const latestImport = useMemo(
    () => pickLatestImport(snapshot.pools, snapshot.servers),
    [snapshot.pools, snapshot.servers],
  );
  const attentionItems = useMemo(() => {
    const items: Array<{
      key: string;
      title: string;
      description: string;
      href?: string;
      actionLabel?: string;
      tone: "danger" | "warning";
    }> = [];

    if (!hasProvisionedSources) {
      items.push({
        key: "missing-sources",
        title: "还没有远端账号来源",
        description: "建议先接入 CPA 或 Sub2API，这样后续同步和补号会更省心。",
        href: "/settings#remote-account-sources",
        actionLabel: "去接入来源",
        tone: "danger",
      });
    }

    if (sourceCount > 0 && autoSyncCount === 0) {
      items.push({
        key: "auto-sync-disabled",
        title: "远端来源已接入，但自动同步还没开启",
        description: "如果你希望号池能自动补充，建议至少给一个远端来源打开自动同步。",
        href: "/settings#remote-account-sources",
        actionLabel: "去开启自动同步",
        tone: "warning",
      });
    }

    if (latestImport?.status === "failed") {
      items.push({
        key: "latest-sync-failed",
        title: "最近一次远端同步失败",
        description: `先检查 ${latestImport.sourceType} · ${latestImport.sourceName} 的连接、密钥和同步开关。`,
        href: buildSourceHref(latestImport),
        actionLabel: "去检查连接",
        tone: "danger",
      });
    }

    if (accounts.length > 0 && availableCount === 0) {
      items.push({
        key: "no-available-accounts",
        title: "当前没有正常可用账号",
        description: "建议先在本页刷新账号状态，或补充远端来源后重新同步。",
        href: buildAccountFilterHref({ focus: "attention" }),
        actionLabel: "查看待处理账号",
        tone: "danger",
      });
    }

    if (abnormalCount > 0) {
      items.push({
        key: "abnormal-accounts",
        title: `存在 ${abnormalCount} 个异常账号`,
        description: "可以先刷新状态；如果异常持续，建议回到来源侧检查这些账号是否已失效。",
        href: buildAccountFilterHref({ status: "异常" }),
        actionLabel: "查看异常账号",
        tone: "warning",
      });
    }

    if (limitedCount > 0) {
      items.push({
        key: "limited-accounts",
        title: `有 ${limitedCount} 个账号处于限流`,
        description: "如果可用账号偏少，建议提前补号，避免高峰期没有可用额度。",
        href: buildAccountFilterHref({ status: "限流" }),
        actionLabel: "查看限流账号",
        tone: "warning",
      });
    }

    return items.slice(0, 3);
  }, [abnormalCount, accounts.length, autoSyncCount, availableCount, hasProvisionedSources, limitedCount, latestImport, sourceCount]);

  const steps = [
    {
      key: "sources",
      title: "接入账号来源",
      description: hasProvisionedSources
        ? sourceCount > 0
          ? `已接入 ${sourceCount} 个远端来源，也支持继续在本页导入 Token。`
          : "当前还没有远端来源，但已经有本地导入账号，可以继续下一步。"
        : "先在设置页接入 CPA / Sub2API，或在当前页面先导入本地 Token。",
      done: hasProvisionedSources,
      icon: Link2,
    },
    {
      key: "accounts",
      title: "确认可用账号",
      description: availableCount > 0
        ? `当前有 ${availableCount} 个正常账号可用于出图。`
        : accounts.length > 0
          ? "已经检测到账号，但当前没有正常可用账号，建议先刷新或补充来源。"
          : "还没有可用账号，完成接入后再回来确认状态。",
      done: availableCount > 0,
      icon: ShieldCheck,
    },
    {
      key: "image",
      title: "完成首次出图",
      description: snapshot.hasGeneratedImage
        ? "已经检测到成功出图记录，可以直接进入工作台继续创作。"
        : "还没有检测到成功出图记录，去画图页完成第一张图。",
      done: snapshot.hasGeneratedImage,
      icon: Images,
    },
  ] as const;

  const completedCount = steps.filter((step) => step.done).length;
  const allCompleted = completedCount === steps.length;
  const nextAction = !hasProvisionedSources
    ? {
        href: "/settings#remote-account-sources",
        label: "去设置接入账号来源",
        helper: "你也可以先在当前页面直接导入 Token，后续再补远端同步。",
      }
    : availableCount === 0
      ? {
          href: sourceCount > 0 ? "/settings#remote-account-sources" : "/accounts",
          label: sourceCount > 0 ? "去检查远端同步设置" : "先在本页导入账号",
          helper:
            sourceCount > 0
              ? "如果你已经接入来源，先检查同步开关、连接信息，或在下方点击刷新。"
              : "导入后再确认是否有正常账号可用。",
        }
      : !snapshot.hasGeneratedImage
        ? {
            href: "/image",
            label: "去画图完成首次出图",
            helper: "完成一次成功生成后，这条首次成功路径就算打通了。",
          }
        : {
            href: "/image",
            label: "继续进入画图工作台",
            helper: "系统已经就绪，后续可以继续日常创作和运维。",
          };

  return (
    <Card className="overflow-hidden rounded-[28px] border-white/80 bg-white/95 shadow-[0_20px_70px_rgba(28,25,23,0.08)]">
      <CardContent className="space-y-5 p-4 sm:p-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={allCompleted ? "success" : "warning"}>
                {allCompleted ? "系统已就绪" : `首次成功路径 ${completedCount}/3`}
              </Badge>
              {isLoading ? (
                <Badge variant="secondary" className="gap-1">
                  <LoaderCircle className="size-3 animate-spin" />
                  正在检查
                </Badge>
              ) : null}
              {snapshot.partiallyUnavailable ? <Badge variant="secondary">部分状态暂不可用</Badge> : null}
            </div>
            <div className="space-y-1">
              <h2 className="text-xl font-semibold tracking-tight text-stone-950">管理员首次成功路径</h2>
              <p className="max-w-3xl text-sm leading-6 text-stone-600">
                先把“接入账号来源 → 确认可用账号 → 完成首次出图”这三步走通，后面的号池运维和日常创作会顺很多。
              </p>
            </div>
          </div>
          <div className="grid gap-2 sm:flex sm:flex-wrap sm:justify-end">
            <Button asChild className="h-10 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800">
              <Link
                href={nextAction.href}
                onClick={() => {
                  if (nextAction.href === "/image" && !snapshot.hasGeneratedImage) {
                    markImageOnboardingIntent("first-success");
                  }
                }}
              >
                {nextAction.label}
                <ArrowRight className="size-4" />
              </Link>
            </Button>
            <Button asChild variant="outline" className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700">
              <Link href="/image">打开画图工作台</Link>
            </Button>
          </div>
        </div>

        <div className="grid gap-3 xl:grid-cols-[minmax(0,1.8fr)_minmax(300px,1fr)]">
          <div className="grid gap-3 md:grid-cols-3">
            {steps.map((step) => {
              const Icon = step.icon;
              return (
                <div
                  key={step.key}
                  className={cn(
                    "rounded-2xl border p-4 transition-colors",
                    step.done ? "border-emerald-100 bg-emerald-50/80" : "border-stone-200 bg-stone-50/80",
                  )}
                >
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div
                      className={cn(
                        "inline-flex size-10 items-center justify-center rounded-2xl",
                        step.done ? "bg-emerald-600 text-white" : "bg-white text-stone-500",
                      )}
                    >
                      {step.done ? <CheckCircle2 className="size-5" /> : <Icon className="size-5" />}
                    </div>
                    <Badge variant={step.done ? "success" : "secondary"}>{step.done ? "已完成" : "待完成"}</Badge>
                  </div>
                  <div className="space-y-1.5">
                    <div className="text-sm font-semibold text-stone-950">{step.title}</div>
                    <p className="text-sm leading-6 text-stone-600">{step.description}</p>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="space-y-3 rounded-2xl border border-stone-200 bg-stone-50/80 p-4">
            <div className="space-y-1">
              <div className="text-sm font-semibold text-stone-950">当前就绪状态</div>
              <p className="text-sm leading-6 text-stone-600">{nextAction.helper}</p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
              <div className="rounded-2xl bg-white p-3">
                <div className="mb-2 flex items-center gap-2 text-stone-500">
                  <Link2 className="size-4" />
                  <span className="text-xs font-medium">账号来源</span>
                </div>
                <div className="text-lg font-semibold text-stone-950">
                  {sourceCount > 0 ? `${sourceCount} 个连接` : hasLocalImportedAccounts ? "已导入本地账号" : "未接入"}
                </div>
                <p className="mt-1 text-xs leading-5 text-stone-500">
                  {sourceCount > 0
                    ? `自动同步已开启 ${autoSyncCount} 个`
                    : hasLocalImportedAccounts
                      ? "当前使用本地导入账号，尚未配置远端自动同步。"
                      : "接入远端来源后可在这里查看连接与自动同步状态。"}
                </p>
              </div>

              <div className="rounded-2xl bg-white p-3">
                <div className="mb-2 flex items-center gap-2 text-stone-500">
                  <ShieldCheck className="size-4" />
                  <span className="text-xs font-medium">可用账号</span>
                </div>
                <div className="text-lg font-semibold text-stone-950">{availableCount}</div>
                <p className="mt-1 text-xs leading-5 text-stone-500">
                  异常 {abnormalCount} / 限流 {limitedCount}
                </p>
              </div>

              <div className="rounded-2xl bg-white p-3">
                <div className="mb-2 flex items-center gap-2 text-stone-500">
                  <RefreshCcw className="size-4" />
                  <span className="text-xs font-medium">最近同步</span>
                </div>
                <div className="text-sm font-semibold text-stone-950">{buildLatestImportLabel(latestImport)}</div>
                <p className="mt-1 text-xs leading-5 text-stone-500">
                  {latestImport
                    ? `更新时间 ${formatRelativeTime(latestImport.updatedAt)} · 新增 ${latestImport.added} / 刷新 ${latestImport.refreshed} / 失败 ${latestImport.failed}`
                    : "接入远端后会在这里显示最近一次导入或同步结果。"}
                </p>
              </div>
            </div>

            {!allCompleted ? (
              <div className="flex items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-900">
                <CircleAlert className="mt-0.5 size-4 shrink-0" />
                <span>先把这三步走通，再回头做更细的号池运维和模板化创作，会更顺手。</span>
              </div>
            ) : (
              <div className="flex items-start gap-2 rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-sm text-emerald-900">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
                <span>首次成功路径已经打通，后续可以把重点放在稳定运维和提高创作效率上。</span>
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs text-stone-500">
          <CircleDashed className="size-3.5" />
          <span>当前阶段先聚焦首次成功路径，号池健康面板和图片模板化会放到后续阶段。</span>
        </div>

        <div className="space-y-3 rounded-2xl border border-stone-200 bg-stone-50/80 p-4">
          <div className="space-y-1">
            <div className="text-sm font-semibold text-stone-950">当前关注点</div>
            <p className="text-sm leading-6 text-stone-600">把最影响可用性的 1-3 个问题直接提出来，减少你自己翻页面判断。</p>
          </div>

          {attentionItems.length > 0 ? (
            <div className="grid gap-3 md:grid-cols-3">
              {attentionItems.map((item) => (
                <div
                  key={item.key}
                  className={cn(
                    "rounded-2xl border px-4 py-3",
                    item.tone === "danger" ? "border-rose-200 bg-rose-50/90" : "border-amber-200 bg-amber-50/90",
                  )}
                >
                  <div className="space-y-1.5">
                    <div
                      className={cn(
                        "text-sm font-semibold",
                        item.tone === "danger" ? "text-rose-900" : "text-amber-900",
                      )}
                    >
                      {item.title}
                    </div>
                    <p className={cn("text-sm leading-6", item.tone === "danger" ? "text-rose-800" : "text-amber-800")}>
                      {item.description}
                    </p>
                  </div>
                  {item.href && item.actionLabel ? (
                    <Button
                      asChild
                      variant="outline"
                      className={cn(
                        "mt-3 h-9 rounded-xl border bg-white/80 px-3 text-sm",
                        item.tone === "danger"
                          ? "border-rose-200 text-rose-900 hover:bg-white"
                          : "border-amber-200 text-amber-900 hover:bg-white",
                      )}
                    >
                      <Link href={item.href}>
                        {item.actionLabel}
                        <ArrowRight className="size-4" />
                      </Link>
                    </Button>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-start gap-2 rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-sm text-emerald-900">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
              <span>当前没有明显的高优先级运维提醒，可以继续正常出图或做更细的号池优化。</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
