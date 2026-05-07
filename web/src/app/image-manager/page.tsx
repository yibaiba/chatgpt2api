"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, LoaderCircle, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { getConversationImageCount, getConversationImages, type ConversationImageAsset } from "@/app/image-manager/conversation-utils";
import { ImageManagerDeleteDialog, ImageManagerDetailDialog } from "@/app/image-manager/dialogs";
import { FilterToolbar } from "@/app/image-manager/filter-toolbar";
import { ImageManagerTable } from "@/app/image-manager/table";
import { useImageManagerFilters } from "@/app/image-manager/use-image-manager-filters";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { syncStoredAuthSessionWithFallback } from "@/lib/auth-session";
import { type AuthSession } from "@/lib/auth-types";
import { clearImageConversations, deleteImageConversation, listImageConversations, type ImageConversation, type ImageConversationMode } from "@/store/image-conversations";

type DeleteConfirmState = { type: "one"; conversationId: string; title: string } | { type: "batch"; conversationIds: string[]; count: number } | { type: "all" } | null;

function dataUrlToBlob(dataUrl: string): Blob {
  const [header, content] = dataUrl.split(",", 2);
  const mimeType = header.match(/^data:(.*?);base64$/)?.[1] || "image/png";
  const binary = atob(content || "");
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return new Blob([bytes], { type: mimeType });
}

function downloadBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

function dedupeFileName(fileName: string, usedNames: Set<string>) {
  if (!usedNames.has(fileName)) {
    usedNames.add(fileName);
    return fileName;
  }
  const dotIndex = fileName.lastIndexOf(".");
  const hasExtension = dotIndex > 0;
  const stem = hasExtension ? fileName.slice(0, dotIndex) : fileName;
  const extension = hasExtension ? fileName.slice(dotIndex) : "";
  let suffix = 2;
  while (true) {
    const candidate = `${stem}-${suffix}${extension}`;
    if (!usedNames.has(candidate)) {
      usedNames.add(candidate);
      return candidate;
    }
    suffix += 1;
  }
}

