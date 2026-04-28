"use client";

import { getConversationImages, getConversationMode, getConversationPrompt, getConversationStatus, getModeLabel } from "@/app/image-manager/conversation-utils";
import { ImageLightbox } from "@/components/image-lightbox";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { formatDateTimeInShanghai } from "@/lib/time";
import type { ImageConversation } from "@/store/image-conversations";

type DeleteConfirmState =
  | { type: "one"; conversationId: string; title: string }
  | { type: "batch"; conversationIds: string[]; count: number }
  | { type: "all" }
  | null;

type ImageManagerDetailDialogProps = {
  selectedConversation: ImageConversation | null;
  lightboxImages: Array<{ id: string; src: string }>;
  lightboxIndex: number;
  lightboxOpen: boolean;
  setLightboxImages: (images: Array<{ id: string; src: string }>) => void;
  setLightboxIndex: (index: number) => void;
  setLightboxOpen: (open: boolean) => void;
  onOpenChange: (open: boolean) => void;
};

export function ImageManagerDetailDialog({
  selectedConversation,
  lightboxImages,
  lightboxIndex,
  lightboxOpen,
  setLightboxImages,
  setLightboxIndex,
  setLightboxOpen,
  onOpenChange,
}: ImageManagerDetailDialogProps) {
  return (
    <>
      <Dialog open={selectedConversation !== null} onOpenChange={onOpenChange}>
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
      <ImageLightbox images={lightboxImages} currentIndex={lightboxIndex} open={lightboxOpen} onOpenChange={setLightboxOpen} onIndexChange={setLightboxIndex} />
    </>
  );
}

type ImageManagerDeleteDialogProps = {
  deleteConfirm: DeleteConfirmState;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void | Promise<void>;
};

export function ImageManagerDeleteDialog({
  deleteConfirm,
  onOpenChange,
  onConfirm,
}: ImageManagerDeleteDialogProps) {
  return (
    <Dialog open={deleteConfirm !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md rounded-3xl border-white/80 bg-white p-6 shadow-2xl">
        <DialogHeader className="space-y-2"><DialogTitle>{deleteConfirm?.type === "all" ? "确认清空全部历史" : deleteConfirm?.type === "batch" ? "确认批量删除" : "确认删除会话"}</DialogTitle></DialogHeader>
        <p className="text-sm text-stone-500">{deleteConfirm?.type === "all" ? "此操作会清空当前服务端图片历史，且无法撤销。" : deleteConfirm?.type === "batch" ? `将删除当前已选的 ${deleteConfirm.count} 条会话，且无法撤销。` : `将删除「${deleteConfirm?.title || ""}」及其所有历史图片。`}</p>
        <DialogFooter className="gap-2 sm:justify-end"><Button variant="outline" className="rounded-xl border-stone-200 bg-white" onClick={() => onOpenChange(false)}>取消</Button><Button variant="destructive" className="rounded-xl" onClick={() => void onConfirm()}>确认</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
