"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { History, Plus } from "lucide-react";
import { toast } from "sonner";

import { ImageComposer } from "@/app/image/components/image-composer";
import { ImageResults, type ImageLightboxItem } from "@/app/image/components/image-results";
import { ImageSidebar } from "@/app/image/components/image-sidebar";
import { ImageLightbox } from "@/components/image-lightbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { getCachedOrSyncAuthSession, syncStoredAuthSessionWithFallback } from "@/lib/auth-session";
import type { AuthSession, ImageHistoryPersistenceMode, UserRole } from "@/lib/auth-types";
import {
  editImage,
  fetchAccounts,
  generateImage,
  type Account,
  type ImageModel,
} from "@/lib/api";
import {
  applyAspectRatioPrompt,
  isImageAspectRatio,
  type ImageAspectRatio,
  type ImageOutputQuality,
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
  type ImageTurnStatus,
  type StoredImage,
  type StoredReferenceImage,
} from "@/store/image-conversations";

const DEFAULT_IMAGE_MODEL: ImageModel = "gpt-image-2";
const ACTIVE_CONVERSATION_STORAGE_KEY = "chatgpt2api:image_active_conversation_id";
const IMAGE_ASPECT_RATIO_STORAGE_KEY = "chatgpt2api:image_last_aspect_ratio";
const activeConversationQueueIds = new Set<string>();

function buildConversationTitle(prompt: string) {
  const trimmed = prompt.trim();
  if (trimmed.length <= 12) {
    return trimmed;
  }
  return `${trimmed.slice(0, 12)}...`;
}

function formatConversationTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
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
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
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
      if (turn.status !== "queued" && turn.status !== "generating") {
        return turn;
      }

      const loadingCount = turn.images.filter((image) => image.status === "loading").length;
      if (loadingCount > 0) {
        const message = "页面刷新或任务中断，未完成的图片已标记为失败";
        changed = true;
        return {
          ...turn,
          status: "error" as const,
          error: message,
          images: turn.images.map((image) =>
            image.status === "loading" ? { ...image, status: "error" as const, error: message } : image,
          ),
        };
      }

      const failedCount = turn.images.filter((image) => image.status === "error").length;
      const successCount = turn.images.filter((image) => image.status === "success").length;
      const nextStatus: ImageTurnStatus =
        failedCount > 0 ? "error" : successCount > 0 ? "success" : "queued";
      const nextError = failedCount > 0 ? turn.error || `其中 ${failedCount} 张未成功生成` : undefined;
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [imagePrompt, setImagePrompt] = useState("");
  const [imageCount, setImageCount] = useState("1");
  const [imageMode, setImageMode] = useState<ImageConversationMode>("generate");
  const [imageModel, setImageModel] = useState<ImageModel>(DEFAULT_IMAGE_MODEL);
  const [imageAspectRatio, setImageAspectRatio] = useState<ImageAspectRatio>(() => {
    if (typeof window === "undefined") {
      return "1:1";
    }
    const storedAspectRatio = window.localStorage.getItem(IMAGE_ASPECT_RATIO_STORAGE_KEY);
    return isImageAspectRatio(storedAspectRatio) ? storedAspectRatio : "1:1";
  });
  const [imageOutputQuality, setImageOutputQuality] = useState<ImageOutputQuality>("original");
  const [referenceImageFiles, setReferenceImageFiles] = useState<File[]>([]);
  const [referenceImages, setReferenceImages] = useState<StoredReferenceImage[]>([]);
  const [conversations, setConversations] = useState<ImageConversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [availableQuota, setAvailableQuota] = useState("加载中...");
  const [viewerSession, setViewerSession] = useState<AuthSession | null>(null);
  const [onboardingMode] = useState<string | null>(() => consumeImageOnboardingIntent());
  const [historyPersistenceMode, setHistoryPersistenceMode] = useState<ImageHistoryPersistenceMode>("browser");
  const [isHistoryModeReady, setIsHistoryModeReady] = useState(false);
  const [lightboxImages, setLightboxImages] = useState<ImageLightboxItem[]>([]);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState(0);

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

  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(IMAGE_ASPECT_RATIO_STORAGE_KEY, imageAspectRatio);
  }, [imageAspectRatio]);

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
    if (!selectedConversation) {
      return;
    }

    if (typeof window !== "undefined" && window.innerWidth < 1024) {
      resultsViewportRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
      return;
    }

    resultsViewportRef.current?.scrollTo({
      top: resultsViewportRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [selectedConversation?.updatedAt, selectedConversation?.turns.length, selectedConversation]);

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

  const handleImageModeChange = useCallback((nextMode: ImageConversationMode) => {
    setImageMode(nextMode);
    if (nextMode === "edit") {
      setImageModel("gpt-image-2");
    }
  }, []);

  const resetComposer = useCallback(() => {
    handleImageModeChange("generate");
    clearComposerInputs();
  }, [clearComposerInputs, handleImageModeChange]);

  const handleCreateDraft = () => {
    setSelectedConversationId(null);
    resetComposer();
    textareaRef.current?.focus();
  };

  const handleDeleteConversation = async (id: string) => {
    const nextConversations = conversations.filter((item) => item.id !== id);
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    if (selectedConversationId === id) {
      setSelectedConversationId(pickFallbackConversationId(nextConversations));
      resetComposer();
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

  const handleReusePrompt = useCallback(
    async (payload: { conversationId?: string; prompt: string; referenceImages: StoredReferenceImage[] }) => {
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
        setImagePrompt(nextPrompt);
        applyPreparedReferenceImages(restoredReferenceImages);
        handleImageModeChange(referenceCount > 0 ? "edit" : "generate");
        focusComposer(nextPrompt.length);
        toast.success(
          referenceCount > 0 ? `已恢复提示词和 ${referenceCount} 张参考图` : "已恢复提示词到当前输入框",
        );
      } catch (error) {
        const message = error instanceof Error ? error.message : "恢复本轮输入失败";
        toast.error(message);
      }
    },
    [applyPreparedReferenceImages, focusComposer, handleImageModeChange, prepareReferenceImagesForComposer],
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
      const queuedTurn = snapshot?.turns.find((turn) => turn.status === "queued");
      if (!snapshot || !queuedTurn) {
        return;
      }

      activeConversationQueueIds.add(conversationId);
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

      try {
        const referenceFiles = queuedTurn.referenceImages.map((image, index) =>
          dataUrlToFile(image.dataUrl, image.name || `${queuedTurn.id}-${index + 1}.png`, image.type),
        );
        const pendingImages = queuedTurn.images.filter((image) => image.status === "loading");
        const submittedPrompt = applyAspectRatioPrompt(queuedTurn.prompt, queuedTurn.aspectRatio);
        const submittedModel = queuedTurn.mode === "edit" ? "gpt-image-2" : queuedTurn.model;

        if (queuedTurn.mode === "edit" && referenceFiles.length === 0) {
          throw new Error("未找到可用于继续编辑的参考图");
        }

        if (pendingImages.length === 0) {
          const existingFailedCount = queuedTurn.images.filter((image) => image.status === "error").length;
          const existingSuccessCount = queuedTurn.images.filter((image) => image.status === "success").length;
          await updateConversation(conversationId, (current) => {
            const conversation = current ?? snapshot;
            return {
              ...conversation,
              updatedAt: new Date().toISOString(),
              turns: conversation.turns.map((turn) =>
                turn.id === queuedTurn.id
                  ? {
                      ...turn,
                      status: existingFailedCount > 0 ? "error" : existingSuccessCount > 0 ? "success" : "queued",
                      error: existingFailedCount > 0 ? `其中 ${existingFailedCount} 张未成功生成` : undefined,
                    }
                  : turn,
              ),
            };
          });
          return;
        }

        const tasks = pendingImages.map(async (pendingImage) => {
          try {
            const data =
              queuedTurn.mode === "edit"
                ? await editImage(referenceFiles, submittedPrompt, submittedModel)
                : await generateImage(submittedPrompt, submittedModel);
            const first = data.data?.[0];
            if (!first?.b64_json) {
              throw new Error("未返回图片数据");
            }

            let b64Json = first.b64_json;
            let mimeType = first.mime_type || "image/png";
            if (queuedTurn.outputQuality && queuedTurn.outputQuality !== "original") {
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
            };

            await updateConversation(
              conversationId,
              (current) => {
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
              },
              { persist: false },
            );

            return nextImage;
          } catch (error) {
            const message = error instanceof Error ? error.message : "生成失败";
            const failedImage: StoredImage = {
              id: pendingImage.id,
              status: "error",
              error: message,
            };

            await updateConversation(
              conversationId,
              (current) => {
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
              },
              { persist: false },
            );

            throw error;
          }
        });

        const settled = await Promise.allSettled(tasks);
        const resumedSuccessCount = settled.filter(
          (item): item is PromiseFulfilledResult<StoredImage> => item.status === "fulfilled",
        ).length;
        const resumedFailedCount = settled.length - resumedSuccessCount;
        const existingSuccessCount = queuedTurn.images.filter((image) => image.status === "success").length;
        const existingFailedCount = queuedTurn.images.filter((image) => image.status === "error").length;
        const successCount = existingSuccessCount + resumedSuccessCount;
        const failedCount = existingFailedCount + resumedFailedCount;

        await updateConversation(conversationId, (current) => {
          const conversation = current ?? snapshot;
          return {
            ...conversation,
            updatedAt: new Date().toISOString(),
            turns: conversation.turns.map((turn) =>
              turn.id === queuedTurn.id
                ? {
                    ...turn,
                    status: failedCount > 0 ? "error" : "success",
                    error: failedCount > 0 ? `其中 ${failedCount} 张未成功生成` : undefined,
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
                      image.status === "loading" ? { ...image, status: "error", error: message } : image,
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
            conversation.turns.some((turn) => turn.status === "queued")
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
        conversation.turns.some((turn) => turn.status === "queued")
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
    const draftTurn: ImageTurn = {
      id: turnId,
      prompt,
      model: imageMode === "edit" ? "gpt-image-2" : imageModel,
      mode: imageMode,
      aspectRatio: imageAspectRatio,
      outputQuality: imageOutputQuality,
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
      <section className="mx-auto grid min-h-[calc(100dvh-5rem)] w-full max-w-[1380px] grid-cols-1 gap-3 px-3 pb-6 lg:h-[calc(100dvh-5rem)] lg:min-h-0 lg:grid-cols-[240px_minmax(0,1fr)]">
        <div className="hidden min-h-0 lg:block">
          <ImageSidebar
            conversations={conversations}
            showConversationOwner={showConversationOwner}
            isLoadingHistory={isLoadingHistory}
            selectedConversationId={selectedConversationId}
            onCreateDraft={handleCreateDraft}
            onClearHistory={handleClearHistory}
            onSelectConversation={setSelectedConversationId}
            onDeleteConversation={handleDeleteConversation}
            formatConversationTime={formatConversationTime}
          />
        </div>

        <div className="flex min-h-0 flex-col gap-3 sm:gap-4">
          <div className="flex items-center justify-between gap-3 lg:hidden">
            <Button
              variant="outline"
              className="h-10 flex-1 rounded-2xl border-stone-200 bg-white/85 text-stone-700 shadow-sm"
              onClick={() => setIsHistoryOpen(true)}
            >
              <History className="size-4" />
              历史记录 ({conversations.length})
            </Button>
            <Button
              className="h-10 rounded-2xl bg-stone-950 px-3 text-white shadow-sm hover:bg-stone-800"
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
            className="min-h-[220px] px-2 py-3 sm:px-4 sm:py-4 lg:min-h-0 lg:flex-1 lg:overflow-y-auto"
          >
            <ImageResults
              selectedConversation={selectedConversation}
              showConversationOwner={showConversationOwner}
              onOpenLightbox={openLightbox}
              onReuseAsReference={handleReuseAsReference}
              onReusePrompt={handleReusePrompt}
              formatConversationTime={formatConversationTime}
            />
          </div>

          <ImageComposer
            mode={imageMode}
            model={imageModel}
            prompt={imagePrompt}
            aspectRatio={imageAspectRatio}
            imageCount={imageCount}
            outputQuality={imageOutputQuality}
            availableQuota={availableQuota}
            activeTaskCount={activeTaskCount}
            referenceImages={referenceImages}
            textareaRef={textareaRef}
            fileInputRef={fileInputRef}
            onModeChange={handleImageModeChange}
            onModelChange={setImageModel}
            onPromptChange={setImagePrompt}
            onAspectRatioChange={setImageAspectRatio}
            onImageCountChange={setImageCount}
            onOutputQualityChange={setImageOutputQuality}
            onSubmit={handleSubmit}
            onPickReferenceImage={() => fileInputRef.current?.click()}
            onReferenceImageChange={handleReferenceImageChange}
            onReferenceImageReuse={handleReuseAsReference}
            onRemoveReferenceImage={handleRemoveReferenceImage}
          />
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
              showConversationOwner={showConversationOwner}
              isLoadingHistory={isLoadingHistory}
              selectedConversationId={selectedConversationId}
              onCreateDraft={() => {
                handleCreateDraft();
                setIsHistoryOpen(false);
              }}
              onClearHistory={async () => {
                await handleClearHistory();
                setIsHistoryOpen(false);
              }}
              onSelectConversation={(id) => {
                setSelectedConversationId(id);
                setIsHistoryOpen(false);
              }}
              onDeleteConversation={handleDeleteConversation}
              formatConversationTime={formatConversationTime}
            />
          </div>
        </DialogContent>
      </Dialog>

      <ImageLightbox
        images={lightboxImages}
        currentIndex={lightboxIndex}
        open={lightboxOpen}
        onOpenChange={setLightboxOpen}
        onIndexChange={setLightboxIndex}
      />
    </>
  );
}