export default function ImageManagerPage() {
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [items, setItems] = useState<ImageConversation[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<ImageConversation | null>(null);
  const [lightboxImages, setLightboxImages] = useState<Array<{ id: string; src: string }>>([]);
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<DeleteConfirmState>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [isLoading, setIsLoading] = useState(true);

  const loadItems = useCallback(async (silent = false) => {
    if (!silent) setIsLoading(true);
    try {
      const nextItems = await listImageConversations();
      setItems(nextItems);
      const validIds = new Set(nextItems.map((item) => item.id));
      setSelectedIds((current) => new Set(Array.from(current).filter((id) => validIds.has(id))));
    } catch (error) {
      if (!silent) {
        toast.error(error instanceof Error ? error.message : "加载图片历史失败");
      }
    } finally {
      if (!silent) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const init = async () => {
      try {
        const nextSession = await syncStoredAuthSessionWithFallback();
        if (cancelled) return;
        if (nextSession.role !== "admin") {
          toast.error("只有管理员可以访问图片管理");
          router.replace("/image");
          return;
        }
        setSession(nextSession);
        if (nextSession.image_history_persistence_mode === "server") {
          await loadItems();
        } else {
          setIsLoading(false);
        }
      } catch (error) {
        if (cancelled) return;
        setIsLoading(false);
        toast.error(error instanceof Error ? error.message : "校验登录状态失败，请稍后重试");
      }
    };
    void init();
    return () => {
      cancelled = true;
    };
  }, [loadItems, router]);

  const {
    filteredItems,
    ownerOptions,
    modelOptions,
    queryInput,
    statusFilter,
    modeFilter,
    ownerFilter,
    modelFilter,
    imageCountFilter,
    datePreset,
    startDate,
    endDate,
    dateRangeError,
    dateRangeLabel,
    setQueryInput,
    setAppliedQuery,
    setStatusFilter,
    setModeFilter,
    setOwnerFilter,
    setModelFilter,
    setImageCountFilter,
    setStartDate,
    setEndDate,
    setDatePreset,
    applyDatePreset,
    resetFilters,
  } = useImageManagerFilters(items);

  const summary = useMemo(() => {
    const successfulImages = items.reduce((sum, conversation) => sum + getConversationImageCount(conversation), 0);
    const userConversations = items.filter((conversation) => conversation.ownerRole === "user").length;
    return { total: items.length, successfulImages, userConversations };
  }, [items]);
  const selectedFilteredCount = useMemo(() => filteredItems.reduce((sum, conversation) => sum + (selectedIds.has(conversation.id) ? 1 : 0), 0), [filteredItems, selectedIds]);
  const allFilteredSelected = filteredItems.length > 0 && selectedFilteredCount === filteredItems.length;
  const someFilteredSelected = selectedFilteredCount > 0 && !allFilteredSelected;

  const handleDelete = useCallback(async () => {
    if (!deleteConfirm) return;
    try {
      if (deleteConfirm.type === "all") {
        await clearImageConversations();
        setItems([]);
        setSelectedIds(new Set());
        setSelectedConversation(null);
        toast.success("已清空图片历史");
      } else if (deleteConfirm.type === "batch") {
        await Promise.all(deleteConfirm.conversationIds.map((conversationId) => deleteImageConversation(conversationId)));
        const deletedIds = new Set(deleteConfirm.conversationIds);
        setItems((current) => current.filter((item) => !deletedIds.has(item.id)));
        setSelectedIds((current) => new Set(Array.from(current).filter((id) => !deletedIds.has(id))));
        setSelectedConversation((current) => (current && deletedIds.has(current.id) ? null : current));
        toast.success(`已删除 ${deleteConfirm.count} 条会话`);
      } else {
        await deleteImageConversation(deleteConfirm.conversationId);
        setItems((current) => current.filter((item) => item.id !== deleteConfirm.conversationId));
        setSelectedIds((current) => {
          const next = new Set(current);
          next.delete(deleteConfirm.conversationId);
          return next;
        });
        setSelectedConversation((current) => (current?.id === deleteConfirm.conversationId ? null : current));
        toast.success("已删除会话");
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除失败");
    } finally {
      setDeleteConfirm(null);
    }
  }, [deleteConfirm]);

  const toggleSelection = useCallback((conversationId: string, checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(conversationId);
      } else {
        next.delete(conversationId);
      }
      return next;
    });
  }, []);
  const toggleAllFiltered = useCallback((checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      for (const conversation of filteredItems) {
        if (checked) {
          next.add(conversation.id);
        } else {
          next.delete(conversation.id);
        }
      }
      return next;
    });
  }, [filteredItems]);
  const historyDisabled = session?.image_history_persistence_mode !== "server";

  const handleDownloadImage = useCallback((image: ConversationImageAsset) => {
    downloadBlob(dataUrlToBlob(image.src), image.fileName);
  }, []);

  const handleDownloadSelectedZip = useCallback(async () => {
    const selectedConversations = filteredItems.filter((item) => selectedIds.has(item.id));
    const selectedImages = selectedConversations.flatMap((conversation) => getConversationImages(conversation));
    if (selectedImages.length === 0) {
      toast.error("已选会话里没有可下载的成功图片");
      return;
    }
    try {
      const JSZip = (await import("jszip")).default;
      const zip = new JSZip();
      const usedNames = new Set<string>();
      for (const image of selectedImages) {
        zip.file(dedupeFileName(image.fileName, usedNames), dataUrlToBlob(image.src));
      }
      const blob = await zip.generateAsync({ type: "blob" });
      downloadBlob(blob, `image-manager-${Date.now()}.zip`);
      toast.success(`已打包 ${selectedImages.length} 张图片`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "打包 ZIP 失败");
    }
  }, [filteredItems, selectedIds]);

  if (isLoading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  if (!session || session.role !== "admin") {
    return null;
  }

  return (
    <div className="space-y-5">
      <section className="space-y-1">
        <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">Images</div>
        <h1 className="text-2xl font-semibold tracking-tight text-stone-950">图片管理</h1>
        <p className="text-sm text-stone-500">基于现有服务端图片历史做只读/删除管理，普通用户仍然只能走画图入口，不能访问此页面。</p>
      </section>

      {historyDisabled ? (
        <Card className="rounded-2xl border-amber-200 bg-amber-50/80 shadow-sm">
          <CardContent className="flex flex-col gap-3 p-5 text-sm text-amber-900 md:flex-row md:items-center md:justify-between">
            <div>当前图片历史模式是浏览器本地保存，后台图片管理页只会展示服务端历史。请先在设置里切到“服务端统一保存”。</div>
            <Button asChild className="rounded-xl bg-stone-950 text-white hover:bg-stone-800">
              <Link href="/settings">前往设置</Link>
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <section className="grid gap-4 md:grid-cols-3">
        <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm"><CardContent className="space-y-1 p-5"><div className="text-xs text-stone-400">总会话数</div><div className="text-2xl font-semibold text-stone-900">{summary.total}</div></CardContent></Card>
        <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm"><CardContent className="space-y-1 p-5"><div className="text-xs text-stone-400">成功图片</div><div className="text-2xl font-semibold text-emerald-600">{summary.successfulImages}</div></CardContent></Card>
        <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm"><CardContent className="space-y-1 p-5"><div className="text-xs text-stone-400">普通用户会话</div><div className="text-2xl font-semibold text-violet-600">{summary.userConversations}</div></CardContent></Card>
      </section>

      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="space-y-4 p-5">
          <FilterToolbar
            queryInput={queryInput}
            statusFilter={statusFilter}
            modeFilter={modeFilter}
            ownerFilter={ownerFilter}
            modelFilter={modelFilter}
            imageCountFilter={imageCountFilter}
            datePreset={datePreset}
            startDate={startDate}
            endDate={endDate}
            dateRangeError={dateRangeError}
            ownerOptions={ownerOptions}
            modelOptions={modelOptions}
            historyDisabled={historyDisabled}
            isLoading={isLoading}
            onQueryInputChange={setQueryInput}
            onStatusFilterChange={setStatusFilter}
            onModeFilterChange={setModeFilter}
            onOwnerFilterChange={setOwnerFilter}
            onModelFilterChange={setModelFilter}
            onImageCountFilterChange={setImageCountFilter}
            onDatePresetChange={applyDatePreset}
            onStartDateChange={(value) => {
              setDatePreset("custom");
              setStartDate(value);
            }}
            onEndDateChange={(value) => {
              setDatePreset("custom");
              setEndDate(value);
            }}
            onReset={resetFilters}
            onRefresh={() => loadItems()}
            onApplyQuery={() => setAppliedQuery(queryInput)}
          />

          <div className="flex items-center justify-between text-sm text-stone-500">
            <span>当前结果：{filteredItems.length} 条 · 时间范围：{dateRangeLabel} · 服务端历史模式：{session.image_history_persistence_mode === "server" ? "已启用" : "未启用"}</span>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button variant="outline" className="rounded-xl border-stone-200 bg-white px-4 text-stone-700" onClick={() => toggleAllFiltered(!allFilteredSelected)} disabled={historyDisabled || filteredItems.length === 0}>{allFilteredSelected ? "取消全选当前结果" : "全选当前结果"}</Button>
              <Button variant="outline" className="rounded-xl border-stone-200 bg-white px-4 text-stone-700" onClick={() => void handleDownloadSelectedZip()} disabled={historyDisabled || selectedFilteredCount === 0}><Download className="size-4" />下载已选 ZIP</Button>
              <Button variant="destructive" className="rounded-xl px-4" onClick={() => setDeleteConfirm({ type: "batch", conversationIds: filteredItems.filter((item) => selectedIds.has(item.id)).map((item) => item.id), count: selectedFilteredCount })} disabled={historyDisabled || selectedFilteredCount === 0}><Trash2 className="size-4" />删除已选 ({selectedFilteredCount})</Button>
              <Button variant="destructive" className="rounded-xl px-4" onClick={() => setDeleteConfirm({ type: "all" })} disabled={historyDisabled || items.length === 0}><Trash2 className="size-4" />清空全部</Button>
            </div>
          </div>

          <ImageManagerTable
            items={filteredItems}
            historyDisabled={historyDisabled}
            allFilteredSelected={allFilteredSelected}
            someFilteredSelected={someFilteredSelected}
            selectedIds={selectedIds}
            onToggleAllFiltered={toggleAllFiltered}
            onToggleItem={toggleSelection}
            onOpenConversation={setSelectedConversation}
            onRequestDeleteConversation={({ conversationId, title }) =>
              setDeleteConfirm({ type: "one", conversationId, title })
            }
          />
        </CardContent>
      </Card>

      <ImageManagerDetailDialog
        selectedConversation={selectedConversation}
        lightboxImages={lightboxImages}
        lightboxIndex={lightboxIndex}
        lightboxOpen={lightboxOpen}
        setLightboxImages={setLightboxImages}
        setLightboxIndex={setLightboxIndex}
        setLightboxOpen={setLightboxOpen}
        onDownloadImage={handleDownloadImage}
        onOpenChange={(open) => !open && setSelectedConversation(null)}
      />
      <ImageManagerDeleteDialog
        deleteConfirm={deleteConfirm}
        onOpenChange={(open) => !open && setDeleteConfirm(null)}
        onConfirm={handleDelete}
      />
    </div>
  );
}
