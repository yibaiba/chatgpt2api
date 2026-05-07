"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Bot, ChevronRight, LoaderCircle, Plus, Send, ShieldAlert, Sparkles, Square } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { fetchAvailableModels, fetchSettingsConfig } from "@/lib/api";
import type { AuthSession } from "@/lib/auth-types";
import { syncStoredAuthSessionWithFallback } from "@/lib/auth-session";
import { streamPromptReview } from "@/lib/prompt-review";
import { buildPromptReviewStorageKey } from "@/lib/prompt-review-storage";
import { cn, generateClientId } from "@/lib/utils";

type ContextMode = "full" | "warn" | "auto";
type ReviewMessageState = "done" | "streaming" | "blocked" | "error";
type ReviewMessage = { id: string; role: "user" | "assistant"; content: string; error?: string; state: ReviewMessageState };
type ReviewThread = {
  id: string;
  title: string;
  serverThreadId: string | null;
  roundCount: number;
  blockedCount: number;
  updatedAt: number;
  lastPreview: string;
  messages: ReviewMessage[];
};

const CONTEXT_LIMIT = 6;
const AUTO_RESET_LIMIT = 12;
const DEFAULT_MODEL_OPTIONS = ["auto", "gpt-4.1", "gpt-5"];
const IMAGE_MODEL_OPTIONS = new Set(["gpt-image-1", "gpt-image-2", "codex-gpt-image-2", "gpt-image-think"]);

function normalizePromptReviewModelOptions(values: string[]) {
  const seen = new Set<string>();
  const options: string[] = [];
  for (const value of ["auto", ...values]) {
    const model = String(value || "").trim();
    if (!model || seen.has(model) || IMAGE_MODEL_OPTIONS.has(model)) {
      continue;
    }
    seen.add(model);
    options.push(model);
  }
  return options.length ? options : [...DEFAULT_MODEL_OPTIONS];
}

function buildThread(seed = ""): ReviewThread {
  const now = Date.now();
  const preview = seed.trim();
  return {
    id: `local-${generateClientId()}`,
    title: preview ? preview.slice(0, 18) : "新审查对话",
    serverThreadId: null,
    roundCount: 0,
    blockedCount: 0,
    updatedAt: now,
    lastPreview: preview,
    messages: [],
  };
}

function countWordHits(text: string, word: string) {
  const source = text.toLowerCase();
  const target = word.toLowerCase();
  if (!source || !target) {
    return 0;
  }
  let total = 0;
  let start = 0;
  while (start < source.length) {
    const index = source.indexOf(target, start);
    if (index < 0) {
      break;
    }
    total += 1;
    start = index + target.length;
  }
  return total;
}

function storageKeyForSession(session: AuthSession) {
  return buildPromptReviewStorageKey(session.role, session.id);
}

