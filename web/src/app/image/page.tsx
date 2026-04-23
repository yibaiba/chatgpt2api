"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { ImageLightbox } from "@/components/image-lightbox";
import {
  editImage,
  fetchAccounts,
  generateImage,
  type Account,
  type ImageBackground,
  type ImageModel,
  type ImageOutputFormat,
  type ImageQuality,
  type ImageRequestOptions,
} from "@/lib/api";
import type { UserRole } from "@/lib/auth-types";
import { getCachedOrSyncAuthSession, syncStoredAuthSession } from "@/lib/auth-session";
import { ImageComposer } from "@/app/image/components/image-composer";
import { ImageResults } from "@/app/image/components/image-results";
import { ImageSidebar } from "@/app/image/components/image-sidebar";
import {
  clearImageConversations,
  deleteImageConversation,
  listImageConversations,
  saveImageConversation,
  type ImageConversation,
  type ImageConversationMode,
  type StoredImage,
  type StoredReferenceImage,
} from "@/store/image-conversations";

const imageModelOptions: Array<{ label: string; value: ImageModel }> = [
  { label: "auto", value: "auto" },
  { label: "gpt-image-1", value: "gpt-image-1" },
  { label: "gpt-image-2", value: "gpt-image-2" },
];
const imageSizeSuggestions = [
  "auto",
  "1024x1024",
  "1536x1024",
  "1024x1536",
  "2048x2048",
  "2048x1152",
  "3840x2160",
  "2160x3840",
];
const imageQualityOptions: Array<{ label: string; value: ImageQuality }> = [
  { label: "自动质量", value: "auto" },
  { label: "低", value: "low" },
  { label: "中", value: "medium" },
  { label: "高", value: "high" },
];
const imageBackgroundOptions: Array<{ label: string; value: ImageBackground }> = [
  { label: "自动背景", value: "auto" },
  { label: "透明", value: "transparent" },
  { label: "不透明", value: "opaque" },
];
const imageOutputFormatOptions: Array<{ label: string; value: ImageOutputFormat }> = [
  { label: "PNG", value: "png" },
  { label: "JPEG", value: "jpeg" },
  { label: "WEBP", value: "webp" },
];
const ACTIVE_CONVERSATION_STORAGE_KEY = "chatgpt2api:image_active_conversation_id";
const ACTIVE_IMAGE_GENERATION_STORAGE_KEY = "chatgpt2api:image-active-generating-ids";

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
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("读取参考图失败"));
    reader.readAsDataURL(file);
  });
}

