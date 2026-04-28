"use client";

import { Trash2 } from "lucide-react";

import { getConversationImages, getConversationMode, getConversationPrompt, getConversationStatus, getModeLabel, getStatusBadgeVariant } from "@/app/image-manager/conversation-utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { formatMonthDayTimeInShanghai } from "@/lib/time";
import type { ImageConversation } from "@/store/image-conversations";

type ImageManagerTableProps = {
  items: ImageConversation[];
  historyDisabled: boolean;
  allFilteredSelected: boolean;
  someFilteredSelected: boolean;
  selectedIds: Set<string>;
  onToggleAllFiltered: (checked: boolean) => void;
  onToggleItem: (conversationId: string, checked: boolean) => void;
  onOpenConversation: (conversation: ImageConversation) => void;
  onRequestDeleteConversation: (payload: { conversationId: string; title: string }) => void;
};

export function ImageManagerTable({
  items,
  historyDisabled,
  allFilteredSelected,
  someFilteredSelected,
  selectedIds,
  onToggleAllFiltered,
  onToggleItem,
  onOpenConversation,
  onRequestDeleteConversation,
}: ImageManagerTableProps) {
  return (
    <div className="overflow-hidden rounded-2xl border border-stone-200">
      <div className="overflow-x-auto">
        <table className="min-w-full table-fixed border-collapse">
          <thead className="bg-stone-50 text-left text-xs uppercase tracking-[0.12em] text-stone-500">
            <tr>
              <th className="w-12 px-4 py-3 font-medium">
                <Checkbox
                  checked={allFilteredSelected ? true : someFilteredSelected ? "indeterminate" : false}
                  aria-label="全选当前筛选结果"
                  disabled={historyDisabled || items.length === 0}
                  onCheckedChange={(checked) => onToggleAllFiltered(Boolean(checked))}
                />
              </th>
              <th className="px-4 py-3 font-medium">会话</th>
              <th className="px-4 py-3 font-medium">归属</th>
              <th className="px-4 py-3 font-medium">状态</th>
              <th className="px-4 py-3 font-medium">更新时间</th>
              <th className="px-4 py-3 font-medium text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100 bg-white text-sm">
            {items.map((conversation) => {
              const status = getConversationStatus(conversation);
              const mode = getConversationMode(conversation);
              const images = getConversationImages(conversation);
              return (
                <tr key={conversation.id} className="align-top text-stone-700">
                  <td className="px-4 py-3">
                    <Checkbox
                      checked={selectedIds.has(conversation.id)}
                      aria-label={`选择会话 ${conversation.title}`}
                      disabled={historyDisabled}
                      onCheckedChange={(checked) => onToggleItem(conversation.id, Boolean(checked))}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="space-y-1">
                      <div className="font-medium text-stone-900">{conversation.title}</div>
                      <div className="line-clamp-2 text-xs text-stone-500">{getConversationPrompt(conversation) || "—"}</div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant="secondary">{getModeLabel(mode)}</Badge>
                        <Badge variant="outline">{conversation.turns.length} 轮</Badge>
                        <Badge variant="outline">{images.length} 张</Badge>
                        <Badge variant="outline">{conversation.turns[conversation.turns.length - 1]?.model || "未知模型"}</Badge>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="space-y-1">
                      <div className="font-medium text-stone-800">{conversation.ownerName}</div>
                      <div className="text-xs text-stone-500">{conversation.ownerRole === "admin" ? "管理员" : conversation.ownerId}</div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={getStatusBadgeVariant(status)}>
                      {status === "success" ? "成功" : status === "error" ? "失败" : status === "generating" ? "生成中" : "排队中"}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-xs text-stone-500">{formatMonthDayTimeInShanghai(conversation.updatedAt) || "—"}</td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <Button variant="outline" className="rounded-lg border-stone-200 bg-white px-3 text-stone-700" onClick={() => onOpenConversation(conversation)}>查看</Button>
                      <Button
                        variant="ghost"
                        className="rounded-lg px-3 text-rose-600 hover:bg-rose-50 hover:text-rose-700"
                        onClick={() => onRequestDeleteConversation({ conversationId: conversation.id, title: conversation.title })}
                      >
                        <Trash2 className="size-4" />
                        删除
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!historyDisabled && items.length === 0 ? <div className="px-6 py-14 text-center text-sm text-stone-500">没有匹配的图片会话</div> : null}
    </div>
  );
}