export default function PromptReviewPage() {
  const router = useRouter();
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const [threads, setThreads] = useState<ReviewThread[]>([]);
  const [activeId, setActiveId] = useState("");
  const [draft, setDraft] = useState("");
  const [model, setModel] = useState("gpt-4.1");
  const [modelOptions, setModelOptions] = useState<string[]>([...DEFAULT_MODEL_OPTIONS]);
  const [contextMode, setContextMode] = useState<ContextMode>("warn");
  const [sensitiveWords, setSensitiveWords] = useState<string[]>([]);
  const [storageKey, setStorageKey] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const init = async () => {
      try {
        const session = await syncStoredAuthSessionWithFallback();
        if (cancelled) {
          return;
        }
        if (session.role !== "admin") {
          toast.error("只有管理员可以访问 Prompt 审查工作台");
          router.replace("/image");
          return;
        }
        const nextStorageKey = storageKeyForSession(session);
        const stored = typeof window === "undefined" ? null : window.localStorage.getItem(nextStorageKey);
        const parsed = stored ? (JSON.parse(stored) as ReviewThread[]) : [];
        const nextThreads = Array.isArray(parsed) && parsed.length ? parsed : [buildThread()];
        let nextModelOptions = [...DEFAULT_MODEL_OPTIONS];
        try {
          const models = await fetchAvailableModels();
          nextModelOptions = normalizePromptReviewModelOptions(models.map((item) => item.id));
        } catch {
          nextModelOptions = [...DEFAULT_MODEL_OPTIONS];
        }
        const settings = await fetchSettingsConfig();
        if (cancelled) {
          return;
        }
        setStorageKey(nextStorageKey);
        setModelOptions(nextModelOptions);
        setModel((current) => (nextModelOptions.includes(current) ? current : (nextModelOptions[0] ?? "auto")));
        setThreads(nextThreads);
        setActiveId(nextThreads[0]?.id || "");
        setSensitiveWords(Array.isArray(settings.config.sensitive_words) ? settings.config.sensitive_words.filter(Boolean) : []);
      } catch (error) {
        if (!cancelled) {
          toast.error(error instanceof Error ? error.message : "加载 Prompt 审查工作台失败");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };
    void init();
    return () => {
      cancelled = true;
    };
  }, [router]);

  useEffect(() => {
    if (typeof window === "undefined" || !threads.length || !storageKey) {
      return;
    }
    window.localStorage.setItem(storageKey, JSON.stringify(threads));
  }, [storageKey, threads]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [threads, activeId]);

  const activeThread = useMemo(() => threads.find((thread) => thread.id === activeId) || threads[0] || null, [activeId, threads]);
  const flaggedWords = useMemo(() => {
    if (!activeThread) {
      return [];
    }
    const joinedText = activeThread.messages.map((item) => item.content).join("\n");
    return sensitiveWords
      .map((word) => ({ word, count: countWordHits(joinedText, word) }))
      .filter((item) => item.count > 0)
      .sort((left, right) => right.count - left.count);
  }, [activeThread, sensitiveWords]);

  const patchThread = useCallback((threadId: string, updater: (thread: ReviewThread) => ReviewThread) => {
    setThreads((current) => current.map((thread) => (thread.id === threadId ? updater(thread) : thread)));
  }, []);

  const createFreshThread = useCallback(
    (seed = "") => {
      const nextThread = buildThread(seed);
      setThreads((current) => [nextThread, ...current]);
      setActiveId(nextThread.id);
      return nextThread;
    },
    [],
  );

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsSending(false);
    toast.message("已停止当前流式输出");
  }, []);

  const handleSend = useCallback(async () => {
    const prompt = draft.trim();
    if (!prompt || isSending || !activeThread) {
      return;
    }
    let workingThread = activeThread;
    if (!workingThread.serverThreadId && workingThread.messages.length > 0) {
      workingThread = createFreshThread(prompt);
      toast.message("当前本地线程没有可复用的服务端上下文，已自动新开线程继续审查");
    } else if (contextMode === "auto" && activeThread.roundCount >= AUTO_RESET_LIMIT) {
      workingThread = createFreshThread(prompt);
      toast.message("当前线程已较长，已自动新开审查对话");
    }
    const userMessage: ReviewMessage = { id: generateClientId(), role: "user", content: prompt, state: "done" };
    const assistantMessage: ReviewMessage = { id: generateClientId(), role: "assistant", content: "", state: "streaming" };
    setDraft("");
    setActiveId(workingThread.id);
    patchThread(workingThread.id, (thread) => ({
      ...thread,
      title: thread.messages.length ? thread.title : prompt.slice(0, 18),
      updatedAt: Date.now(),
      lastPreview: prompt,
      messages: [...thread.messages, userMessage, assistantMessage],
    }));

    const controller = new AbortController();
    abortRef.current = controller;
    setIsSending(true);
    try {
      const result = await streamPromptReview({
        model,
        prompt,
        signal: controller.signal,
        threadId: workingThread.serverThreadId,
        onThreadId: (threadId) => {
          patchThread(workingThread.id, (thread) => ({ ...thread, serverThreadId: threadId }));
        },
        onTextDelta: (delta) => {
          patchThread(workingThread.id, (thread) => ({
            ...thread,
            updatedAt: Date.now(),
            lastPreview: (thread.lastPreview + delta).trim().slice(-80),
            messages: thread.messages.map((message) =>
              message.id === assistantMessage.id ? { ...message, content: `${message.content}${delta}` } : message,
            ),
          }));
        },
      });
      patchThread(workingThread.id, (thread) => ({
        ...thread,
        serverThreadId: result.threadId || thread.serverThreadId,
        roundCount: thread.roundCount + 1,
        blockedCount: thread.blockedCount + (result.finishReason === "content_filter" ? 1 : 0),
        updatedAt: Date.now(),
        lastPreview: (result.text || prompt).trim().slice(-80),
        messages: thread.messages.map((message) =>
          message.id === assistantMessage.id
            ? {
                ...message,
                content: result.text || "当前输出已结束",
                error: result.moderationError || "",
                state: result.finishReason === "content_filter" ? "blocked" : "done",
              }
            : message,
        ),
      }));
      if (result.finishReason === "content_filter" && result.moderationError) {
        toast.warning(result.moderationError);
      }
    } catch (error) {
      const message =
        error instanceof DOMException && error.name === "AbortError"
          ? "已手动停止当前流式输出"
          : error instanceof Error
            ? error.message
            : "流式审查失败";
      patchThread(workingThread.id, (thread) => ({
        ...thread,
        updatedAt: Date.now(),
        serverThreadId:
          message === "thread not found" || message === "thread conversation expired" ? null : thread.serverThreadId,
        messages: thread.messages.map((item) =>
          item.id === assistantMessage.id ? { ...item, content: item.content || "请求失败", error: message, state: "error" } : item,
        ),
      }));
      toast.error(message);
    } finally {
      abortRef.current = null;
      setIsSending(false);
    }
  }, [activeThread, contextMode, createFreshThread, draft, isSending, model, patchThread]);

  const contextHint =
    !activeThread || contextMode === "full"
      ? "始终复用服务端 thread_id，适合深挖同一主题。"
      : contextMode === "warn"
        ? activeThread.roundCount >= CONTEXT_LIMIT
          ? "当前轮数已偏长，建议新开线程避免网页侧上下文继续膨胀。"
          : `超过 ${CONTEXT_LIMIT} 轮后会提醒你手动新开线程。`
        : activeThread.roundCount >= AUTO_RESET_LIMIT
          ? "下次发送会自动切到新线程，避免上下文继续累积。"
          : `超过 ${AUTO_RESET_LIMIT} 轮后会自动新开线程。`;

  if (isLoading) {
    return (
      <div className="flex min-h-[55vh] items-center justify-center">
        <LoaderCircle className="size-6 animate-spin text-stone-400" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <section className="space-y-1">
        <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">Prompt Review</div>
        <h1 className="text-2xl font-semibold tracking-tight text-stone-950">Prompt 审查工作台</h1>
        <p className="text-sm text-stone-500">单独开一个持续对话线程，用流式方式审查 prompt、追问风险点，并在右侧持续汇总敏感词命中情况。</p>
      </section>

      <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)_320px]">
        <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
          <CardContent className="space-y-4 p-5">
            <Button className="h-10 rounded-xl bg-stone-950 text-white hover:bg-stone-800" onClick={() => createFreshThread()}>
              <Plus className="size-4" />
              新建线程
            </Button>
            <div className="space-y-2">
              {threads.map((thread) => (
                <button
                  key={thread.id}
                  type="button"
                  className={cn(
                    "w-full rounded-2xl border px-4 py-3 text-left transition",
                    activeThread?.id === thread.id ? "border-stone-950 bg-stone-950 text-white" : "border-stone-200 bg-white text-stone-700",
                  )}
                  onClick={() => setActiveId(thread.id)}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="truncate text-sm font-medium">{thread.title}</div>
                    <ChevronRight className="size-4 shrink-0 opacity-70" />
                  </div>
                  <div className={cn("mt-2 line-clamp-2 text-xs", activeThread?.id === thread.id ? "text-white/70" : "text-stone-500")}>
                    {thread.lastPreview || "空线程，适合先丢一句待审 prompt。"}
                  </div>
                  <div className="mt-3 flex items-center gap-2 text-[11px]">
                    <Badge variant={thread.serverThreadId ? "success" : "secondary"}>{thread.serverThreadId ? "持续对话" : "未启动"}</Badge>
                    <Badge variant={thread.blockedCount ? "warning" : "secondary"}>拦截 {thread.blockedCount}</Badge>
                  </div>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
          <CardContent className="flex h-full min-h-[70vh] flex-col gap-4 p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-stone-900">{activeThread?.title || "Prompt 审查"}</div>
                <div className="text-xs text-stone-500">模型：{model} · 轮数：{activeThread?.roundCount || 0}</div>
              </div>
              {activeThread?.serverThreadId ? <Badge variant="success">{activeThread.serverThreadId}</Badge> : <Badge variant="secondary">新线程</Badge>}
            </div>

            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto rounded-3xl border border-stone-200 bg-stone-50/70 p-4">
              {(activeThread?.messages || []).map((message) => (
                <div key={message.id} className={cn("max-w-[88%] rounded-3xl px-4 py-3 text-sm shadow-sm", message.role === "user" ? "ml-auto bg-stone-950 text-white" : "bg-white text-stone-800")}>
                  <div className="mb-1 flex items-center gap-2 text-[11px] uppercase tracking-[0.12em] opacity-70">
                    {message.role === "user" ? <Sparkles className="size-3.5" /> : <Bot className="size-3.5" />}
                    {message.role === "user" ? "Prompt" : "Review"}
                    {message.state === "streaming" ? <LoaderCircle className="size-3.5 animate-spin" /> : null}
                    {message.state === "blocked" ? <ShieldAlert className="size-3.5" /> : null}
                  </div>
                  <div className="whitespace-pre-wrap break-words">{message.content || "..."}</div>
                  {message.error ? <div className="mt-2 text-xs text-amber-500">{message.error}</div> : null}
                </div>
              ))}
              <div ref={bottomRef} />
            </div>

            <div className="space-y-3">
              <Textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="输入待审 prompt，或继续追问“这段提示词哪里容易误伤敏感词？”"
                className="min-h-28 rounded-[28px] border-stone-200 bg-white"
              />
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="text-xs text-stone-500">{contextHint}</div>
                <div className="flex items-center gap-2">
                  {isSending ? (
                    <Button variant="outline" className="h-10 rounded-xl border-stone-200 bg-white" onClick={handleStop}>
                      <Square className="size-4" />
                      停止
                    </Button>
                  ) : null}
                  <Button className="h-10 rounded-xl bg-stone-950 text-white hover:bg-stone-800" onClick={() => void handleSend()} disabled={!draft.trim() || isSending}>
                    <Send className="size-4" />
                    发送
                  </Button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
            <CardContent className="space-y-4 p-5">
              <div className="space-y-1">
                <div className="text-sm font-medium text-stone-900">上下文策略</div>
                <div className="text-xs text-stone-500">当前页面只维护一个服务端 thread_id；这里主要帮助你控制何时手动或自动新开线程。</div>
              </div>
              <Select value={model} onValueChange={setModel}>
                <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                  <SelectValue placeholder="选择模型" />
                </SelectTrigger>
                <SelectContent>
                  {modelOptions.map((item) => (
                    <SelectItem key={item} value={item}>
                      {item}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={contextMode} onValueChange={(value) => setContextMode(value as ContextMode)}>
                <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                  <SelectValue placeholder="选择上下文模式" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="full">完整线程</SelectItem>
                  <SelectItem value="warn">超过 6 轮提醒</SelectItem>
                  <SelectItem value="auto">超过 12 轮自动新开</SelectItem>
                </SelectContent>
              </Select>
              <div className={cn("rounded-2xl border px-4 py-3 text-xs", activeThread?.roundCount && activeThread.roundCount >= CONTEXT_LIMIT ? "border-amber-200 bg-amber-50 text-amber-700" : "border-stone-200 bg-stone-50 text-stone-500")}>
                {activeThread?.roundCount && activeThread.roundCount >= CONTEXT_LIMIT ? <AlertTriangle className="mb-2 size-4" /> : null}
                {contextHint}
              </div>
            </CardContent>
          </Card>

          <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
            <CardContent className="space-y-4 p-5">
              <div className="space-y-1">
                <div className="text-sm font-medium text-stone-900">敏感词总结</div>
                <div className="text-xs text-stone-500">设置页里配置的敏感词会直接作用到这里；命中后流会以 content_filter 收口。</div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge variant="secondary">已配置 {sensitiveWords.length}</Badge>
                <Badge variant={flaggedWords.length ? "warning" : "success"}>本线程命中 {flaggedWords.length}</Badge>
              </div>
              <div className="space-y-2">
                {flaggedWords.length ? (
                  flaggedWords.map((item) => (
                    <div key={item.word} className="flex items-center justify-between rounded-xl border border-stone-200 bg-white px-3 py-2 text-sm text-stone-700">
                      <span>{item.word}</span>
                      <Badge variant="warning">{item.count}</Badge>
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 px-4 py-6 text-sm text-stone-500">
                    当前线程还没有命中已配置敏感词；如果需要更严格的拦截，先到设置页补词表。
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