function dataUrlToFile(dataUrl: string, fileName: string) {
  const [header, encoded = ""] = dataUrl.split(",", 2);
  const mimeMatch = header.match(/^data:(.*?)(;base64)?$/i);
  const mimeType = mimeMatch?.[1] || "image/png";
  const binary = atob(encoded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new File([bytes], fileName, { type: mimeType });
}

function buildGeneratedImageDataUrl(image: Pick<StoredImage, "b64_json" | "mime_type">) {
  return `data:${image.mime_type || "image/png"};base64,${image.b64_json}`;
}

function sortImageConversations(conversations: ImageConversation[]) {
  return [...conversations].sort((a, b) => (b.updatedAt || b.createdAt).localeCompare(a.updatedAt || a.createdAt));
}

function pickFallbackConversationId(conversations: ImageConversation[]) {
  const activeConversation = conversations.find((conversation) => conversation.status === "generating");
  return activeConversation?.id ?? conversations[0]?.id ?? null;
}

function readActiveConversationId() {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(ACTIVE_CONVERSATION_STORAGE_KEY);
}

function writeActiveConversationId(conversationId: string | null) {
  if (typeof window === "undefined") {
    return;
  }
  const normalized = String(conversationId || "").trim();
  if (!normalized) {
    window.localStorage.removeItem(ACTIVE_CONVERSATION_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(ACTIVE_CONVERSATION_STORAGE_KEY, normalized);
}

function readActiveGeneratingConversationIds(): string[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    const raw = window.localStorage.getItem(ACTIVE_IMAGE_GENERATION_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.map((item) => String(item)) : [];
  } catch {
    return [];
  }
}

function writeActiveGeneratingConversationIds(ids: Iterable<string>) {
  if (typeof window === "undefined") {
    return;
  }
  const normalized = Array.from(new Set(Array.from(ids, (id) => String(id).trim()).filter(Boolean)));
  if (normalized.length === 0) {
    window.localStorage.removeItem(ACTIVE_IMAGE_GENERATION_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(ACTIVE_IMAGE_GENERATION_STORAGE_KEY, JSON.stringify(normalized));
}

async function recoverInterruptedConversations(items: ImageConversation[]) {
  const activeIds = new Set(readActiveGeneratingConversationIds());
  if (activeIds.size === 0) {
    return items;
  }

  const interruptedMessage = "页面刷新或任务中断，未完成的图片已标记为失败";
  const recoveredAt = new Date().toISOString();
  const nextItems = items.map((conversation) => {
    if (!activeIds.has(conversation.id) || conversation.status !== "generating") {
      return conversation;
    }

    let changed = false;
    const images = conversation.images.map((image) => {
      if (image.status !== "loading") {
        return image;
      }
      changed = true;
      return {
        ...image,
        status: "error" as const,
        error: interruptedMessage,
      };
    });

    if (!changed) {
      return conversation;
    }

    return {
      ...conversation,
      updatedAt: recoveredAt,
      status: "error" as const,
      images,
      error: interruptedMessage,
    };
  });

  const changedItems = nextItems.filter((conversation, index) => conversation !== items[index]);
  if (changedItems.length > 0) {
    await Promise.all(changedItems.map((conversation) => saveImageConversation(conversation)));
  }
  writeActiveGeneratingConversationIds([]);
  return nextItems;
}

export default function ImagePage() {
  const didLoadQuotaRef = useRef(false);
  const conversationsRef = useRef<ImageConversation[]>([]);
  const persistenceQueueRef = useRef(new Map<string, Promise<void>>());
  const pendingPersistenceRef = useRef(new Set<string>());
  const resultsViewportRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [imagePrompt, setImagePrompt] = useState("");
  const [imageCount, setImageCount] = useState("1");
  const [imageMode, setImageMode] = useState<ImageConversationMode>("generate");
  const [imageModel, setImageModel] = useState<ImageModel>("auto");
  const [imageSize, setImageSize] = useState("auto");
  const [imageQuality, setImageQuality] = useState<ImageQuality>("auto");
  const [imageBackground, setImageBackground] = useState<ImageBackground>("auto");
  const [imageOutputFormat, setImageOutputFormat] = useState<ImageOutputFormat>("png");
  const [imageCompression, setImageCompression] = useState("");
  const [referenceImageFiles, setReferenceImageFiles] = useState<File[]>([]);
  const [referenceImages, setReferenceImages] = useState<StoredReferenceImage[]>([]);
  const [conversations, setConversations] = useState<ImageConversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [generatingIds, setGeneratingIds] = useState<Set<string>>(new Set());
  const [availableQuota, setAvailableQuota] = useState("加载中");
  const [viewerRole, setViewerRole] = useState<UserRole | null>(null);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState(0);

  const selectedConversation = useMemo(
    () => conversations.find((item) => item.id === selectedConversationId) ?? null,
    [conversations, selectedConversationId],
  );
  const parsedCount = useMemo(() => Math.max(1, Math.min(10, Number(imageCount) || 1)), [imageCount]);
  const isSelectedGenerating = selectedConversationId !== null && generatingIds.has(selectedConversationId);
  const hasAnyGenerating = generatingIds.size > 0;
  const showConversationOwner = viewerRole === "admin";
  const supportsTransparentBackground = imageModel !== "gpt-image-2";
  const supportsCompression = imageOutputFormat === "jpeg" || imageOutputFormat === "webp";
  const parsedCompression = useMemo(() => {
    if (!supportsCompression || imageCompression.trim() === "") {
      return undefined;
    }
    const value = Number(imageCompression);
    return Number.isFinite(value) ? value : undefined;
  }, [imageCompression, supportsCompression]);
  const imageRequestOptions = useMemo<ImageRequestOptions>(
    () => ({
      size: imageSize.trim() || "auto",
      quality: imageQuality,
      background: imageBackground,
      output_format: imageOutputFormat,
      compression: parsedCompression,
    }),
    [imageBackground, imageOutputFormat, imageQuality, imageSize, parsedCompression],
  );
  const selectConversation = useCallback((conversationId: string | null) => {
    writeActiveConversationId(conversationId);
    setSelectedConversationId(conversationId);
  }, []);

  const addGeneratingId = useCallback((id: string) => {
    setGeneratingIds((prev) => {
      const next = new Set(prev).add(id);
      writeActiveGeneratingConversationIds(next);
      return next;
    });
  }, []);

  const removeGeneratingId = useCallback((id: string) => {
    setGeneratingIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      writeActiveGeneratingConversationIds(next);
      return next;
    });
  }, []);

  const lightboxImages = useMemo(
    () =>
      (selectedConversation?.images ?? [])
        .filter((img): img is StoredImage & { b64_json: string } => img.status === "success" && !!img.b64_json)
        .map((img) => ({ id: img.id, src: buildGeneratedImageDataUrl(img) })),
    [selectedConversation],
  );

  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  const handleImageModelChange = useCallback((value: ImageModel) => {
    setImageModel(value);
    if (value === "gpt-image-2") {
      setImageBackground((prev) => (prev === "transparent" ? "auto" : prev));
    }
  }, []);

  const openLightbox = useCallback(
    (imageId: string) => {
      const idx = lightboxImages.findIndex((img) => img.id === imageId);
      if (idx >= 0) {
        setLightboxIndex(idx);
        setLightboxOpen(true);
      }
    },
    [lightboxImages],
  );

  useEffect(() => {
    let cancelled = false;

    const loadHistory = async () => {
      try {
        const items = await listImageConversations();
        const recoveredItems = await recoverInterruptedConversations(items);
        if (cancelled) {
          return;
        }
        conversationsRef.current = recoveredItems;
        setConversations(recoveredItems);
        const storedConversationId = readActiveConversationId();
        const nextSelectedConversationId =
          (storedConversationId && recoveredItems.some((conversation) => conversation.id === storedConversationId)
            ? storedConversationId
            : null) ?? pickFallbackConversationId(recoveredItems);
        writeActiveConversationId(nextSelectedConversationId);
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
  }, []);

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
        await saveImageConversation(conversation);
      }
    })().finally(() => {
      persistenceQueueRef.current.delete(conversationId);
      pendingPersistenceRef.current.delete(conversationId);
    });

    persistenceQueueRef.current.set(conversationId, task);
    return task;
  }, []);

  const loadQuota = useCallback(async (forceSyncSession = false) => {
    try {
      const session = forceSyncSession ? await syncStoredAuthSession() : await getCachedOrSyncAuthSession();
      if (!session) {
        setAvailableQuota("—");
        return;
      }
      setViewerRole(session.role);
      if (session.role === "admin") {
        const data = await fetchAccounts();
        setAvailableQuota(formatAvailableQuota(data.items));
        return;
      }
      setAvailableQuota(String(Math.max(0, session.image_quota ?? 0)));
    } catch {
      setAvailableQuota((prev) => (prev === "加载中" ? "—" : prev));
    }
  }, []);

  useEffect(() => {
    if (didLoadQuotaRef.current) {
      return;
    }
    didLoadQuotaRef.current = true;

    const syncQuota = async (forceSyncSession = false) => {
      await loadQuota(forceSyncSession);
    };

    const handleFocus = () => {
      void syncQuota(true);
    };

    void syncQuota(true);
    window.addEventListener("focus", handleFocus);
    return () => {
      window.removeEventListener("focus", handleFocus);
    };
  }, [loadQuota]);

  useEffect(() => {
    if (!selectedConversation && !isSelectedGenerating) {
      return;
    }

    resultsViewportRef.current?.scrollTo({
      top: resultsViewportRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [selectedConversation, isSelectedGenerating]);

  const persistConversation = async (conversation: ImageConversation) => {
    const nextConversation = {
      ...conversation,
      updatedAt: conversation.updatedAt || conversation.createdAt,
    };
    const nextConversations = sortImageConversations([
      nextConversation,
      ...conversationsRef.current.filter((item) => item.id !== conversation.id),
    ]);
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    await scheduleConversationPersistence(nextConversation.id);
  };

  const updateConversation = async (
    conversationId: string,
    updater: (current: ImageConversation | null) => ImageConversation,
  ) => {
    const current = conversationsRef.current.find((item) => item.id === conversationId) ?? null;
    const nextConversation = {
      ...updater(current),
      updatedAt: new Date().toISOString(),
    };
    const nextConversations = sortImageConversations([
      nextConversation,
      ...conversationsRef.current.filter((item) => item.id !== conversationId),
    ]);
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    await scheduleConversationPersistence(conversationId);
  };

  const resetComposer = useCallback(() => {
    setImagePrompt("");
    setImageCount("1");
    setReferenceImageFiles([]);
    setReferenceImages([]);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }, []);

  const handleCreateDraft = () => {
    selectConversation(null);
    resetComposer();
    textareaRef.current?.focus();
  };

  const handleDeleteConversation = async (id: string) => {
    const nextConversations = conversations.filter((item) => item.id !== id);
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    const nextSelectedConversationId =
      selectedConversationId === id ? pickFallbackConversationId(nextConversations) : selectedConversationId;
    selectConversation(nextSelectedConversationId);

    try {
      await deleteImageConversation(id);
    } catch (error) {
      const message = error instanceof Error ? error.message : "删除会话失败";
      toast.error(message);
      const items = await listImageConversations();
      conversationsRef.current = items;
      setConversations(items);
    }
  };

  const handleClearHistory = async () => {
    try {
      await clearImageConversations();
      conversationsRef.current = [];
      setConversations([]);
      selectConversation(null);
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
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "读取参考图失败";
      toast.error(message);
    }
  }, []);

  const handleReferenceImageChange = useCallback(async (files: File[]) => {
    if (files.length === 0) {
      setReferenceImageFiles([]);
      setReferenceImages([]);
      return;
    }

    await appendReferenceImages(files);
  }, [appendReferenceImages]);

  const handleReuseGeneratedImage = useCallback(async (
    payload: { conversationId?: string; id?: string; dataUrl: string },
  ) => {
    try {
      if (payload.conversationId) {
        selectConversation(payload.conversationId);
      }
      setImageMode("edit");
      setImagePrompt("");
      const file = dataUrlToFile(payload.dataUrl, `generated-${payload.id || createId()}.png`);
      await appendReferenceImages([file]);
      requestAnimationFrame(() => {
        textareaRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
        textareaRef.current?.focus();
      });
      toast.success("已加入当前参考图，继续输入描述即可编辑");
    } catch (error) {
      const message = error instanceof Error ? error.message : "加入参考图失败";
      toast.error(message);
    }
  }, [appendReferenceImages, selectConversation]);

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

  const handleGenerateImage = async () => {
    const prompt = imagePrompt.trim();
    if (!prompt) {
      toast.error("请输入提示词");
      return;
    }

    if (imageMode === "edit" && referenceImageFiles.length === 0) {
      toast.error("请先上传参考图");
      return;
    }
    if (!supportsTransparentBackground && imageBackground === "transparent") {
      toast.error('gpt-image-2 暂不支持 transparent 背景');
      return;
    }

    const now = new Date().toISOString();
    const conversationId = createId();
    const draftReferenceImages = imageMode === "edit" ? referenceImages : [];

    const draftConversation: ImageConversation = {
      id: conversationId,
      title: buildConversationTitle(prompt),
      prompt,
      model: imageModel,
      mode: imageMode,
      referenceImages: draftReferenceImages,
      count: parsedCount,
      images: Array.from({ length: parsedCount }, (_, index) => ({
        id: `${conversationId}-${index}`,
        status: "loading",
      })),
      createdAt: now,
      updatedAt: now,
      status: "generating",
      ownerRole: viewerRole === "admin" ? "admin" : "user",
      ownerId: viewerRole === "admin" ? "admin" : "self",
      ownerName: viewerRole === "admin" ? "管理员" : "普通用户",
    };

    addGeneratingId(conversationId);
    selectConversation(conversationId);
    resetComposer();

    try {
      await persistConversation(draftConversation);

      const tasks = Array.from({ length: parsedCount }, async (_, index) => {
        try {
          const data =
            imageMode === "edit" && referenceImageFiles.length > 0
              ? await editImage(referenceImageFiles, prompt, imageModel, imageRequestOptions)
              : await generateImage(prompt, imageModel, imageRequestOptions);
          const first = data.data?.[0];
          if (!first?.b64_json) {
            throw new Error(`第 ${index + 1} 张没有返回图片数据`);
          }

          const nextImage: StoredImage = {
            id: `${conversationId}-${index}`,
            status: "success",
            b64_json: first.b64_json,
            mime_type: first.mime_type || "image/png",
          };

          await updateConversation(conversationId, (current) => ({
            ...(current ?? draftConversation),
            images: (current?.images ?? draftConversation.images).map((image) =>
              image.id === nextImage.id ? nextImage : image,
            ),
          }));

          return nextImage;
        } catch (error) {
          const message = error instanceof Error ? error.message : `第 ${index + 1} 张生成失败`;
          const failedImage: StoredImage = {
            id: `${conversationId}-${index}`,
            status: "error",
            error: message,
          };

          await updateConversation(conversationId, (current) => ({
            ...(current ?? draftConversation),
            images: (current?.images ?? draftConversation.images).map((image) =>
              image.id === failedImage.id ? failedImage : image,
            ),
          }));

          throw error;
        }
      });

      const settled = await Promise.allSettled(tasks);
      const successCount = settled.filter((item): item is PromiseFulfilledResult<StoredImage> => item.status === "fulfilled")
        .length;
      const failedCount = settled.length - successCount;

      if (successCount === 0) {
        const firstError = settled.find((item) => item.status === "rejected");
        throw new Error(firstError?.status === "rejected" ? String(firstError.reason) : "生成图片失败");
      }

      await updateConversation(conversationId, (current) => ({
        ...(current ?? draftConversation),
        status: failedCount > 0 ? "error" : "success",
        error: failedCount > 0 ? `其中 ${failedCount} 张生成失败` : undefined,
      }));
      await loadQuota(true);

      if (failedCount > 0) {
        toast.error(`已完成 ${successCount} 张，另有 ${failedCount} 张未生成成功`);
      } else {
        toast.success(imageMode === "edit" ? `已完成 ${successCount} 张图片编辑` : `已生成 ${successCount} 张图片`);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : imageMode === "edit" ? "编辑图片失败" : "生成图片失败";
      await persistConversation({
        ...draftConversation,
        status: "error",
        error: message,
        images: draftConversation.images.map((image) =>
          image.status === "loading"
            ? {
                ...image,
                status: "error",
                error: message,
              }
            : image,
        ),
      });
      toast.error(message);
    } finally {
      removeGeneratingId(conversationId);
    }
  };

  return (
    <>
      <section className="mx-auto grid min-h-[calc(100dvh-5rem)] w-full max-w-[1380px] grid-cols-1 gap-3 px-3 pb-6 lg:h-[calc(100vh-5rem)] lg:min-h-0 lg:grid-cols-[240px_minmax(0,1fr)]">
        <ImageSidebar
          conversations={conversations}
          showConversationOwner={showConversationOwner}
          isLoadingHistory={isLoadingHistory}
          generatingIds={generatingIds}
          selectedConversationId={selectedConversationId}
          onCreateDraft={handleCreateDraft}
          onClearHistory={handleClearHistory}
          onSelectConversation={selectConversation}
          onDeleteConversation={handleDeleteConversation}
          formatConversationTime={formatConversationTime}
        />

        <div className="flex min-h-0 flex-col gap-4">
          <div
            ref={resultsViewportRef}
            className="hide-scrollbar min-h-[36vh] flex-1 overflow-y-auto px-1 py-2 sm:min-h-0 sm:px-4 sm:py-4"
          >
            <ImageResults
              selectedConversation={selectedConversation}
              showConversationOwner={showConversationOwner}
              isSelectedGenerating={isSelectedGenerating}
              openLightbox={openLightbox}
              onReuseAsReference={handleReuseGeneratedImage}
              formatConversationTime={formatConversationTime}
            />
          </div>

          <ImageComposer
            mode={imageMode}
            prompt={imagePrompt}
            model={imageModel}
            size={imageSize}
            quality={imageQuality}
            background={imageBackground}
            outputFormat={imageOutputFormat}
            compression={imageCompression}
            imageCount={imageCount}
            availableQuota={availableQuota}
            hasAnyGenerating={hasAnyGenerating}
            generatingCount={generatingIds.size}
            referenceImages={referenceImages}
            textareaRef={textareaRef}
            fileInputRef={fileInputRef}
            imageModelOptions={imageModelOptions}
            imageSizeSuggestions={imageSizeSuggestions}
            imageQualityOptions={imageQualityOptions}
            imageBackgroundOptions={imageBackgroundOptions}
            imageOutputFormatOptions={imageOutputFormatOptions}
            supportsTransparentBackground={supportsTransparentBackground}
            supportsCompression={supportsCompression}
            onModeChange={setImageMode}
            onPromptChange={setImagePrompt}
            onModelChange={handleImageModelChange}
            onSizeChange={setImageSize}
            onQualityChange={setImageQuality}
            onBackgroundChange={setImageBackground}
            onOutputFormatChange={setImageOutputFormat}
            onCompressionChange={setImageCompression}
            onImageCountChange={setImageCount}
            onSubmit={handleGenerateImage}
            onPickReferenceImage={() => fileInputRef.current?.click()}
            onReferenceImageChange={handleReferenceImageChange}
            onReferenceImageReuse={handleReuseGeneratedImage}
            onRemoveReferenceImage={handleRemoveReferenceImage}
          />
        </div>
      </section>

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
