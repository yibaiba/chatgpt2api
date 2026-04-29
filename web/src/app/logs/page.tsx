"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { LoaderCircle, RefreshCw, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { fetchSystemLogs, type SystemLog, type SystemLogLevel, type SystemLogSource } from "@/lib/api";
import { syncStoredAuthSessionWithFallback } from "@/lib/auth-session";

const SOURCE_LABELS: Record<SystemLogSource, string> = {
  all: "全部来源",
  server: "服务日志",
  register: "注册日志",
};

const LEVEL_LABELS: Record<SystemLogLevel, string> = {
  all: "全部级别",
  info: "信息",
  warning: "警告",
  error: "错误",
  success: "成功",
};

function levelBadgeVariant(level: SystemLogLevel) {
  if (level === "error") {
    return "danger" as const;
  }
  if (level === "warning") {
    return "warning" as const;
  }
  if (level === "success") {
    return "success" as const;
  }
  return "secondary" as const;
}

function sourceBadgeVariant(source: SystemLogSource) {
  return source === "register" ? ("success" as const) : ("secondary" as const);
}

export default function LogsPage() {
  const router = useRouter();
  const [items, setItems] = useState<SystemLog[]>([]);
  const [source, setSource] = useState<SystemLogSource>("all");
  const [level, setLevel] = useState<SystemLogLevel>("all");
  const [queryInput, setQueryInput] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [selectedLog, setSelectedLog] = useState<SystemLog | null>(null);

  const loadLogs = useCallback(
    async (silent = false) => {
      if (!silent) {
        setIsLoading(true);
      }
      try {
        const data = await fetchSystemLogs({
          source,
          query: appliedQuery,
          level,
          limit: 200,
        });
        setItems(data.items);
      } catch (error) {
        if (!silent) {
          toast.error(error instanceof Error ? error.message : "加载日志失败");
        }
      } finally {
        if (!silent) {
          setIsLoading(false);
        }
      }
    },
    [appliedQuery, level, source],
  );

  useEffect(() => {
    let cancelled = false;
    const init = async () => {
      try {
        const session = await syncStoredAuthSessionWithFallback();
        if (cancelled) {
          return;
        }
        if (session.role !== "admin") {
          toast.error("只有管理员可以访问日志管理");
          router.replace("/image");
          return;
        }
        await loadLogs();
      } catch (error) {
        if (cancelled) {
          return;
        }
        setIsLoading(false);
        toast.error(error instanceof Error ? error.message : "校验登录状态失败，请稍后重试");
      }
    };
    void init();
    return () => {
      cancelled = true;
    };
  }, [loadLogs, router]);

  const summary = useMemo(() => {
    const total = items.length;
    const errorCount = items.filter((item) => item.level === "error").length;
    const warningCount = items.filter((item) => item.level === "warning").length;
    return { total, errorCount, warningCount };
  }, [items]);

  return (
    <div className="space-y-5">
      <section className="space-y-1">
        <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">Logs</div>
        <h1 className="text-2xl font-semibold tracking-tight text-stone-950">日志管理</h1>
        <p className="text-sm text-stone-500">
          先提供一个低风险的只读日志浏览器：聚合服务运行日志与注册 runner 日志，便于快速筛查异常和追踪执行过程。
        </p>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
          <CardContent className="space-y-1 p-5">
            <div className="text-xs text-stone-400">总记录数</div>
            <div className="text-2xl font-semibold text-stone-900">{summary.total}</div>
          </CardContent>
        </Card>
        <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
          <CardContent className="space-y-1 p-5">
            <div className="text-xs text-stone-400">错误</div>
            <div className="text-2xl font-semibold text-rose-600">{summary.errorCount}</div>
          </CardContent>
        </Card>
        <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
          <CardContent className="space-y-1 p-5">
            <div className="text-xs text-stone-400">警告</div>
            <div className="text-2xl font-semibold text-amber-600">{summary.warningCount}</div>
          </CardContent>
        </Card>
      </section>

      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="space-y-4 p-5">
          <div className="grid gap-3 lg:grid-cols-[180px_180px_minmax(0,1fr)_auto_auto]">
            <Select value={source} onValueChange={(value) => setSource(value as SystemLogSource)}>
              <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                <SelectValue placeholder="选择来源" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部来源</SelectItem>
                <SelectItem value="server">服务日志</SelectItem>
                <SelectItem value="register">注册日志</SelectItem>
              </SelectContent>
            </Select>

            <Select value={level} onValueChange={(value) => setLevel(value as SystemLogLevel)}>
              <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                <SelectValue placeholder="选择级别" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部级别</SelectItem>
                <SelectItem value="info">信息</SelectItem>
                <SelectItem value="warning">警告</SelectItem>
                <SelectItem value="error">错误</SelectItem>
                <SelectItem value="success">成功</SelectItem>
              </SelectContent>
            </Select>

            <Input
              value={queryInput}
              onChange={(event) => setQueryInput(event.target.value)}
              placeholder="搜索关键字，例如 fail、refresh、register"
              className="h-11 rounded-xl border-stone-200 bg-white"
            />

            <Button
              variant="outline"
              className="h-11 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
              onClick={() => {
                setQueryInput("");
                setAppliedQuery("");
                setSource("all");
                setLevel("all");
              }}
            >
              清空
            </Button>

            <Button
              className="h-11 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800"
              onClick={() => {
                setAppliedQuery(queryInput.trim());
              }}
              disabled={isLoading}
            >
              {isLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Search className="size-4" />}
              查询
            </Button>
          </div>

          <div className="flex items-center justify-between text-sm text-stone-500">
            <span>
              当前来源：{SOURCE_LABELS[source]} · 级别：{LEVEL_LABELS[level]} · 关键字：{appliedQuery || "无"}
            </span>
            <Button
              variant="ghost"
              className="h-9 rounded-lg px-3 text-stone-600"
              onClick={() => void loadLogs()}
              disabled={isLoading}
            >
              <RefreshCw className={`size-4 ${isLoading ? "animate-spin" : ""}`} />
              刷新
            </Button>
          </div>

          <div className="overflow-hidden rounded-2xl border border-stone-200">
            <div className="overflow-x-auto">
              <table className="min-w-full table-fixed border-collapse">
                <thead className="bg-stone-50 text-left text-xs uppercase tracking-[0.12em] text-stone-500">
                  <tr>
                    <th className="px-4 py-3 font-medium">来源</th>
                    <th className="px-4 py-3 font-medium">级别</th>
                    <th className="px-4 py-3 font-medium">时间</th>
                    <th className="px-4 py-3 font-medium">摘要</th>
                    <th className="px-4 py-3 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-stone-100 bg-white text-sm">
                  {items.map((item) => (
                    <tr key={item.id} className="align-top text-stone-700">
                      <td className="px-4 py-3">
                        <Badge variant={sourceBadgeVariant(item.source)} className="rounded-md">
                          {SOURCE_LABELS[item.source]}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={levelBadgeVariant(item.level)} className="rounded-md">
                          {LEVEL_LABELS[item.level]}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-stone-500">{item.time || "—"}</td>
                      <td className="px-4 py-3">
                        <div className="line-clamp-2 break-all text-stone-700">{item.summary}</div>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Button variant="ghost" className="h-8 rounded-lg px-3 text-stone-600" onClick={() => setSelectedLog(item)}>
                          查看全文
                        </Button>
                      </td>
                    </tr>
                  ))}
                  {!isLoading && items.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-6 py-14 text-center text-sm text-stone-500">
                        没有找到匹配日志
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
        </CardContent>
      </Card>

      <Dialog open={Boolean(selectedLog)} onOpenChange={(open) => (!open ? setSelectedLog(null) : null)}>
        <DialogContent className="w-[min(92vw,960px)] rounded-2xl p-6">
          <DialogHeader>
            <DialogTitle>日志详情</DialogTitle>
          </DialogHeader>
          {selectedLog ? (
            <div className="space-y-4">
              <div className="grid gap-3 rounded-xl border border-stone-200 bg-stone-50/70 p-4 text-sm text-stone-700 md:grid-cols-2">
                <div className="flex items-center justify-between gap-4">
                  <span className="text-stone-400">来源</span>
                  <span>{SOURCE_LABELS[selectedLog.source]}</span>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <span className="text-stone-400">级别</span>
                  <span>{LEVEL_LABELS[selectedLog.level]}</span>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <span className="text-stone-400">时间</span>
                  <span>{selectedLog.time || "—"}</span>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <span className="text-stone-400">ID</span>
                  <span className="font-mono text-xs">{selectedLog.id}</span>
                </div>
              </div>
              <pre className="max-h-[70vh] overflow-auto rounded-xl border border-stone-200 bg-stone-950 p-4 text-xs leading-6 text-stone-100">
                {selectedLog.message}
                {"\n\n"}
                {JSON.stringify(selectedLog.detail || {}, null, 2)}
              </pre>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
