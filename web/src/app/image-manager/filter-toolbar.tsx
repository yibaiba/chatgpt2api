"use client";

import { CalendarRange, LoaderCircle, RefreshCw, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { ImageConversationMode, ImageTurnStatus } from "@/store/image-conversations";

import { DATE_PRESET_OPTIONS, type ConversationDatePreset } from "./date-range";
import type { ImageCountFilter } from "./use-image-manager-filters";

export type ConversationStatusFilter = "all" | ImageTurnStatus;

type FilterToolbarProps = {
  queryInput: string;
  statusFilter: ConversationStatusFilter;
  modeFilter: "all" | ImageConversationMode;
  ownerFilter: string;
  modelFilter: string;
  imageCountFilter: ImageCountFilter;
  datePreset: ConversationDatePreset;
  startDate: string;
  endDate: string;
  dateRangeError: string;
  ownerOptions: Array<{ value: string; label: string }>;
  modelOptions: Array<{ value: string; label: string }>;
  historyDisabled: boolean;
  isLoading: boolean;
  onQueryInputChange: (value: string) => void;
  onStatusFilterChange: (value: ConversationStatusFilter) => void;
  onModeFilterChange: (value: "all" | ImageConversationMode) => void;
  onOwnerFilterChange: (value: string) => void;
  onModelFilterChange: (value: string) => void;
  onImageCountFilterChange: (value: ImageCountFilter) => void;
  onDatePresetChange: (value: Exclude<ConversationDatePreset, "custom">) => void;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  onReset: () => void;
  onRefresh: () => void | Promise<void>;
  onApplyQuery: () => void;
};

export function FilterToolbar({
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
  ownerOptions,
  modelOptions,
  historyDisabled,
  isLoading,
  onQueryInputChange,
  onStatusFilterChange,
  onModeFilterChange,
  onOwnerFilterChange,
  onModelFilterChange,
  onImageCountFilterChange,
  onDatePresetChange,
  onStartDateChange,
  onEndDateChange,
  onReset,
  onRefresh,
  onApplyQuery,
}: FilterToolbarProps) {
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex h-11 items-center gap-2 rounded-xl border border-stone-200 bg-stone-50 px-3 text-sm font-medium text-stone-700">
            <CalendarRange className="size-4" />
            时间范围
          </div>
          {DATE_PRESET_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              disabled={historyDisabled}
              aria-pressed={datePreset === option.value}
              onClick={() => onDatePresetChange(option.value)}
              className={cn(
                "inline-flex h-11 items-center rounded-xl border px-3 text-sm font-medium transition",
                datePreset === option.value
                  ? "border-stone-950 bg-stone-950 text-white"
                  : "border-stone-200 bg-white text-stone-700 hover:border-stone-300 hover:bg-stone-50",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:min-w-[360px]">
          <Input
            type="date"
            value={startDate}
            max={endDate || undefined}
            disabled={historyDisabled}
            aria-label="开始日期"
            className="h-11 rounded-xl border-stone-200 bg-white"
            onChange={(event) => onStartDateChange(event.target.value)}
          />
          <Input
            type="date"
            value={endDate}
            min={startDate || undefined}
            disabled={historyDisabled}
            aria-label="结束日期"
            className="h-11 rounded-xl border-stone-200 bg-white"
            onChange={(event) => onEndDateChange(event.target.value)}
          />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[170px_170px_220px_180px_170px_minmax(0,1fr)_auto_auto_auto]">
        <Select value={statusFilter} onValueChange={(value) => onStatusFilterChange(value as ConversationStatusFilter)}>
          <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
            <SelectValue placeholder="状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            <SelectItem value="success">成功</SelectItem>
            <SelectItem value="generating">生成中</SelectItem>
            <SelectItem value="queued">排队中</SelectItem>
            <SelectItem value="error">失败</SelectItem>
          </SelectContent>
        </Select>
        <Select value={modeFilter} onValueChange={(value) => onModeFilterChange(value as "all" | ImageConversationMode)}>
          <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
            <SelectValue placeholder="模式" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部模式</SelectItem>
            <SelectItem value="generate">生成</SelectItem>
            <SelectItem value="edit">编辑</SelectItem>
          </SelectContent>
        </Select>
        <Select value={ownerFilter} onValueChange={onOwnerFilterChange}>
          <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
            <SelectValue placeholder="归属" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部归属</SelectItem>
            {ownerOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={modelFilter} onValueChange={onModelFilterChange}>
          <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
            <SelectValue placeholder="模型" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部模型</SelectItem>
            {modelOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={imageCountFilter} onValueChange={(value) => onImageCountFilterChange(value as ImageCountFilter)}>
          <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
            <SelectValue placeholder="图片数量" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部图片数量</SelectItem>
            <SelectItem value="1">至少 1 张</SelectItem>
            <SelectItem value="2">至少 2 张</SelectItem>
            <SelectItem value="4">至少 4 张</SelectItem>
            <SelectItem value="8">至少 8 张</SelectItem>
          </SelectContent>
        </Select>
        <Input
          value={queryInput}
          disabled={historyDisabled}
          onChange={(event) => onQueryInputChange(event.target.value)}
          placeholder="搜索标题、提示词、用户或模型"
          className="h-11 rounded-xl border-stone-200 bg-white"
        />
        <Button
          variant="outline"
          disabled={historyDisabled}
          className="h-11 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
          onClick={onReset}
        >
          清空
        </Button>
        <Button
          variant="outline"
          disabled={historyDisabled}
          className="h-11 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
          onClick={() => void onRefresh()}
        >
          <RefreshCw className="size-4" />
          刷新
        </Button>
        <Button
          disabled={historyDisabled}
          className="h-11 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800"
          onClick={onApplyQuery}
        >
          {isLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Search className="size-4" />}
          查询
        </Button>
      </div>

      {dateRangeError ? <p role="alert" className="text-sm text-rose-600">{dateRangeError}</p> : null}
    </div>
  );
}
