"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { LoaderCircle, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { getConversationImageCount, getConversationImages, getConversationMode, getConversationPrompt, getConversationStatus, getModeLabel, getStatusBadgeVariant } from "@/app/image-manager/conversation-utils";
import { FilterToolbar } from "@/app/image-manager/filter-toolbar";
import { useImageManagerFilters } from "@/app/image-manager/use-image-manager-filters";
import { ImageLightbox } from "@/components/image-lightbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { syncStoredAuthSession } from "@/lib/auth-session";
import { type AuthSession } from "@/lib/auth-types";
import { formatDateTimeInShanghai, formatMonthDayTimeInShanghai } from "@/lib/time";
import {
  clearImageConversations,
  deleteImageConversation,
  listImageConversations,
  type ImageConversation,
  type ImageConversationMode,
} from "@/store/image-conversations";

type DeleteConfirmState = { type: "one"; conversationId: string; title: string } | { type: "all" } | null;

export default function ImageManagerPage() {
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [items, setItems] = useState<ImageConversation[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<ImageConversation | null>(null);
  const [lightboxImages, setLightboxImages] = useState<Array<{ id: string; src: string }>>([]);
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<DeleteConfirmState>(null);
  const [isLoading, setIsLoading] = useState(true);

  const loadItems = useCallback(async (silent = false) => {
    if (!silent) setIsLoading(true);
    try {
      const nextItems = await listImageConversations();
      setItems(nextItems);
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
        const nextSession = await syncStoredAuthSession();
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
      } catch {
        if (!cancelled) router.replace("/login");
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

  const handleDelete = useCallback(async () => {
    if (!deleteConfirm) return;
    try {
      if (deleteConfirm.type === "all") {
        await clearImageConversations();
        setItems([]);
        setSelectedConversation(null);
        toast.success("已清空图片历史");
      } else {
        await deleteImageConversation(deleteConfirm.conversationId);
        setItems((current) => current.filter((item) => item.id !== deleteConfirm.conversationId));
        if (selectedConversation?.id === deleteConfirm.conversationId) {
          setSelectedConversation(null);
        }
        toast.success("已删除会话");
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除失败");
    } finally {
      setDeleteConfirm(null);
    }
  }, [deleteConfirm, selectedConversation?.id]);

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

  const historyDisabled = session.image_history_persistence_mode !== "server";

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
            <Button variant="destructive" className="rounded-xl px-4" onClick={() => setDeleteConfirm({ type: "all" })} disabled={historyDisabled || items.length === 0}><Trash2 className="size-4" />清空全部</Button>
          </div>

          <div className="overflow-hidden rounded-2xl border border-stone-200">
            <div className="overflow-x-auto">
              <table className="min-w-full table-fixed border-collapse">
                <thead className="bg-stone-50 text-left text-xs uppercase tracking-[0.12em] text-stone-500"><tr><th className="px-4 py-3 font-medium">会话</th><th className="px-4 py-3 font-medium">归属</th><th className="px-4 py-3 font-medium">状态</th><th className="px-4 py-3 font-medium">更新时间</th><th className="px-4 py-3 font-medium text-right">操作</th></tr></thead>
                <tbody className="divide-y divide-stone-100 bg-white text-sm">
                  {filteredItems.map((conversation) => {
                    const status = getConversationStatus(conversation);
                    const mode = getConversationMode(conversation);
                    const images = getConversationImages(conversation);
                    return (
                      <tr key={conversation.id} className="align-top text-stone-700">
                        <td className="px-4 py-3"><div className="space-y-1"><div className="font-medium text-stone-900">{conversation.title}</div><div className="line-clamp-2 text-xs text-stone-500">{getConversationPrompt(conversation) || "—"}</div><div className="flex flex-wrap gap-2"><Badge variant="secondary">{getModeLabel(mode)}</Badge><Badge variant="outline">{conversation.turns.length} 轮</Badge><Badge variant="outline">{images.length} 张</Badge><Badge variant="outline">{conversation.turns[conversation.turns.length - 1]?.model || "未知模型"}</Badge></div></div></td>
                        <td className="px-4 py-3"><div className="space-y-1"><div className="font-medium text-stone-800">{conversation.ownerName}</div><div className="text-xs text-stone-500">{conversation.ownerRole === "admin" ? "管理员" : conversation.ownerId}</div></div></td>
                        <td className="px-4 py-3"><Badge variant={getStatusBadgeVariant(status)}>{status === "success" ? "成功" : status === "error" ? "失败" : status === "generating" ? "生成中" : "排队中"}</Badge></td>
                        <td className="px-4 py-3 text-xs text-stone-500">{formatMonthDayTimeInShanghai(conversation.updatedAt) || "—"}</td>
                        <td className="px-4 py-3"><div className="flex justify-end gap-2"><Button variant="outline" className="rounded-lg border-stone-200 bg-white px-3 text-stone-700" onClick={() => setSelectedConversation(conversation)}>查看</Button><Button variant="ghost" className="rounded-lg px-3 text-rose-600 hover:bg-rose-50 hover:text-rose-700" onClick={() => setDeleteConfirm({ type: "one", conversationId: conversation.id, title: conversation.title })}><Trash2 className="size-4" />删除</Button></div></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {!historyDisabled && filteredItems.length === 0 ? <div className="px-6 py-14 text-center text-sm text-stone-500">没有匹配的图片会话</div> : null}
          </div>
        </CardContent>
      </Card>

      <Dialog open={selectedConversation !== null} onOpenChange={(open) => !open && setSelectedConversation(null)}>
        <DialogContent className="max-w-5xl rounded-3xl border-white/80 bg-white p-0 shadow-2xl">
          {selectedConversation ? (
            <div className="space-y-5 p-6">
              <DialogHeader className="space-y-2"><DialogTitle className="text-xl font-semibold text-stone-950">{selectedConversation.title}</DialogTitle></DialogHeader>
              <div className="grid gap-3 md:grid-cols-4">
                <Card className="rounded-2xl border-stone-200 shadow-none"><CardContent className="space-y-1 p-4"><div className="text-xs text-stone-400">归属</div><div className="text-sm font-medium text-stone-900">{selectedConversation.ownerName}</div><div className="text-xs text-stone-500">{selectedConversation.ownerRole === "admin" ? "管理员" : selectedConversation.ownerId}</div></CardContent></Card>
                <Card className="rounded-2xl border-stone-200 shadow-none"><CardContent className="space-y-1 p-4"><div className="text-xs text-stone-400">最后状态</div><div className="text-sm font-medium text-stone-900">{getConversationStatus(selectedConversation)}</div><div className="text-xs text-stone-500">{getModeLabel(getConversationMode(selectedConversation))}</div></CardContent></Card>
                <Card className="rounded-2xl border-stone-200 shadow-none"><CardContent className="space-y-1 p-4"><div className="text-xs text-stone-400">创建时间</div><div className="text-sm font-medium text-stone-900">{formatDateTimeInShanghai(selectedConversation.createdAt) || "—"}</div></CardContent></Card>
                <Card className="rounded-2xl border-stone-200 shadow-none"><CardContent className="space-y-1 p-4"><div className="text-xs text-stone-400">更新时间</div><div className="text-sm font-medium text-stone-900">{formatDateTimeInShanghai(selectedConversation.updatedAt) || "—"}</div></CardContent></Card>
              </div>
              <div className="rounded-2xl border border-stone-200 bg-stone-50/70 p-4 text-sm text-stone-700">{getConversationPrompt(selectedConversation) || "—"}</div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {getConversationImages(selectedConversation).map((image, index) => (
                  <button key={image.id} type="button" className="overflow-hidden rounded-2xl border border-stone-200 bg-stone-100 text-left transition hover:border-stone-300 hover:shadow-sm" onClick={() => { const images = getConversationImages(selectedConversation); setLightboxImages(images); setLightboxIndex(index); setLightboxOpen(true); }}>
                    <img src={image.src} alt={selectedConversation.title} className="aspect-square w-full object-cover" />
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog open={deleteConfirm !== null} onOpenChange={(open) => !open && setDeleteConfirm(null)}>
        <DialogContent className="max-w-md rounded-3xl border-white/80 bg-white p-6 shadow-2xl">
          <DialogHeader className="space-y-2"><DialogTitle>{deleteConfirm?.type === "all" ? "确认清空全部历史" : "确认删除会话"}</DialogTitle></DialogHeader>
          <p className="text-sm text-stone-500">{deleteConfirm?.type === "all" ? "此操作会清空当前服务端图片历史，且无法撤销。" : `将删除「${deleteConfirm?.title || ""}」及其所有历史图片。`}</p>
          <DialogFooter className="gap-2 sm:justify-end"><Button variant="outline" className="rounded-xl border-stone-200 bg-white" onClick={() => setDeleteConfirm(null)}>取消</Button><Button variant="destructive" className="rounded-xl" onClick={() => void handleDelete()}>确认</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <ImageLightbox images={lightboxImages} currentIndex={lightboxIndex} open={lightboxOpen} onOpenChange={setLightboxOpen} onIndexChange={setLightboxIndex} />
    </div>
  );
}
