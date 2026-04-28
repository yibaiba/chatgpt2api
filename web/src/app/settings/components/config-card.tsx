"use client";

import { History, KeyRound, Link2, LoaderCircle, Save, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import { useSettingsStore } from "../store";

export function ConfigCard() {
  const config = useSettingsStore((state) => state.config);
  const isLoadingConfig = useSettingsStore((state) => state.isLoadingConfig);
  const isSavingConfig = useSettingsStore((state) => state.isSavingConfig);
  const setAuthKey = useSettingsStore((state) => state.setAuthKey);
  const setRefreshAccountIntervalMinute = useSettingsStore((state) => state.setRefreshAccountIntervalMinute);
  const setRemoteAccountSyncIntervalMinute = useSettingsStore((state) => state.setRemoteAccountSyncIntervalMinute);
  const setRefreshAccountBatchSize = useSettingsStore((state) => state.setRefreshAccountBatchSize);
  const setAutoRemoveRateLimitedAccounts = useSettingsStore((state) => state.setAutoRemoveRateLimitedAccounts);
  const setSensitiveWordFilterEnabled = useSettingsStore((state) => state.setSensitiveWordFilterEnabled);
  const setSensitiveWordsText = useSettingsStore((state) => state.setSensitiveWordsText);
  const setBaseUrl = useSettingsStore((state) => state.setBaseUrl);
  const setImageHistoryPersistenceMode = useSettingsStore((state) => state.setImageHistoryPersistenceMode);
  const saveConfig = useSettingsStore((state) => state.saveConfig);

  if (isLoadingConfig) {
    return (
      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="flex items-center justify-center p-10">
          <LoaderCircle className="size-5 animate-spin text-stone-400" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-6 p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold tracking-tight">系统配置</h2>
            <p className="text-sm text-stone-500">修改后请务必点击保存按钮，否则配置不会生效。</p>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <label className="flex items-center gap-1.5 text-sm font-medium text-stone-700">
              <KeyRound className="size-3.5" />
              登录密钥
            </label>
            <Input
              value={String(config?.["auth-key"] || "")}
              onChange={(event) => setAuthKey(event.target.value)}
              placeholder={config?.auth_key_configured ? "留空表示保持不变" : "auth-key"}
              className="h-11 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">
              用于管理员登录验证。服务端不会再回显当前密钥，留空表示保持现有配置。
            </p>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium text-stone-700">账号刷新间隔（分钟）</label>
            <Input
              type="number"
              min="1"
              inputMode="numeric"
              value={String(config?.refresh_account_interval_minute || "")}
              onChange={(event) => setRefreshAccountIntervalMinute(event.target.value)}
              placeholder="5"
              className="h-11 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">控制账号自动刷新频率，保存时会自动归一到最小 1 分钟。</p>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium text-stone-700">账号刷新并发批大小</label>
            <Input
              type="number"
              min="1"
              max="10"
              step="1"
              inputMode="numeric"
              value={String(config?.refresh_account_batch_size || "")}
              onChange={(event) => setRefreshAccountBatchSize(event.target.value)}
              placeholder="3"
              className="h-11 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">控制每一批同时刷新的 token 数量，保存时会自动限制在 1 到 10。</p>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium text-stone-700">远端账号自动同步间隔（分钟）</label>
            <Input
              type="number"
              min="1"
              inputMode="numeric"
              value={String(config?.remote_account_sync_interval_minute || "")}
              onChange={(event) => setRemoteAccountSyncIntervalMinute(event.target.value)}
              placeholder="60"
              className="h-11 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">
              控制 CPA / Sub2API 自动同步频率；只有在连接详情里额外开启了「自动同步」的来源，才会按这个间隔全量拉取。
            </p>
          </div>

          <div className="space-y-2 md:col-span-2">
            <label className="text-sm font-medium text-stone-700">账号自动清理</label>
            <label className="flex items-start gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3 text-sm text-stone-700">
              <Checkbox
                checked={Boolean(config?.auto_remove_rate_limited_accounts)}
                onCheckedChange={(checked) => setAutoRemoveRateLimitedAccounts(Boolean(checked))}
                className="mt-0.5"
              />
              <span className="space-y-1">
                <span className="block font-medium text-stone-800">自动移除限流账号</span>
                <span className="block text-xs text-stone-500">
                  当账号因图片额度耗尽被标记为“限流”时，自动从当前号池移除，避免后续反复轮询到不可用账号。
                </span>
              </span>
            </label>
          </div>

          <div className="space-y-3 md:col-span-2">
            <label className="flex items-center gap-1.5 text-sm font-medium text-stone-700">
              <ShieldAlert className="size-3.5" />
              敏感词拦截
            </label>
            <label className="flex items-start gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3 text-sm text-stone-700">
              <Checkbox
                checked={Boolean(config?.sensitive_word_filter_enabled)}
                onCheckedChange={(checked) => setSensitiveWordFilterEnabled(Boolean(checked))}
                className="mt-0.5"
              />
              <span className="space-y-1">
                <span className="block font-medium text-stone-800">启用 prompt 敏感词过滤</span>
                <span className="block text-xs text-stone-500">
                  命中后会在调用上游前直接返回 400，同时覆盖图片直连、image jobs、chat、responses 与 messages。
                </span>
              </span>
            </label>
            <Textarea
              value={Array.isArray(config?.sensitive_words) ? config.sensitive_words.join("\n") : ""}
              onChange={(event) => setSensitiveWordsText(event.target.value)}
              placeholder={"每行一个敏感词\n例如：nsfw"}
              disabled={!config?.sensitive_word_filter_enabled}
              className="min-h-28 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">
              按子串匹配，忽略大小写；建议只填写明确需要拦截的关键词，避免误伤正常 prompt。
            </p>
          </div>

          <div className="space-y-2 md:col-span-2">
            <label className="flex items-center gap-1.5 text-sm font-medium text-stone-700">
              <History className="size-3.5" />
              图片历史存储方式
            </label>
            <Select
              value={config?.image_history_persistence_mode === "server" ? "server" : "browser"}
              onValueChange={(value) => {
                setImageHistoryPersistenceMode(value === "server" ? "server" : "browser");
              }}
            >
              <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                <SelectValue placeholder="选择图片历史存储方式" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="browser">仅浏览器历史</SelectItem>
                <SelectItem value="server">从服务器读取并保存历史</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-stone-500">
              浏览器模式只在当前设备保存图片历史，不会请求服务端历史接口。
            </p>
          </div>

          <div className="space-y-2 md:col-span-2">
            <label className="flex items-center gap-1.5 text-sm font-medium text-stone-700">
              <Link2 className="size-3.5" />
              图片访问地址
            </label>
            <Input
              type="url"
              value={String(config?.base_url || "")}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="https://example.com"
              className="h-11 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">用于生成 `response_format=url` 时的图片访问前缀。</p>
          </div>
        </div>

        <div className="flex justify-end">
          <Button
            className="h-10 w-full rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800 sm:w-auto"
            onClick={() => void saveConfig()}
            disabled={isSavingConfig}
          >
            {isSavingConfig ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
            保存
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
