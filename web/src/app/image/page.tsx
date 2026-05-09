"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownToLine, ArrowUpToLine, History, Plus } from "lucide-react";
import { toast } from "sonner";

import { ImageComposer } from "@/app/image/components/image-composer";
import { ImageResults, type ImageLightboxItem } from "@/app/image/components/image-results";
import { ImageSidebar } from "@/app/image/components/image-sidebar";
import { MaskEditorDialog } from "@/app/image/components/mask-editor-dialog";
import { ImageLightbox } from "@/components/image-lightbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { getCachedOrSyncAuthSession, syncStoredAuthSessionWithFallback } from "@/lib/auth-session";
import type { AuthSession, ImageHistoryPersistenceMode, UserRole } from "@/lib/auth-types";
import {
  createImageEditJob,
  createImageGenerationJob,
  createImageInpaintJob,
  fetchAccounts,
  waitForImageJob,
  type Account,
  type GeneratedImageResponse,
  type ImageModel,
} from "@/lib/api";
import { formatMonthDayTimeInShanghai } from "@/lib/time";
import { generateClientId } from "@/lib/utils";
import {
  buildImageJobRequestOptions,
  DEFAULT_IMAGE_BACKGROUND,
  DEFAULT_IMAGE_OUTPUT_FORMAT,
  DEFAULT_IMAGE_RENDER_QUALITY,
  isCodexImageModel,
  normalizeImageCompression,
  isImageAspectRatio,
  type ImageBackground,
  type ImageAspectRatio,
  type ImageOutputFormat,
  type ImageOutputQuality,
  type ImageRenderQuality,
} from "@/lib/image-options";
import { consumeImageOnboardingIntent } from "@/lib/onboarding";
import { upscaleGeneratedImage } from "@/lib/image-upscale";
import {
  buildBrowserImageHistoryStorageKey,
  clearBrowserImageConversations,
  clearImageConversations,
  deleteBrowserImageConversation,
  deleteImageConversation,
  getImageConversationStats,
  listBrowserImageConversations,
  listImageConversations,
  saveBrowserImageConversation,
  saveImageConversation,
  type ImageConversation,
  type ImageConversationMode,
  type ImageTurn,
  type StoredImage,
  type StoredReferenceImage,
} from "@/store/image-conversations";

const DEFAULT_IMAGE_MODEL: ImageModel = "gpt-image-2";
const ACTIVE_CONVERSATION_STORAGE_KEY = "chatgpt2api:image_active_conversation_id";
const IMAGE_ASPECT_RATIO_STORAGE_KEY = "chatgpt2api:image_last_aspect_ratio";
const MOBILE_RESULTS_BREAKPOINT = 1024;
const RESULTS_SCROLL_RETRY_DELAYS_MS = [80, 240, 600, 1200, 2400] as const;
const RESULTS_SCROLL_SETTLE_DELAY_MS = 2400;
const DRAFT_CONVERSATION_TITLE = "新对话";
const activeConversationQueueIds = new Set<string>();
// 跟踪由外部流程（如 handleMaskEditorSubmit）直接管理的 turn，防止 runConversationQueue 抢占处理
const externallyManagedTurnIds = new Set<string>();

function buildConversationTitle(prompt: string) {
  const trimmed = prompt.trim();
  if (trimmed.length <= 12) {
    return trimmed;
  }
  return `${trimmed.slice(0, 12)}...`;
}

function formatConversationTime(value: string) {
  return formatMonthDayTimeInShanghai(value);
}

function formatAvailableQuota(accounts: Account[]) {
  const availableAccounts = accounts.filter((account) => account.status === "正常");
  if (availableAccounts.some((account) => account.type === "Pro" || account.type === "ProLite")) {
    return "∞";
  }
  if (availableAccounts.some((account) => account.imageQuotaUnknown)) {
    return "未知";
  }
  return String(availableAccounts.reduce((sum, account) => sum + Math.max(0, account.quota), 0));
}

function createId() {
  return generateClientId();
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("读取参考图失败"));
    reader.readAsDataURL(file);
  });
}

function dataUrlToFile(dataUrl: string, fileName: string, mimeType?: string) {
  const [header, content] = dataUrl.split(",", 2);
  const matchedMimeType = header.match(/data:(.*?);base64/)?.[1];
  const binary = atob(content || "");
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new File([bytes], fileName, { type: mimeType || matchedMimeType || "image/png" });
}

function pickFallbackConversationId(conversations: ImageConversation[]) {
  const activeConversation = conversations.find((conversation) =>
    conversation.turns.some((turn) => turn.status === "queued" || turn.status === "generating"),
  );
  return activeConversation?.id ?? conversations[0]?.id ?? null;
}

function normalizeImageModelForMode(mode: ImageConversationMode, model: ImageModel): ImageModel {
  if (mode === "edit" && model === "gpt-image-think") {
    return "gpt-image-2";
  }
  return model;
}

function getLoadingImages(turn: ImageTurn) {
  return turn.images.filter((image) => image.status === "loading");
}

function hasRecoverableImageJob(image: StoredImage) {
  return image.status === "loading" && typeof image.job_id === "string" && image.job_id.trim().length > 0;
}

function hasPendingTurnWork(turn: ImageTurn) {
  return (turn.status === "queued" || turn.status === "generating") && getLoadingImages(turn).length > 0;
}

function resolveCompletedTurnState(turn: ImageTurn) {
  const failedCount = turn.images.filter((image) => image.status === "error").length;
  const successCount = turn.images.filter((image) => image.status === "success").length;
  return {
    status: failedCount > 0 ? ("error" as const) : successCount > 0 ? ("success" as const) : ("queued" as const),
    error: failedCount > 0 ? `其中 ${failedCount} 张未成功生成` : undefined,
  };
}

function resolveRecoveredTurnState(turn: ImageTurn) {
  const loadingImages = getLoadingImages(turn);
  if (loadingImages.length === 0) {
    return resolveCompletedTurnState(turn);
  }
  return {
    status: loadingImages.every(hasRecoverableImageJob) ? ("generating" as const) : ("queued" as const),
    error: undefined,
  };
}

