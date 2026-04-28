"use client";

import { useCallback, useMemo, useState } from "react";

import { getConversationImageCount, getConversationMode, getConversationModel, getConversationPrompt, getConversationStatus } from "@/app/image-manager/conversation-utils";
import { buildPresetDateRange, describeDateRange, formatShanghaiDateKey, isDateRangeInvalid, matchesDateRange, type ConversationDatePreset } from "@/app/image-manager/date-range";
import type { ConversationStatusFilter } from "@/app/image-manager/filter-toolbar";
import type { ImageConversation, ImageConversationMode } from "@/store/image-conversations";

export type ImageCountFilter = "all" | "1" | "2" | "4" | "8";

type FilterOption = {
  value: string;
  label: string;
};

function buildOwnerOptions(items: ImageConversation[]): FilterOption[] {
  const seen = new Map<string, string>();
  for (const conversation of items) {
    if (seen.has(conversation.ownerId)) {
      continue;
    }
    seen.set(
      conversation.ownerId,
      conversation.ownerRole === "admin" ? "管理员" : `${conversation.ownerName} (${conversation.ownerId})`,
    );
  }
  return Array.from(seen.entries())
    .map(([value, label]) => ({ value, label }))
    .sort((left, right) => left.label.localeCompare(right.label, "zh-CN"));
}

function buildModelOptions(items: ImageConversation[]): FilterOption[] {
  return Array.from(new Set(items.map((conversation) => getConversationModel(conversation)).filter(Boolean)))
    .map((value) => ({ value, label: value }))
    .sort((left, right) => left.label.localeCompare(right.label, "en"));
}

export function useImageManagerFilters(items: ImageConversation[]) {
  const [queryInput, setQueryInput] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<ConversationStatusFilter>("all");
  const [modeFilter, setModeFilter] = useState<"all" | ImageConversationMode>("all");
  const [ownerFilter, setOwnerFilter] = useState("all");
  const [modelFilter, setModelFilter] = useState("all");
  const [imageCountFilter, setImageCountFilter] = useState<ImageCountFilter>("all");
  const [datePreset, setDatePreset] = useState<ConversationDatePreset>("all");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const ownerOptions = useMemo(() => buildOwnerOptions(items), [items]);
  const modelOptions = useMemo(() => buildModelOptions(items), [items]);
  const dateRangeError = useMemo(
    () => (isDateRangeInvalid(startDate, endDate) ? "开始日期不能晚于结束日期" : ""),
    [endDate, startDate],
  );
  const dateRangeLabel = useMemo(
    () => describeDateRange(datePreset, startDate, endDate),
    [datePreset, endDate, startDate],
  );
  const filteredItems = useMemo(() => {
    const query = appliedQuery.trim().toLowerCase();
    const minimumImageCount = imageCountFilter === "all" ? 0 : Number(imageCountFilter);
    return items.filter((conversation) => {
      const statusMatched = statusFilter === "all" || getConversationStatus(conversation) === statusFilter;
      const modeMatched = modeFilter === "all" || getConversationMode(conversation) === modeFilter;
      const ownerMatched = ownerFilter === "all" || conversation.ownerId === ownerFilter;
      const modelMatched = modelFilter === "all" || getConversationModel(conversation) === modelFilter;
      const imageCountMatched = getConversationImageCount(conversation) >= minimumImageCount;
      const dateMatched = matchesDateRange(formatShanghaiDateKey(conversation.updatedAt), startDate, endDate);
      if (!statusMatched || !modeMatched || !ownerMatched || !modelMatched || !imageCountMatched || !dateMatched) {
        return false;
      }
      if (!query) {
        return true;
      }
      const haystack = [conversation.title, conversation.ownerName, conversation.ownerId, getConversationPrompt(conversation), getConversationModel(conversation)]
        .join("\n")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [appliedQuery, endDate, imageCountFilter, items, modeFilter, modelFilter, ownerFilter, startDate, statusFilter]);

  const applyDatePreset = useCallback((value: Exclude<ConversationDatePreset, "custom">) => {
    setDatePreset(value);
    const range = buildPresetDateRange(value);
    setStartDate(range.start);
    setEndDate(range.end);
  }, []);

  const resetFilters = useCallback(() => {
    setQueryInput("");
    setAppliedQuery("");
    setStatusFilter("all");
    setModeFilter("all");
    setOwnerFilter("all");
    setModelFilter("all");
    setImageCountFilter("all");
    setDatePreset("all");
    setStartDate("");
    setEndDate("");
  }, []);

  return {
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
  };
}
