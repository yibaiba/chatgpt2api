"use client";

import { ChevronLeft, ChevronRight, ExternalLink, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  IMAGE_PROMPT_GALLERY_CATEGORIES,
  IMAGE_PROMPT_GALLERY_ITEMS,
  IMAGE_PROMPT_GALLERY_SOURCE_URL,
  loadImagePromptGalleryItems,
  normalizeImagePromptGalleryPrompt,
  type ImagePromptGalleryItem,
  type ImagePromptGalleryCategory,
  type ImagePromptGalleryFilter,
} from "@/lib/image-prompt-gallery";
import { cn } from "@/lib/utils";

type ImagePromptGalleryProps = {
  selectedPrompt: string;
  onSelectPrompt: (prompt: string) => void;
};

const GALLERY_PAGE_SIZE = 9;

export function ImagePromptGallery({ selectedPrompt, onSelectPrompt }: ImagePromptGalleryProps) {
  const [open, setOpen] = useState(false);
  const [activeCategory, setActiveCategory] = useState<ImagePromptGalleryFilter>("all");
  const [currentPage, setCurrentPage] = useState(1);
  const [galleryItems, setGalleryItems] = useState<ImagePromptGalleryItem[]>(() => [...IMAGE_PROMPT_GALLERY_ITEMS]);
  const normalizedSelectedPrompt = normalizeImagePromptGalleryPrompt(selectedPrompt);

  useEffect(() => {
    let cancelled = false;
    void loadImagePromptGalleryItems().then((items) => {
      if (!cancelled) {
        setGalleryItems(items);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const visibleItems = useMemo(() => {
    if (activeCategory === "all") {
      return galleryItems;
    }
    return galleryItems.filter((item) => item.category === activeCategory);
  }, [activeCategory, galleryItems]);
  const totalPages = Math.max(1, Math.ceil(visibleItems.length / GALLERY_PAGE_SIZE));
  const activePage = Math.min(currentPage, totalPages);
  const pagedItems = useMemo(() => {
    const start = (activePage - 1) * GALLERY_PAGE_SIZE;
    return visibleItems.slice(start, start + GALLERY_PAGE_SIZE);
  }, [activePage, visibleItems]);

  const selectedItem = useMemo(
    () => galleryItems.find((item) => normalizeImagePromptGalleryPrompt(item.prompt) === normalizedSelectedPrompt),
    [galleryItems, normalizedSelectedPrompt],
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          className="h-10 rounded-full border-stone-200 bg-white px-4 text-sm font-medium text-stone-700 shadow-none hover:bg-stone-50"
          onClick={() => setOpen(true)}
        >
          <Sparkles className="size-4 text-orange-500" />
          提示词灵感
          <span className="rounded-full bg-orange-100 px-2 py-0.5 text-[11px] font-semibold text-orange-600">
            {galleryItems.length}
          </span>
        </Button>
        <div className="min-w-0 text-xs text-stone-500">
          {selectedItem ? (
            <span className="block truncate">已选灵感：{selectedItem.title}</span>
          ) : (
            <span className="block truncate">精选案例一键填入，不占输入区空间</span>
          )}
        </div>
      </div>

      <DialogContent className="flex max-h-[88vh] w-[min(96vw,1120px)] flex-col gap-0 overflow-hidden rounded-[32px] border border-stone-200 p-0">
        <DialogHeader className="gap-3 border-b border-stone-200/80 px-5 py-5 sm:px-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="space-y-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <DialogTitle className="text-xl tracking-tight text-stone-950">提示词灵感画廊</DialogTitle>
                <span className="inline-flex h-6 items-center rounded-full bg-orange-100 px-2.5 text-[11px] font-semibold text-orange-600">
                  精选
                </span>
              </div>
              <DialogDescription className="text-sm leading-6 text-stone-500">
                精选自 awesome-gpt-image-2-prompts，并自动补充 upstream JSON 最新案例。
              </DialogDescription>
            </div>

            <a
              href={IMAGE_PROMPT_GALLERY_SOURCE_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs font-medium text-stone-500 transition hover:text-stone-800"
            >
              查看来源
              <ExternalLink className="size-3.5" />
            </a>
          </div>

          <div className="flex flex-wrap gap-2">
            {IMAGE_PROMPT_GALLERY_CATEGORIES.map((category) => (
              <button
                key={category.value}
                type="button"
                onClick={() => {
                  setActiveCategory(category.value);
                  setCurrentPage(1);
                }}
                className={cn(
                  "inline-flex h-9 items-center rounded-full border px-4 text-sm font-medium transition",
                  activeCategory === category.value
                    ? "border-stone-950 bg-stone-950 text-white"
                    : "border-stone-200 bg-white text-stone-600 hover:border-stone-300 hover:text-stone-900",
                )}
                aria-pressed={activeCategory === category.value}
              >
                {category.label}
              </button>
            ))}
          </div>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
            {pagedItems.map((item) => {
              const isSelected = normalizedSelectedPrompt === normalizeImagePromptGalleryPrompt(item.prompt);
              const categoryMeta = getCategoryMeta(item.category);

              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    onSelectPrompt(item.prompt);
                    setOpen(false);
                  }}
                  className={cn(
                    "group overflow-hidden rounded-[28px] border bg-white text-left transition",
                    isSelected
                      ? "border-blue-500 shadow-[0_18px_50px_-30px_rgba(37,99,235,0.55)]"
                      : "border-stone-200 hover:-translate-y-0.5 hover:border-stone-300 hover:shadow-[0_20px_60px_-32px_rgba(28,25,23,0.22)]",
                  )}
                  >
                    <div className="relative aspect-[16/10] overflow-hidden bg-stone-100">
                      <GalleryPreviewImage title={item.title} imageUrl={item.previewImageUrl} />
                      <div className="absolute left-3 top-3 rounded-md bg-black/60 px-2 py-1 text-[11px] font-semibold tracking-[0.08em] text-white">
                        {categoryMeta.badge}
                      </div>
                  </div>

                  <div className="space-y-3 p-4">
                    <div className="space-y-1.5">
                      <div className="text-lg font-semibold tracking-tight text-stone-950">{item.title}</div>
                      <p className="line-clamp-2 text-sm leading-6 text-stone-500">{item.summary}</p>
                    </div>

                    <p className="line-clamp-3 text-[13px] leading-6 text-stone-600">{item.prompt}</p>

                    <div className="flex items-center justify-between gap-3 text-xs">
                      <span className="truncate text-stone-400">
                        {item.sourceTitle} · {item.creator}
                      </span>
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 font-medium",
                          isSelected ? "text-blue-600" : "text-stone-700",
                        )}
                      >
                        <Sparkles className="size-3.5" />
                        {isSelected ? "已填入" : "一键填入"}
                      </span>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-stone-200/80 px-5 py-4 sm:px-6">
          <div className="text-xs text-stone-500">
            当前显示 {pagedItems.length} / {visibleItems.length} 条灵感
          </div>
          {totalPages > 1 ? (
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                className="h-9 rounded-full border-stone-200 bg-white px-3 text-stone-600 shadow-none"
                onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                disabled={activePage <= 1}
              >
                <ChevronLeft className="size-4" />
                上一页
              </Button>
              <div className="min-w-[88px] text-center text-sm font-medium text-stone-700">
                {activePage} / {totalPages}
              </div>
              <Button
                type="button"
                variant="outline"
                className="h-9 rounded-full border-stone-200 bg-white px-3 text-stone-600 shadow-none"
                onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                disabled={activePage >= totalPages}
              >
                下一页
                <ChevronRight className="size-4" />
              </Button>
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function getCategoryMeta(category: ImagePromptGalleryCategory) {
  return IMAGE_PROMPT_GALLERY_CATEGORIES.find((item) => item.value === category) ?? IMAGE_PROMPT_GALLERY_CATEGORIES[0];
}

function GalleryPreviewImage({ title, imageUrl }: { title: string; imageUrl: string }) {
  const [failed, setFailed] = useState(!imageUrl);

  useEffect(() => {
    setFailed(!imageUrl);
  }, [imageUrl]);

  if (failed) {
    return (
      <div className="flex h-full w-full items-end bg-[radial-gradient(circle_at_top,_rgba(251,146,60,0.35),_rgba(12,10,9,0.92))] p-4 text-white">
        <div className="space-y-1">
          <div className="text-[11px] font-semibold tracking-[0.14em] text-orange-200/90 uppercase">Prompt</div>
          <div className="line-clamp-2 text-base font-semibold tracking-tight">{title}</div>
        </div>
      </div>
    );
  }

  return (
    <img
      src={imageUrl}
      alt={title}
      className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.02]"
      loading="lazy"
      draggable={false}
      onError={() => setFailed(true)}
    />
  );
}