function sortImageConversations(conversations: ImageConversation[]) {
  return [...conversations].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

async function recoverConversationHistory(
  items: ImageConversation[],
  persistConversation: (conversation: ImageConversation) => Promise<void>,
) {
  const normalized = items.map((conversation) => {
    let changed = false;

    const turns = conversation.turns.map((turn) => {
      const { status: nextStatus, error: nextError } = resolveRecoveredTurnState(turn);
      if (nextStatus === turn.status && nextError === turn.error) {
        return turn;
      }

      changed = true;
      return {
        ...turn,
        status: nextStatus,
        error: nextError,
      };
    });

    if (!changed) {
      return conversation;
    }

    const lastTurn = turns.length > 0 ? turns[turns.length - 1] : null;
    return {
      ...conversation,
      turns,
      updatedAt: lastTurn?.createdAt || conversation.updatedAt,
    };
  });

  const changedConversations = normalized.filter((conversation, index) => conversation !== items[index]);
  if (changedConversations.length > 0) {
    await Promise.all(changedConversations.map((conversation) => persistConversation(conversation)));
  }

  return normalized;
}

export default function ImagePage() {
  const didLoadQuotaRef = useRef(false);
  const conversationsRef = useRef<ImageConversation[]>([]);
  const runConversationQueueRef = useRef<(conversationId: string) => Promise<void>>(async () => {});
  const persistenceQueueRef = useRef<Map<string, Promise<void>>>(new Map());
  const pendingPersistenceRef = useRef<Set<string>>(new Set());
  const resultsViewportRef = useRef<HTMLDivElement>(null);
  const resultsContentRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [imagePrompt, setImagePrompt] = useState("");
  const [imageCount, setImageCount] = useState("1");
  const [imageMode, setImageMode] = useState<ImageConversationMode>("generate");
  const [imageModel, setImageModel] = useState<ImageModel>(DEFAULT_IMAGE_MODEL);
  const [imageAspectRatio, setImageAspectRatio] = useState<ImageAspectRatio>("1:1");
  const [imageOutputQuality, setImageOutputQuality] = useState<ImageOutputQuality>("original");
  const [imageRenderQuality, setImageRenderQuality] = useState<ImageRenderQuality>(DEFAULT_IMAGE_RENDER_QUALITY);
  const [imageBackground, setImageBackground] = useState<ImageBackground>(DEFAULT_IMAGE_BACKGROUND);
  const [imageOutputFormat, setImageOutputFormat] = useState<ImageOutputFormat>(DEFAULT_IMAGE_OUTPUT_FORMAT);
  const [imageCompression, setImageCompression] = useState("");
  const [referenceImageFiles, setReferenceImageFiles] = useState<File[]>([]);
  const [referenceImages, setReferenceImages] = useState<StoredReferenceImage[]>([]);
  const [conversations, setConversations] = useState<ImageConversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [availableQuota, setAvailableQuota] = useState("加载中...");
  const [viewerSession, setViewerSession] = useState<AuthSession | null>(null);
  const [onboardingMode, setOnboardingMode] = useState<string | null>(null);
  const [historyPersistenceMode, setHistoryPersistenceMode] = useState<ImageHistoryPersistenceMode>("browser");
  const [isHistoryModeReady, setIsHistoryModeReady] = useState(false);
  const [lightboxImages, setLightboxImages] = useState<ImageLightboxItem[]>([]);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [deleteConfirm, setDeleteConfirm] = useState<{ type: "one"; id: string } | { type: "all" } | null>(null);
  const [isNearPageBottom, setIsNearPageBottom] = useState(true);
  const [didLoadStoredAspectRatio, setDidLoadStoredAspectRatio] = useState(false);

  // 遮罩编辑 dialog 状态
  const [maskEditorOpen, setMaskEditorOpen] = useState(false);
  const [maskEditorImageDataUrl, setMaskEditorImageDataUrl] = useState("");
  const [maskEditorImageFile, setMaskEditorImageFile] = useState<File | null>(null);
  const [maskEditorDefaultPrompt, setMaskEditorDefaultPrompt] = useState("");
  const [maskEditorAvailableImages, setMaskEditorAvailableImages] = useState<{ dataUrl: string; id: string }[]>([]);
  const [maskEditorConversationId, setMaskEditorConversationId] = useState("");
  const [maskEditorLastMessageId, setMaskEditorLastMessageId] = useState("");

  const parsedCount = useMemo(() => Math.max(1, Math.min(10, Number(imageCount) || 1)), [imageCount]);
  const effectiveSelectedConversationId = useMemo(() => {
    if (selectedConversationId && conversations.some((conversation) => conversation.id === selectedConversationId)) {
      return selectedConversationId;
    }
    return pickFallbackConversationId(conversations);
  }, [conversations, selectedConversationId]);
  const selectedConversation = useMemo(
    () => conversations.find((item) => item.id === effectiveSelectedConversationId) ?? null,
    [conversations, effectiveSelectedConversationId],
  );
  const activeTaskCount = useMemo(
    () =>
      conversations.reduce((sum, conversation) => {
        const stats = getImageConversationStats(conversation);
        return sum + stats.queued + stats.running;
      }, 0),
    [conversations],
  );
  const viewerRole = viewerSession?.role ?? null;
  const browserHistoryStorageKey = useMemo(
    () =>
      buildBrowserImageHistoryStorageKey(
        viewerRole === "admin" ? "admin" : "user",
        viewerSession?.id || (viewerRole === "admin" ? "admin" : "unknown"),
      ),
    [viewerRole, viewerSession?.id],
  );
  const showConversationOwner = viewerRole === "admin";
  const hasSuccessfulImageResult = useMemo(
    () =>
      conversations.some((conversation) =>
        conversation.turns.some((turn) => turn.images.some((image) => image.status === "success" && image.b64_json)),
      ),
    [conversations],
  );
  const showFirstSuccessBanner = viewerRole === "admin" && onboardingMode === "first-success";
  const deleteConfirmTitle = deleteConfirm?.type === "all" ? "清空历史记录" : deleteConfirm?.type === "one" ? "删除对话" : "";
  const deleteConfirmDescription =
    deleteConfirm?.type === "all"
      ? "确认删除全部图片历史记录吗？删除后无法恢复。"
      : deleteConfirm?.type === "one"
        ? "确认删除这条图片对话吗？删除后无法恢复。"
        : "";

  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      const storedAspectRatio = window.localStorage.getItem(IMAGE_ASPECT_RATIO_STORAGE_KEY);
      if (isImageAspectRatio(storedAspectRatio)) {
        setImageAspectRatio(storedAspectRatio);
      }
      setOnboardingMode(consumeImageOnboardingIntent());
      setDidLoadStoredAspectRatio(true);
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || !didLoadStoredAspectRatio) {
      return;
    }
    window.localStorage.setItem(IMAGE_ASPECT_RATIO_STORAGE_KEY, imageAspectRatio);
  }, [didLoadStoredAspectRatio, imageAspectRatio]);

  useEffect(() => {
    if (!isHistoryModeReady) {
      return;
    }
    let cancelled = false;

    const loadHistory = async () => {
      setIsLoadingHistory(true);
      try {
        const items =
          historyPersistenceMode === "server"
            ? await listImageConversations()
            : await listBrowserImageConversations(browserHistoryStorageKey);
        const normalizedItems = await recoverConversationHistory(items, (conversation) =>
          historyPersistenceMode === "server"
            ? saveImageConversation(conversation)
            : saveBrowserImageConversation(browserHistoryStorageKey, conversation),
        );
        if (cancelled) {
          return;
        }

        conversationsRef.current = normalizedItems;
        setConversations(normalizedItems);
        const storedConversationId =
          typeof window !== "undefined" ? window.localStorage.getItem(ACTIVE_CONVERSATION_STORAGE_KEY) : null;
        const nextSelectedConversationId =
          (storedConversationId && normalizedItems.some((conversation) => conversation.id === storedConversationId)
            ? storedConversationId
            : null) ?? pickFallbackConversationId(normalizedItems);
        setSelectedConversationId(nextSelectedConversationId);
      } catch (error) {
        const message = error instanceof Error ? error.message : "读取会话记录失败";
        toast.error(message);
      } finally {
        if (!cancelled) {
          setIsLoadingHistory(false);
        }
      }
    };

    void loadHistory();
    return () => {
      cancelled = true;
    };
  }, [browserHistoryStorageKey, historyPersistenceMode, isHistoryModeReady]);

  const applyViewerSession = useCallback((session: AuthSession | null) => {
    setViewerSession(session);
    setHistoryPersistenceMode(session?.image_history_persistence_mode === "server" ? "server" : "browser");
    setIsHistoryModeReady(true);
  }, []);

  const loadViewerSession = useCallback(
    async (forceSyncSession = false) => {
      const session = forceSyncSession
        ? await syncStoredAuthSessionWithFallback()
        : await getCachedOrSyncAuthSession();
      applyViewerSession(session);
      return session;
    },
    [applyViewerSession],
  );

  const loadQuota = useCallback(
    async (forceSyncSession = false) => {
      let session: AuthSession | null = null;
      try {
        session = await loadViewerSession(forceSyncSession);
      } catch {
        setAvailableQuota((prev) => (prev === "加载中..." ? "—" : prev));
        return;
      }

      if (!session) {
        setAvailableQuota("—");
        return;
      }
      if (session.role !== "admin") {
        setAvailableQuota(String(Math.max(0, session.image_quota ?? 0)));
        return;
      }

      try {
        const data = await fetchAccounts();
        setAvailableQuota(formatAvailableQuota(data.items));
      } catch {
        setAvailableQuota((prev) => (prev === "加载中..." ? "—" : prev));
      }
    },
    [loadViewerSession],
  );

  useEffect(() => {
    if (didLoadQuotaRef.current) {
      return;
    }
    didLoadQuotaRef.current = true;

    const handleFocus = () => {
      void loadQuota(true);
    };

    void loadQuota(true);
    window.addEventListener("focus", handleFocus);
    return () => {
      window.removeEventListener("focus", handleFocus);
    };
  }, [loadQuota]);

  useEffect(() => {
    if (!selectedConversation || isHistoryOpen || typeof window === "undefined") {
      return;
    }

    const isMobile = window.innerWidth < MOBILE_RESULTS_BREAKPOINT;
    const scrollToEnd = (behavior: ScrollBehavior) => {
      if (isMobile) {
        const scrollingElement = document.scrollingElement ?? document.documentElement;
        window.scrollTo({
          top: scrollingElement.scrollHeight,
          behavior,
        });
        return;
      }

      resultsViewportRef.current?.scrollTo({
        top: resultsViewportRef.current.scrollHeight,
        behavior,
      });
    };

    let frame = 0;
    const retryTimers = RESULTS_SCROLL_RETRY_DELAYS_MS.map((delay) =>
      window.setTimeout(() => {
        scrollToEnd("auto");
      }, delay),
    );
    let observer: ResizeObserver | null = null;
    let settleTimer: number | null = null;
    frame = window.requestAnimationFrame(() => {
      scrollToEnd("smooth");
    });

    const scheduleObserverStop = () => {
      if (settleTimer !== null) {
        window.clearTimeout(settleTimer);
      }
      settleTimer = window.setTimeout(() => {
        observer?.disconnect();
      }, RESULTS_SCROLL_SETTLE_DELAY_MS);
    };

    if (typeof ResizeObserver !== "undefined" && resultsContentRef.current) {
      observer = new ResizeObserver(() => {
        window.cancelAnimationFrame(frame);
        frame = window.requestAnimationFrame(() => {
          scrollToEnd("auto");
        });
        scheduleObserverStop();
      });
      observer.observe(resultsContentRef.current);
      scheduleObserverStop();
    }

    return () => {
      window.cancelAnimationFrame(frame);
      for (const timer of retryTimers) {
        window.clearTimeout(timer);
      }
      if (settleTimer !== null) {
        window.clearTimeout(settleTimer);
      }
      observer?.disconnect();
    };
  }, [isHistoryOpen, selectedConversation?.updatedAt, selectedConversation?.turns.length, selectedConversation]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    if (effectiveSelectedConversationId) {
      window.localStorage.setItem(ACTIVE_CONVERSATION_STORAGE_KEY, effectiveSelectedConversationId);
    } else {
      window.localStorage.removeItem(ACTIVE_CONVERSATION_STORAGE_KEY);
    }
  }, [effectiveSelectedConversationId]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const updatePageBottomState = () => {
      const scrollingElement = document.scrollingElement ?? document.documentElement;
      const distanceToBottom = scrollingElement.scrollHeight - window.scrollY - window.innerHeight;
      const nextIsNearBottom = distanceToBottom < 96;
      setIsNearPageBottom((current) => (current === nextIsNearBottom ? current : nextIsNearBottom));
    };

    updatePageBottomState();
    window.addEventListener("scroll", updatePageBottomState, { passive: true });
    window.addEventListener("resize", updatePageBottomState);
    return () => {
      window.removeEventListener("scroll", updatePageBottomState);
      window.removeEventListener("resize", updatePageBottomState);
    };
  }, []);

  const saveConversationToCurrentStore = useCallback(
    async (conversation: ImageConversation) => {
      if (historyPersistenceMode === "server") {
        await saveImageConversation(conversation);
        return;
      }
      await saveBrowserImageConversation(browserHistoryStorageKey, conversation);
    },
    [browserHistoryStorageKey, historyPersistenceMode],
  );

  const scheduleConversationPersistence = useCallback((conversationId: string) => {
    pendingPersistenceRef.current.add(conversationId);

    const activeTask = persistenceQueueRef.current.get(conversationId);
    if (activeTask) {
      return activeTask;
    }

    const task = (async () => {
      while (pendingPersistenceRef.current.has(conversationId)) {
        pendingPersistenceRef.current.delete(conversationId);
        const conversation = conversationsRef.current.find((item) => item.id === conversationId);
        if (!conversation) {
          continue;
        }
        await saveConversationToCurrentStore(conversation);
      }
    })().finally(() => {
      persistenceQueueRef.current.delete(conversationId);
      pendingPersistenceRef.current.delete(conversationId);
    });

    persistenceQueueRef.current.set(conversationId, task);
    return task;
  }, [saveConversationToCurrentStore]);

  const persistConversation = async (conversation: ImageConversation) => {
    const nextConversations = sortImageConversations([
      conversation,
      ...conversationsRef.current.filter((item) => item.id !== conversation.id),
    ]);
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    await scheduleConversationPersistence(conversation.id);
  };

  const updateConversation = useCallback(
    async (
      conversationId: string,
      updater: (current: ImageConversation | null) => ImageConversation,
      options: { persist?: boolean } = {},
    ) => {
      const current = conversationsRef.current.find((item) => item.id === conversationId) ?? null;
      const nextConversation = updater(current);
      const nextConversations = sortImageConversations([
        nextConversation,
        ...conversationsRef.current.filter((item) => item.id !== conversationId),
      ]);
      conversationsRef.current = nextConversations;
      setConversations(nextConversations);
      if (options.persist !== false) {
        await scheduleConversationPersistence(conversationId);
      }
    },
    [scheduleConversationPersistence],
  );

  const clearComposerInputs = useCallback(() => {
    setImagePrompt("");
    setImageCount("1");
    setReferenceImageFiles([]);
    setReferenceImages([]);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }, []);

  const resetCodexImageOptions = useCallback(() => {
    setImageRenderQuality(DEFAULT_IMAGE_RENDER_QUALITY);
    setImageBackground(DEFAULT_IMAGE_BACKGROUND);
    setImageOutputFormat(DEFAULT_IMAGE_OUTPUT_FORMAT);
    setImageCompression("");
  }, []);

  const handleImageModeChange = useCallback((nextMode: ImageConversationMode) => {
    setImageMode(nextMode);
    if (nextMode === "edit") {
      setImageModel((current) => {
        const nextModel = normalizeImageModelForMode("edit", current);
        if (!isCodexImageModel(nextModel)) {
          resetCodexImageOptions();
        }
        return nextModel;
      });
    }
  }, [resetCodexImageOptions]);

  const handleImageModelChange = useCallback((nextModel: ImageModel) => {
    setImageModel(nextModel);
    if (!isCodexImageModel(nextModel)) {
      resetCodexImageOptions();
    }
  }, [resetCodexImageOptions]);

  const handleImageOutputFormatChange = useCallback((nextFormat: ImageOutputFormat) => {
    setImageOutputFormat(nextFormat);
    if (nextFormat === "png") {
      setImageCompression("");
    }
  }, []);

  const handleImageCompressionChange = useCallback((nextValue: string) => {
    const digitsOnly = nextValue.replace(/[^\d]/g, "").slice(0, 3);
    if (!digitsOnly) {
      setImageCompression("");
      return;
    }
    setImageCompression(String(Math.min(100, Number(digitsOnly))));
  }, []);

  const resetComposer = useCallback(() => {
    handleImageModeChange("generate");
    clearComposerInputs();
  }, [clearComposerInputs, handleImageModeChange]);

  const createDraftConversation = useCallback((): ImageConversation => {
    const now = new Date().toISOString();
    const draftOwnerRole: UserRole = viewerRole === "admin" ? "admin" : "user";
    return {
      id: createId(),
      title: DRAFT_CONVERSATION_TITLE,
      createdAt: now,
      updatedAt: now,
      ownerRole: draftOwnerRole,
      ownerId: viewerSession?.id || (draftOwnerRole === "admin" ? "admin" : "unknown"),
      ownerName: viewerSession?.name || (draftOwnerRole === "admin" ? "管理员" : "普通用户"),
      turns: [],
    };
  }, [viewerRole, viewerSession?.id, viewerSession?.name]);

  const scrollPageToTop = useCallback(() => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const scrollPageToBottom = useCallback(() => {
    const scrollingElement = document.scrollingElement ?? document.documentElement;
    window.scrollTo({ top: scrollingElement.scrollHeight, behavior: "smooth" });
  }, []);

  const focusComposer = useCallback((selectionEnd?: number) => {
    requestAnimationFrame(() => {
      const element = textareaRef.current;
      if (!element) {
        return;
      }
      element.scrollIntoView({ behavior: "smooth", block: "center" });
      element.focus();
      const end = selectionEnd ?? element.value.length;
      element.setSelectionRange(end, end);
    });
  }, []);

  const handleCreateDraft = () => {
    const draftConversation = createDraftConversation();
    const nextConversations = sortImageConversations([
      draftConversation,
      ...conversationsRef.current.filter((conversation) => conversation.turns.length > 0),
    ]);
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    setSelectedConversationId(draftConversation.id);
    resetComposer();
    focusComposer(0);
  };

  const handleTogglePageEdge = () => {
    if (isNearPageBottom) {
      scrollPageToTop();
      return;
    }
    scrollPageToBottom();
  };

  const handleDeleteConversation = async (id: string) => {
    const deletedConversation = conversations.find((item) => item.id === id);
    const nextConversations = conversations.filter((item) => item.id !== id);
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    if (selectedConversationId === id) {
      setSelectedConversationId(pickFallbackConversationId(nextConversations));
      resetComposer();
    }
    if (deletedConversation?.turns.length === 0) {
      return;
    }

    try {
      if (historyPersistenceMode === "server") {
        await deleteImageConversation(id);
      } else {
        await deleteBrowserImageConversation(browserHistoryStorageKey, id);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "删除会话失败";
      toast.error(message);
      const items =
        historyPersistenceMode === "server"
          ? await listImageConversations()
          : await listBrowserImageConversations(browserHistoryStorageKey);
      conversationsRef.current = items;
      setConversations(items);
    }
  };

  const handleRenameConversation = async (id: string, title: string) => {
    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      return;
    }
    const currentConversation = conversationsRef.current.find((item) => item.id === id);
    if (!currentConversation || currentConversation.title === trimmedTitle) {
      return;
    }

    const renamedConversation: ImageConversation = {
      ...currentConversation,
      title: trimmedTitle,
      updatedAt: currentConversation.turns.length > 0 ? new Date().toISOString() : currentConversation.updatedAt,
    };
    const nextConversations = sortImageConversations([
      renamedConversation,
      ...conversationsRef.current.filter((item) => item.id !== id),
    ]);
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);

    if (currentConversation.turns.length === 0) {
      return;
    }

    try {
      await scheduleConversationPersistence(id);
    } catch (error) {
      const message = error instanceof Error ? error.message : "重命名会话失败";
      toast.error(message);
      const items =
        historyPersistenceMode === "server"
          ? await listImageConversations()
          : await listBrowserImageConversations(browserHistoryStorageKey);
      conversationsRef.current = items;
      setConversations(items);
    }
  };

  const handleClearHistory = async () => {
    try {
      if (historyPersistenceMode === "server") {
        await clearImageConversations();
      } else {
        await clearBrowserImageConversations(browserHistoryStorageKey);
      }
      conversationsRef.current = [];
      setConversations([]);
      setSelectedConversationId(null);
      resetComposer();
      toast.success("已清空历史记录");
    } catch (error) {
      const message = error instanceof Error ? error.message : "清空历史记录失败";
      toast.error(message);
    }
  };

  const openDeleteConversationConfirm = (id: string) => {
    setIsHistoryOpen(false);
    setDeleteConfirm({ type: "one", id });
  };

  const openClearHistoryConfirm = () => {
    setIsHistoryOpen(false);
    setDeleteConfirm({ type: "all" });
  };

  const handleConfirmDelete = async () => {
    const target = deleteConfirm;
    setDeleteConfirm(null);
    if (!target) {
      return;
    }
    if (target.type === "all") {
      await handleClearHistory();
      return;
    }
    await handleDeleteConversation(target.id);
  };

  const appendReferenceImages = useCallback(async (files: File[]) => {
    if (files.length === 0) {
      return;
    }

    try {
      const previews = await Promise.all(
        files.map(async (file) => ({
          name: file.name,
          type: file.type || "image/png",
          dataUrl: await readFileAsDataUrl(file),
        })),
      );

      setReferenceImageFiles((prev) => [...prev, ...files]);
      setReferenceImages((prev) => [...prev, ...previews]);
      handleImageModeChange("edit");
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "读取参考图失败";
      toast.error(message);
    }
  }, [handleImageModeChange]);

  const handleReferenceImageChange = useCallback(
    async (files: File[]) => {
      if (files.length === 0) {
        return;
      }

      await appendReferenceImages(files);
    },
    [appendReferenceImages],
  );

  const handleRemoveReferenceImage = useCallback((index: number) => {
    setReferenceImageFiles((prev) => {
      const next = prev.filter((_, currentIndex) => currentIndex !== index);
      if (next.length === 0 && fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      return next;
    });
    setReferenceImages((prev) => prev.filter((_, currentIndex) => currentIndex !== index));
  }, []);

  const prepareReferenceImagesForComposer = useCallback((images: StoredReferenceImage[]) => {
    const nextImages = images.map((image, index) => ({
      name: image.name || `reference-${index + 1}.png`,
      type: image.type || "image/png",
      dataUrl: image.dataUrl,
    }));
    const nextFiles = nextImages.map((image, index) =>
      dataUrlToFile(image.dataUrl, image.name || `reference-${index + 1}.png`, image.type),
    );
    return { nextFiles, nextImages };
  }, []);

  const applyPreparedReferenceImages = useCallback((prepared: {
    nextFiles: File[];
    nextImages: StoredReferenceImage[];
  }) => {
    const { nextFiles, nextImages } = prepared;
    setReferenceImageFiles(nextFiles);
    setReferenceImages(nextImages);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }, []);

  const handleReuseAsReference = useCallback(
    async (payload: { conversationId?: string; id?: string; dataUrl: string }) => {
      try {
        // 验证 dataUrl 包含有效的 base64 内容
        const base64Content = payload.dataUrl.split(",")[1] ?? "";
        if (!base64Content) {
          throw new Error("该图片数据不完整，无法加入参考图（可能来自不同账号或已过期）");
        }
        if (payload.conversationId) {
          setSelectedConversationId(payload.conversationId);
        }
        handleImageModeChange("edit");
        setImagePrompt("");
        const file = dataUrlToFile(payload.dataUrl, `generated-${payload.id || createId()}.png`);
        await appendReferenceImages([file]);
        focusComposer();
        toast.success("已加入当前参考图，继续输入描述即可编辑");
      } catch (error) {
        const message = error instanceof Error ? error.message : "加入参考图失败";
        toast.error(message);
      }
    },
    [appendReferenceImages, focusComposer, handleImageModeChange],
  );

  const handleInpaint = useCallback(
    (payload: { imageDataUrl: string; prompt: string; imageFile: File; conversationId?: string; lastMessageId?: string }) => {
      setMaskEditorImageDataUrl(payload.imageDataUrl);
      setMaskEditorImageFile(payload.imageFile);
      setMaskEditorDefaultPrompt(payload.prompt);
      setMaskEditorConversationId(payload.conversationId ?? "");
      setMaskEditorLastMessageId(payload.lastMessageId ?? "");
      // 收集当前对话里所有成功生成的图供参考图选择
      const available = (selectedConversation?.turns ?? []).flatMap((turn) =>
        turn.status === "success"
          ? turn.images
              .filter((img) => img.status === "success" && img.b64_json)
              .map((img) => ({
                id: img.id,
                dataUrl: `data:${img.mime_type || "image/png"};base64,${img.b64_json ?? ""}`,
              }))
          : [],
      );
      setMaskEditorAvailableImages(available);
      setMaskEditorOpen(true);
    },
    [selectedConversation],
  );

  const handleMaskEditorSubmit = useCallback(
    async (maskFile: File, prompt: string, refImages: File[]) => {
      const imageFile = maskEditorImageFile;
      if (!imageFile) return;
      setMaskEditorOpen(false);

      const conversationId = selectedConversationId ?? createId();
      const turnId = createId();
      const placeholderImageId = createId();

      // 把 File 对象转为 dataUrl 存入 turn，让队列可以在任意时间点读取
      const [origDataUrl, maskDataUrl, ...refDataUrls] = await Promise.all([
        readFileAsDataUrl(imageFile),
        readFileAsDataUrl(maskFile),
        ...refImages.map((f) => readFileAsDataUrl(f)),
      ]);

      setConversations((prev) => {
        const existingIdx = prev.findIndex((c) => c.id === conversationId);
        const inpaintTurn = {
          id: turnId,
          mode: "edit" as ImageConversationMode,
          model: imageModel,
          prompt,
          status: "queued" as const,
          createdAt: new Date().toISOString(),
          referenceImages: refImages.map((f, i) => ({
            name: f.name,
            type: f.type,
            dataUrl: refDataUrls[i] ?? "",
          })),
          count: 1,
          images: [{ id: placeholderImageId, status: "loading" as const }],
          aspectRatio: undefined,
          outputQuality: undefined,
          renderQuality: undefined,
          background: undefined,
          outputFormat: undefined,
          compression: undefined,
          // inpaint 专用：原图与遮罩图，供 runConversationQueue 读取
          inpaintOriginalImage: { name: imageFile.name, type: imageFile.type, dataUrl: origDataUrl },
          inpaintMaskImage: { name: maskFile.name, type: maskFile.type, dataUrl: maskDataUrl },
          inpaintConversationId: maskEditorConversationId || undefined,
          inpaintParentMessageId: maskEditorLastMessageId || undefined,
        };
        if (existingIdx >= 0) {
          const updated = { ...prev[existingIdx] };
          updated.turns = [...updated.turns, inpaintTurn];
          const next = [...prev];
          next[existingIdx] = updated;
          return next;
        }
        return prev;
      });
      setSelectedConversationId(conversationId);

      // 入队后触发队列，和文生图/图生图走同一套流程
      void runConversationQueueRef.current(conversationId);
    },
    [maskEditorImageFile, selectedConversationId, imageModel, maskEditorConversationId, maskEditorLastMessageId],
  );

  const handleReusePrompt = useCallback(
    async (payload: {
      conversationId?: string;
      prompt: string;
      mode: ImageConversationMode;
      model: ImageModel;
      aspectRatio?: ImageAspectRatio;
      outputQuality?: ImageOutputQuality;
      renderQuality?: ImageRenderQuality;
      background?: ImageBackground;
      outputFormat?: ImageOutputFormat;
      compression?: number;
      referenceImages: StoredReferenceImage[];
    }) => {
      const nextPrompt = payload.prompt.trim();
      const referenceCount = payload.referenceImages.length;
      if (!nextPrompt && referenceCount === 0) {
        toast.error("该轮没有可恢复的提示词或参考图");
        return;
      }

      try {
        const restoredReferenceImages = prepareReferenceImagesForComposer(payload.referenceImages);
        if (payload.conversationId) {
          setSelectedConversationId(payload.conversationId);
        }
        const nextMode = payload.mode === "edit" || referenceCount > 0 ? "edit" : "generate";
        const nextModel = normalizeImageModelForMode(nextMode, payload.model);
        setImagePrompt(nextPrompt);
        setImageAspectRatio(payload.aspectRatio ?? "1:1");
        setImageOutputQuality(payload.outputQuality ?? "original");
        if (isCodexImageModel(nextModel)) {
          setImageRenderQuality(payload.renderQuality ?? DEFAULT_IMAGE_RENDER_QUALITY);
          setImageBackground(payload.background ?? DEFAULT_IMAGE_BACKGROUND);
          setImageOutputFormat(payload.outputFormat ?? DEFAULT_IMAGE_OUTPUT_FORMAT);
          setImageCompression(
            payload.outputFormat === "png" ? "" : String(normalizeImageCompression(payload.compression) ?? ""),
          );
        } else {
          resetCodexImageOptions();
        }
        applyPreparedReferenceImages(restoredReferenceImages);
        handleImageModeChange(nextMode);
        setImageModel(nextModel);
        focusComposer(nextPrompt.length);
        toast.success(
          referenceCount > 0 ? `已恢复提示词和 ${referenceCount} 张参考图` : "已恢复提示词到当前输入框",
        );
      } catch (error) {
        const message = error instanceof Error ? error.message : "恢复本轮输入失败";
        toast.error(message);
      }
    },
    [
      applyPreparedReferenceImages,
      focusComposer,
      handleImageModeChange,
      prepareReferenceImagesForComposer,
      resetCodexImageOptions,
    ],
  );

  const openLightbox = useCallback((images: ImageLightboxItem[], index: number) => {
    if (images.length === 0) {
      return;
    }

    setLightboxImages(images);
    setLightboxIndex(Math.max(0, Math.min(index, images.length - 1)));
    setLightboxOpen(true);
  }, []);

  const runConversationQueue = async (conversationId: string) => {
      if (activeConversationQueueIds.has(conversationId)) {
        return;
      }

      const snapshot = conversationsRef.current.find((conversation) => conversation.id === conversationId);
      const queuedTurn = snapshot?.turns.find(
        (turn) => hasPendingTurnWork(turn) && !externallyManagedTurnIds.has(turn.id),
      );
      if (!snapshot || !queuedTurn) {
        return;
      }

      activeConversationQueueIds.add(conversationId);

      try {
        if (queuedTurn.status !== "generating" || queuedTurn.error) {
          await updateConversation(conversationId, (current) => {
            const conversation = current ?? snapshot;
            return {
              ...conversation,
              updatedAt: new Date().toISOString(),
              turns: conversation.turns.map((turn) =>
                turn.id === queuedTurn.id
                  ? {
                      ...turn,
                      status: "generating",
                      error: undefined,
                    }
                  : turn,
              ),
            };
          });
        }
        const referenceFiles = queuedTurn.referenceImages.map((image, index) =>
          dataUrlToFile(image.dataUrl, image.name || `${queuedTurn.id}-${index + 1}.png`, image.type),
        );
        const submittedModel = normalizeImageModelForMode(queuedTurn.mode, queuedTurn.model);
        const useNativeCodexSize = isCodexImageModel(submittedModel);
        const pendingImages = getLoadingImages(queuedTurn);
        const imageJobOptions = buildImageJobRequestOptions({
          model: submittedModel,
          aspectRatio: queuedTurn.aspectRatio,
          outputQuality: queuedTurn.outputQuality ?? "original",
          renderQuality: queuedTurn.renderQuality ?? DEFAULT_IMAGE_RENDER_QUALITY,
          background: queuedTurn.background ?? DEFAULT_IMAGE_BACKGROUND,
          outputFormat: queuedTurn.outputFormat ?? DEFAULT_IMAGE_OUTPUT_FORMAT,
          compression: queuedTurn.compression,
        });
        const submittedPrompt = queuedTurn.prompt.trim();
        const isInpaintTurn = queuedTurn.mode === "edit" && !!queuedTurn.inpaintMaskImage;

        if (queuedTurn.mode === "edit" && !isInpaintTurn && referenceFiles.length === 0) {
          throw new Error("未找到可用于继续编辑的参考图");
        }

        if (pendingImages.length === 0) {
          await updateConversation(conversationId, (current) => {
            const conversation = current ?? snapshot;
            return {
              ...conversation,
              updatedAt: new Date().toISOString(),
              turns: conversation.turns.map((turn) =>
                  turn.id === queuedTurn.id
                    ? {
                        ...turn,
                        ...resolveCompletedTurnState(turn),
                      }
                    : turn,
              ),
            };
          });
          return;
        }

        const tasks = pendingImages.map(async (pendingImage) => {
          try {
            let jobOrId: string | Awaited<ReturnType<typeof createImageGenerationJob>> = pendingImage.job_id || "";
            let jobId = pendingImage.job_id?.trim() || "";

            if (!jobId) {
              let job: Awaited<ReturnType<typeof createImageGenerationJob>>;
              if (isInpaintTurn && queuedTurn.inpaintOriginalImage && queuedTurn.inpaintMaskImage) {
                const origFile = dataUrlToFile(
                  queuedTurn.inpaintOriginalImage.dataUrl,
                  queuedTurn.inpaintOriginalImage.name || "original.png",
                  queuedTurn.inpaintOriginalImage.type,
                );
                const maskFile = dataUrlToFile(
                  queuedTurn.inpaintMaskImage.dataUrl,
                  queuedTurn.inpaintMaskImage.name || "mask.png",
                  queuedTurn.inpaintMaskImage.type,
                );
                job = await createImageInpaintJob(origFile, maskFile, submittedPrompt, submittedModel, {
                  refImages: referenceFiles.length > 0 ? referenceFiles : undefined,
                  conversationId: queuedTurn.inpaintConversationId,
                  parentMessageId: queuedTurn.inpaintParentMessageId,
                });
              } else if (queuedTurn.mode === "edit") {
                job = await createImageEditJob(referenceFiles, submittedPrompt, submittedModel, imageJobOptions);
              } else {
                job = await createImageGenerationJob(submittedPrompt, submittedModel, imageJobOptions);
              }
              jobOrId = job;
              jobId = job.id;

              await updateConversation(conversationId, (current) => {
                const conversation = current ?? snapshot;
                return {
                  ...conversation,
                  updatedAt: new Date().toISOString(),
                  turns: conversation.turns.map((turn) =>
                    turn.id === queuedTurn.id
                      ? {
                          ...turn,
                          status: "generating",
                          error: undefined,
                          images: turn.images.map((image) =>
                            image.id === pendingImage.id
                              ? {
                                  ...image,
                                  status: "loading",
                                  error: undefined,
                                  job_id: jobId,
                                }
                              : image,
                          ),
                        }
                      : turn,
                  ),
                };
              });
            }

            const data = await waitForImageJob<GeneratedImageResponse>(jobOrId);
            const first = data.data?.[0];
            if (!first?.b64_json) {
              throw new Error("未返回图片数据");
            }

            let b64Json = first.b64_json;
            let mimeType = first.mime_type || "image/png";
            if (!useNativeCodexSize && queuedTurn.outputQuality && queuedTurn.outputQuality !== "original") {
              try {
                const upscaled = await upscaleGeneratedImage(first.b64_json, first.mime_type, queuedTurn.outputQuality);
                b64Json = upscaled.b64_json;
                mimeType = upscaled.mime_type;
              } catch (error) {
                const message = error instanceof Error ? error.message : "本地高清放大失败";
                toast.warning(`${message}，已保留原图输出`);
              }
            }

            const nextImage: StoredImage = {
              id: pendingImage.id,
              status: "success",
              b64_json: b64Json,
              mime_type: mimeType,
              generation_route: first.generation_route,
              conversation_id: first.conversation_id || undefined,
              last_message_id: first.last_message_id || undefined,
            };

            await updateConversation(conversationId, (current) => {
              const conversation = current ?? snapshot;
              return {
                ...conversation,
                updatedAt: new Date().toISOString(),
                turns: conversation.turns.map((turn) =>
                  turn.id === queuedTurn.id
                    ? {
                        ...turn,
                        images: turn.images.map((image) => (image.id === nextImage.id ? nextImage : image)),
                      }
                    : turn,
                ),
              };
            });

            return nextImage;
          } catch (error) {
            const message = error instanceof Error ? error.message : "生成失败";
            const failedImage: StoredImage = {
              id: pendingImage.id,
              status: "error",
              error: message,
            };

            await updateConversation(conversationId, (current) => {
              const conversation = current ?? snapshot;
              return {
                ...conversation,
                updatedAt: new Date().toISOString(),
                turns: conversation.turns.map((turn) =>
                  turn.id === queuedTurn.id
                    ? {
                        ...turn,
                        images: turn.images.map((image) => (image.id === failedImage.id ? failedImage : image)),
                      }
                    : turn,
                ),
              };
            });

            throw error;
          }
        });

        await Promise.allSettled(tasks);
        await updateConversation(conversationId, (current) => {
          const conversation = current ?? snapshot;
          return {
            ...conversation,
            updatedAt: new Date().toISOString(),
            turns: conversation.turns.map((turn) =>
              turn.id === queuedTurn.id
                ? {
                    ...turn,
                    ...resolveCompletedTurnState(turn),
                  }
                : turn,
            ),
          };
        });

        await loadQuota();
      } catch (error) {
        const message = error instanceof Error ? error.message : "生成图片失败";
        await updateConversation(conversationId, (current) => {
          const conversation = current ?? snapshot;
          return {
            ...conversation,
            updatedAt: new Date().toISOString(),
            turns: conversation.turns.map((turn) =>
              turn.id === queuedTurn.id
                ? {
                    ...turn,
                    status: "error",
                    error: message,
                    images: turn.images.map((image) =>
                      image.status === "loading" ? { ...image, status: "error", error: message, job_id: undefined } : image,
                    ),
                  }
                : turn,
            ),
          };
        });
        toast.error(message);
      } finally {
        activeConversationQueueIds.delete(conversationId);
        for (const conversation of conversationsRef.current) {
          if (
            !activeConversationQueueIds.has(conversation.id) &&
            conversation.turns.some(hasPendingTurnWork)
          ) {
            void runConversationQueueRef.current(conversation.id);
          }
        }
      }
    };

  useEffect(() => {
    runConversationQueueRef.current = runConversationQueue;
  });

  useEffect(() => {
    for (const conversation of conversations) {
      if (
        !activeConversationQueueIds.has(conversation.id) &&
        conversation.turns.some(hasPendingTurnWork)
      ) {
        void runConversationQueueRef.current(conversation.id);
      }
    }
  }, [conversations]);

  const handleSubmit = async () => {
    const prompt = imagePrompt.trim();
    if (!prompt) {
      toast.error("请输入提示词");
      return;
    }

    if (imageMode === "edit" && referenceImageFiles.length === 0) {
      toast.error("请先上传参考图");
      return;
    }
    const targetConversation = selectedConversationId
      ? conversationsRef.current.find((conversation) => conversation.id === selectedConversationId) ?? null
      : null;
    const now = new Date().toISOString();
    const conversationId = targetConversation?.id ?? createId();
    const turnId = createId();
    const draftOwnerRole: UserRole = viewerRole === "admin" ? "admin" : "user";
    const draftOwnerId = viewerSession?.id || (draftOwnerRole === "admin" ? "admin" : "unknown");
    const draftOwnerName = viewerSession?.name || (draftOwnerRole === "admin" ? "管理员" : "普通用户");
    const submittedModel = normalizeImageModelForMode(imageMode, imageModel);
    const draftTurn: ImageTurn = {
      id: turnId,
      prompt,
      model: submittedModel,
      mode: imageMode,
      aspectRatio: imageAspectRatio,
      outputQuality: imageOutputQuality,
      renderQuality: isCodexImageModel(submittedModel) ? imageRenderQuality : undefined,
      background: isCodexImageModel(submittedModel) ? imageBackground : undefined,
      outputFormat: isCodexImageModel(submittedModel) ? imageOutputFormat : undefined,
      compression:
        isCodexImageModel(submittedModel) && imageOutputFormat !== "png"
          ? normalizeImageCompression(imageCompression)
          : undefined,
      referenceImages: imageMode === "edit" ? referenceImages : [],
      count: parsedCount,
      images: Array.from({ length: parsedCount }, (_, index) => ({
        id: `${turnId}-${index}`,
        status: "loading" as const,
      })),
      createdAt: now,
      status: "queued",
    };

    const baseConversation: ImageConversation = targetConversation
      ? {
          ...targetConversation,
          title:
            targetConversation.turns.length === 0 || targetConversation.title === DRAFT_CONVERSATION_TITLE
              ? buildConversationTitle(prompt)
              : targetConversation.title,
          updatedAt: now,
          turns: [...targetConversation.turns, draftTurn],
        }
      : {
          id: conversationId,
          title: buildConversationTitle(prompt),
          createdAt: now,
          updatedAt: now,
          ownerRole: draftOwnerRole,
          ownerId: draftOwnerId,
          ownerName: draftOwnerName,
          turns: [draftTurn],
        };

    setSelectedConversationId(conversationId);
    clearComposerInputs();

    await persistConversation(baseConversation);
    void runConversationQueue(conversationId);

    const targetStats = getImageConversationStats(baseConversation);
    if (targetStats.running > 0 || targetStats.queued > 1) {
      toast.success("已加入当前对话队列");
    } else if (!targetConversation) {
      toast.success("已创建新对话并开始处理");
    } else {
      toast.success("已发送到当前对话");
    }
  };

  return (
    <>
      <section className="mx-auto grid min-h-[calc(100dvh-5rem)] w-full max-w-[1380px] grid-cols-1 gap-2 px-0 pb-[calc(env(safe-area-inset-bottom)+0.5rem)] sm:gap-3 sm:px-3 sm:pb-6 lg:h-[calc(100dvh-5rem)] lg:min-h-0 lg:grid-cols-[240px_minmax(0,1fr)]">
        <div className="hidden min-h-0 lg:block">
          <ImageSidebar
            conversations={conversations}
            showConversationOwner={showConversationOwner}
            isLoadingHistory={isLoadingHistory}
            selectedConversationId={selectedConversationId}
            onCreateDraft={handleCreateDraft}
            onClearHistory={openClearHistoryConfirm}
            onSelectConversation={setSelectedConversationId}
            onDeleteConversation={openDeleteConversationConfirm}
            onRenameConversation={handleRenameConversation}
            formatConversationTime={formatConversationTime}
          />
        </div>

        <div className="flex min-h-0 flex-col gap-2 sm:gap-4">
          <div className="sticky top-2 z-30 -mx-1 flex items-center justify-between gap-3 rounded-[28px] border border-white/80 bg-white/85 p-2 shadow-[0_16px_45px_rgba(28,25,23,0.14)] backdrop-blur-xl lg:hidden">
            <Button
              variant="outline"
              className="h-11 flex-1 rounded-2xl border-stone-200 bg-white/90 text-stone-700 shadow-sm hover:bg-white"
              onClick={() => setIsHistoryOpen(true)}
            >
              <History className="size-4" />
              历史记录 ({conversations.length})
            </Button>
            <Button
              type="button"
              variant="outline"
              className="h-11 w-11 shrink-0 rounded-2xl border-stone-200 bg-white/90 px-0 text-stone-700 shadow-sm hover:bg-white"
              onClick={handleTogglePageEdge}
              aria-label={isNearPageBottom ? "回到页面顶部" : "跳到页面底部"}
              title={isNearPageBottom ? "回到顶部" : "跳到底部"}
            >
              {isNearPageBottom ? <ArrowUpToLine className="size-4" /> : <ArrowDownToLine className="size-4" />}
            </Button>
            <Button
              className="h-11 rounded-2xl bg-stone-950 px-4 text-white shadow-sm hover:bg-stone-800"
              onClick={handleCreateDraft}
            >
              <Plus className="size-4" />
              新建
            </Button>
          </div>

          {showFirstSuccessBanner ? (
            <div
              className={
                hasSuccessfulImageResult
                  ? "rounded-[24px] border border-emerald-200 bg-emerald-50 px-4 py-3 text-emerald-950 shadow-sm"
                  : "rounded-[24px] border border-amber-200 bg-amber-50 px-4 py-3 text-amber-950 shadow-sm"
              }
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="space-y-1">
                  <div className="text-sm font-semibold">
                    {hasSuccessfulImageResult ? "首次出图已完成" : "现在就差完成第一张图"}
                  </div>
                  <p className="text-sm leading-6">
                    {hasSuccessfulImageResult
                      ? "已经检测到成功出图记录，这条首次成功路径已经打通。"
                      : "用当前工作台完成一次成功生成后，返回账号页就能看到首次成功路径全部完成。"}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    asChild
                    variant={hasSuccessfulImageResult ? "default" : "outline"}
                    className={
                      hasSuccessfulImageResult
                        ? "h-9 rounded-xl bg-emerald-700 px-4 text-white hover:bg-emerald-800"
                        : "h-9 rounded-xl border-amber-300 bg-white/80 px-4 text-amber-900 hover:bg-white"
                    }
                  >
                    <Link href="/accounts">{hasSuccessfulImageResult ? "返回账号页查看完成状态" : "稍后返回账号页确认"}</Link>
                  </Button>
                </div>
              </div>
            </div>
          ) : null}

          <div
            ref={resultsViewportRef}
            className="min-h-[220px] px-1 py-2 sm:px-4 sm:py-4 lg:min-h-0 lg:flex-1 lg:overflow-y-auto"
          >
            <div ref={resultsContentRef}>
              <ImageResults
                selectedConversation={selectedConversation}
                showConversationOwner={showConversationOwner}
                onOpenLightbox={openLightbox}
                onReuseAsReference={handleReuseAsReference}
                onInpaint={handleInpaint}
                onReusePrompt={handleReusePrompt}
                formatConversationTime={formatConversationTime}
              />
            </div>
          </div>

          <div
            onWheel={(e) => {
              const vp = resultsViewportRef.current;
              if (!vp) return;
              vp.scrollTop += e.deltaY;
            }}
          >
          <ImageComposer
            mode={imageMode}
            model={imageModel}
            prompt={imagePrompt}
            aspectRatio={imageAspectRatio}
            imageCount={imageCount}
            outputQuality={imageOutputQuality}
            renderQuality={imageRenderQuality}
            background={imageBackground}
            outputFormat={imageOutputFormat}
            compressionValue={imageCompression}
            availableQuota={availableQuota}
            activeTaskCount={activeTaskCount}
            referenceImages={referenceImages}
            textareaRef={textareaRef}
            fileInputRef={fileInputRef}
            onModeChange={handleImageModeChange}
            onModelChange={handleImageModelChange}
            onPromptChange={setImagePrompt}
            onAspectRatioChange={setImageAspectRatio}
            onImageCountChange={setImageCount}
            onOutputQualityChange={setImageOutputQuality}
            onRenderQualityChange={setImageRenderQuality}
            onBackgroundChange={setImageBackground}
            onOutputFormatChange={handleImageOutputFormatChange}
            onCompressionChange={handleImageCompressionChange}
            onSubmit={handleSubmit}
            onPickReferenceImage={() => fileInputRef.current?.click()}
            onReferenceImageChange={handleReferenceImageChange}
            onReferenceImageReuse={handleReuseAsReference}
            onRemoveReferenceImage={handleRemoveReferenceImage}
          />
          </div>
        </div>
      </section>

      <Dialog open={isHistoryOpen} onOpenChange={setIsHistoryOpen}>
        <DialogContent className="flex h-[80vh] w-[92vw] max-w-[420px] flex-col overflow-hidden rounded-[32px] border-stone-200 bg-white p-0 shadow-2xl">
          <DialogHeader className="px-6 pt-6 pb-2">
            <DialogTitle className="flex items-center gap-2 text-lg font-bold">
              <History className="size-5" />
              历史记录
            </DialogTitle>
          </DialogHeader>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-8">
            <ImageSidebar
              conversations={conversations}
              className="border-r-0 pr-0"
              hideActionButtons
              showConversationOwner={showConversationOwner}
              isLoadingHistory={isLoadingHistory}
              selectedConversationId={selectedConversationId}
              onCreateDraft={() => {
                handleCreateDraft();
                setIsHistoryOpen(false);
              }}
              onClearHistory={openClearHistoryConfirm}
              onSelectConversation={(id) => {
                setSelectedConversationId(id);
                setIsHistoryOpen(false);
              }}
              onDeleteConversation={openDeleteConversationConfirm}
              onRenameConversation={handleRenameConversation}
              formatConversationTime={formatConversationTime}
            />
          </div>
        </DialogContent>
      </Dialog>

        {deleteConfirm ? (
          <Dialog open onOpenChange={(open) => (!open ? setDeleteConfirm(null) : null)}>
            <DialogContent showCloseButton={false} className="rounded-2xl p-6">
              <DialogHeader className="gap-2">
                <DialogTitle>{deleteConfirmTitle}</DialogTitle>
                <DialogDescription className="text-sm leading-6">
                  {deleteConfirmDescription}
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="outline" onClick={() => setDeleteConfirm(null)}>
                  取消
                </Button>
                <Button className="bg-rose-600 text-white hover:bg-rose-700" onClick={() => void handleConfirmDelete()}>
                  确认删除
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        ) : null}

      <ImageLightbox
        images={lightboxImages}
        currentIndex={lightboxIndex}
        open={lightboxOpen}
        onOpenChange={setLightboxOpen}
        onIndexChange={setLightboxIndex}
      />

      <MaskEditorDialog
        open={maskEditorOpen}
        imageDataUrl={maskEditorImageDataUrl}
        defaultPrompt={maskEditorDefaultPrompt}
        availableImages={maskEditorAvailableImages}
        onClose={() => setMaskEditorOpen(false)}
        onSubmit={handleMaskEditorSubmit}
      />
    </>
  );
}
