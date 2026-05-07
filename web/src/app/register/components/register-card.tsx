"use client";

import { AlertTriangle, LoaderCircle, Play, RotateCcw, Save, Square, Trash2, UserPlus } from "lucide-react";

import type { RegisterConfig, RegisterMailProvider, RegisterMode } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
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

type RegisterCardProps = {
  config: RegisterConfig | null;
  isLoading: boolean;
  isSaving: boolean;
  actionLabel: string | null;
  isDirty: boolean;
  onChange: (value: RegisterConfig | null) => void;
  onSave: () => void;
  onToggle: () => void;
  onReset: () => void;
};

const PROVIDER_OPTIONS = [
  "cloudflare_temp_email",
  "tempmail_lol",
  "moemail",
  "inbucket",
  "duckmail",
  "gptmail",
  "yyds_mail",
] as const;

type RegisterProviderType = (typeof PROVIDER_OPTIONS)[number];

function buildProvider(type: RegisterProviderType = "tempmail_lol", seed?: Partial<RegisterMailProvider>): RegisterMailProvider {
  return {
    id: seed?.id || Math.random().toString(36).slice(2, 10),
    type,
    enabled: seed?.enabled ?? true,
    api_key: type === "tempmail_lol" || type === "moemail" || type === "duckmail" || type === "gptmail" || type === "yyds_mail" ? seed?.api_key || "" : "",
    api_base: type === "cloudflare_temp_email" || type === "moemail" || type === "inbucket" || type === "yyds_mail" ? seed?.api_base || (type === "yyds_mail" ? "https://maliapi.215.im/v1" : "") : "",
    admin_password: type === "cloudflare_temp_email" ? seed?.admin_password || "" : undefined,
    default_domain: type === "duckmail" ? seed?.default_domain || "duckmail.sbs" : type === "gptmail" ? seed?.default_domain || "" : undefined,
    expiry_time: seed?.expiry_time,
    random_subdomain: type === "inbucket" ? seed?.random_subdomain ?? true : undefined,
    subdomain: type === "yyds_mail" ? seed?.subdomain || "" : undefined,
    wildcard: type === "yyds_mail" ? seed?.wildcard ?? false : undefined,
    domains: seed?.domains || [],
  };
}

function updateConfig(
  config: RegisterConfig | null,
  onChange: (value: RegisterConfig) => void,
  updater: (current: RegisterConfig) => RegisterConfig,
) {
  if (!config) {
    return;
  }
  onChange(updater(config));
}

export function RegisterCard({
  config,
  isLoading,
  isSaving,
  actionLabel,
  isDirty,
  onChange,
  onSave,
  onToggle,
  onReset,
}: RegisterCardProps) {
  if (isLoading && !config) {
    return (
      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="flex items-center justify-center p-10">
          <LoaderCircle className="size-5 animate-spin text-stone-400" />
        </CardContent>
      </Card>
    );
  }

  if (!config) {
    return null;
  }

  const stats = config.stats;
  const providers = config.mail.providers;
  const isActing = Boolean(actionLabel);
  const modeSummary =
    config.mode === "total"
      ? "总数模式：启动后一次性补到设定数量，跑完就停止。"
      : config.mode === "quota"
        ? `额度模式：后台常驻，每隔 ${config.check_interval} 秒检查一次；达到目标额度后暂停，跌破后自动继续补号。`
        : `可用账号模式：后台常驻，每隔 ${config.check_interval} 秒检查一次；达到目标可用数后暂停，跌破后自动继续补号。`;
  const updateProvider = (index: number, updates: Partial<RegisterMailProvider>) =>
    updateConfig(config, onChange, (current) => ({
      ...current,
      mail: {
        ...current.mail,
        providers: current.mail.providers.map((item, itemIndex) => (itemIndex === index ? { ...item, ...updates } : item)),
      },
    }));
  const switchProviderType = (index: number, type: RegisterProviderType) =>
    updateConfig(config, onChange, (current) => ({
      ...current,
      mail: {
        ...current.mail,
        providers: current.mail.providers.map((item, itemIndex) =>
          itemIndex === index ? buildProvider(type, { id: item.id, enabled: item.enabled }) : item,
        ),
      },
    }));

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(360px,0.95fr)]">
      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="space-y-6 p-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="space-y-1">
                <div className="flex items-center gap-2 text-stone-900">
                  <UserPlus className="size-4" />
                  <h2 className="text-lg font-semibold tracking-tight">注册配置</h2>
                </div>
                <p className="text-sm text-stone-500">当前已支持 `cloudflare_temp_email`、`tempmail_lol`、`moemail`、`inbucket`、`duckmail`、`gptmail` 与 `yyds_mail`；成功后会自动把 access token 导入现有号池并刷新状态。</p>
              </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                onClick={onReset}
                disabled={isSaving || isActing || config.enabled}
              >
                <RotateCcw className="size-4" />
                重置
              </Button>
              <Button
                className="h-10 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800"
                onClick={onSave}
                disabled={isSaving || isActing || config.enabled || !isDirty}
              >
                {isSaving ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
                保存
              </Button>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">注册模式</label>
              <Select
                value={config.mode}
                onValueChange={(value) =>
                  updateConfig(config, onChange, (current) => ({
                    ...current,
                    mode: value as RegisterMode,
                  }))
                }
                disabled={config.enabled}
              >
                <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="total">注册总数</SelectItem>
                  <SelectItem value="quota">目标额度</SelectItem>
                  <SelectItem value="available">目标可用账号</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs leading-5 text-stone-500">{modeSummary}</p>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">注册总数</label>
              <Input
                value={String(config.total)}
                onChange={(event) =>
                  updateConfig(config, onChange, (current) => ({
                    ...current,
                    total: Number(event.target.value || 0),
                  }))
                }
                className="h-11 rounded-xl border-stone-200 bg-white"
                disabled={config.enabled || config.mode !== "total"}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">线程数</label>
              <Input
                value={String(config.threads)}
                onChange={(event) =>
                  updateConfig(config, onChange, (current) => ({
                    ...current,
                    threads: Number(event.target.value || 0),
                  }))
                }
                className="h-11 rounded-xl border-stone-200 bg-white"
                disabled={config.enabled}
              />
            </div>

            <div className="space-y-2 md:col-span-2">
              <label className="text-sm font-medium text-stone-700">注册代理</label>
              <Input
                value={config.proxy}
                onChange={(event) =>
                  updateConfig(config, onChange, (current) => ({
                    ...current,
                    proxy: event.target.value,
                  }))
                }
                placeholder="http://127.0.0.1:7890"
                className="h-11 rounded-xl border-stone-200 bg-white"
                disabled={config.enabled}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">检查间隔（秒）</label>
              <Input
                value={String(config.check_interval)}
                onChange={(event) =>
                  updateConfig(config, onChange, (current) => ({
                    ...current,
                    check_interval: Number(event.target.value || 0),
                  }))
                }
                className="h-11 rounded-xl border-stone-200 bg-white"
                disabled={config.enabled || config.mode === "total"}
              />
              <p className="text-xs text-stone-500">
                仅 `目标额度` / `目标可用账号` 模式生效；刷新页面不会停止后台 runner，后端会按这个间隔继续巡检。
              </p>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">目标额度</label>
              <Input
                value={String(config.target_quota)}
                onChange={(event) =>
                  updateConfig(config, onChange, (current) => ({
                    ...current,
                    target_quota: Number(event.target.value || 0),
                  }))
                }
                className="h-11 rounded-xl border-stone-200 bg-white"
                disabled={config.enabled || config.mode !== "quota"}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">目标可用账号</label>
              <Input
                value={String(config.target_available)}
                onChange={(event) =>
                  updateConfig(config, onChange, (current) => ({
                    ...current,
                    target_available: Number(event.target.value || 0),
                  }))
                }
                className="h-11 rounded-xl border-stone-200 bg-white"
                disabled={config.enabled || config.mode !== "available"}
              />
            </div>
          </div>

          <div className="space-y-4 border-t border-stone-200 pt-4">
              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-stone-800">邮箱 provider 配置</h3>
                <p className="text-xs text-stone-500">按 provider 类型展示对应字段；先保存配置，再启动 runner，可以避免带着半成品字段直接跑任务。</p>
              </div>

            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">请求超时</label>
                <Input
                  value={String(config.mail.request_timeout)}
                  onChange={(event) =>
                    updateConfig(config, onChange, (current) => ({
                      ...current,
                      mail: {
                        ...current.mail,
                        request_timeout: Number(event.target.value || 0),
                      },
                    }))
                  }
                  className="h-11 rounded-xl border-stone-200 bg-white"
                  disabled={config.enabled}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">等待超时</label>
                <Input
                  value={String(config.mail.wait_timeout)}
                  onChange={(event) =>
                    updateConfig(config, onChange, (current) => ({
                      ...current,
                      mail: {
                        ...current.mail,
                        wait_timeout: Number(event.target.value || 0),
                      },
                    }))
                  }
                  className="h-11 rounded-xl border-stone-200 bg-white"
                  disabled={config.enabled}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">轮询间隔</label>
                <Input
                  value={String(config.mail.wait_interval)}
                  onChange={(event) =>
                    updateConfig(config, onChange, (current) => ({
                      ...current,
                      mail: {
                        ...current.mail,
                        wait_interval: Number(event.target.value || 0),
                      },
                    }))
                  }
                  className="h-11 rounded-xl border-stone-200 bg-white"
                  disabled={config.enabled}
                />
              </div>
            </div>

            <div className="space-y-4">
              {providers.map((provider, index) => {
                const providerType = PROVIDER_OPTIONS.includes(provider.type as RegisterProviderType)
                  ? (provider.type as RegisterProviderType)
                  : "tempmail_lol";
                return (
                  <div key={provider.id || index} className="space-y-3 rounded-2xl border border-stone-200 bg-stone-50/70 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <label className="flex items-center gap-3 text-sm text-stone-700">
                        <Checkbox
                          checked={Boolean(provider.enabled)}
                          onCheckedChange={(checked) => updateProvider(index, { enabled: Boolean(checked) })}
                          disabled={config.enabled}
                        />
                        启用 provider
                      </label>
                      <button
                        type="button"
                        className="rounded-lg p-2 text-stone-400 transition hover:bg-rose-50 hover:text-rose-500 disabled:opacity-50"
                        onClick={() =>
                          updateConfig(config, onChange, (current) => ({
                            ...current,
                            mail: {
                              ...current.mail,
                              providers: current.mail.providers.filter((_, itemIndex) => itemIndex !== index),
                            },
                          }))
                        }
                        disabled={config.enabled}
                        title="删除 provider"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </div>

                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="space-y-2">
                        <label className="text-sm font-medium text-stone-700">类型</label>
                        <Select value={providerType} onValueChange={(value) => switchProviderType(index, value as RegisterProviderType)} disabled={config.enabled}>
                          <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {PROVIDER_OPTIONS.map((option) => (
                              <SelectItem key={option} value={option}>
                                {option}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>

                      {(providerType === "cloudflare_temp_email" || providerType === "moemail" || providerType === "inbucket" || providerType === "yyds_mail") && (
                        <div className="space-y-2">
                          <label className="text-sm font-medium text-stone-700">API Base</label>
                          <Input
                            value={provider.api_base || ""}
                            onChange={(event) => updateProvider(index, { api_base: event.target.value })}
                            className="h-11 rounded-xl border-stone-200 bg-white"
                            disabled={config.enabled}
                          />
                        </div>
                      )}

                      {providerType === "cloudflare_temp_email" && (
                        <div className="space-y-2">
                          <label className="text-sm font-medium text-stone-700">Admin Password</label>
                          <Input
                            value={provider.admin_password || ""}
                            onChange={(event) => updateProvider(index, { admin_password: event.target.value })}
                            className="h-11 rounded-xl border-stone-200 bg-white"
                            disabled={config.enabled}
                          />
                        </div>
                      )}

                      {providerType === "inbucket" && (
                        <label className="flex items-center gap-3 pt-8 text-sm text-stone-700">
                          <Checkbox
                            checked={Boolean(provider.random_subdomain ?? true)}
                            onCheckedChange={(checked) => updateProvider(index, { random_subdomain: Boolean(checked) })}
                            disabled={config.enabled}
                          />
                          启用随机子域名
                        </label>
                      )}

                      {(providerType === "tempmail_lol" || providerType === "moemail" || providerType === "duckmail" || providerType === "gptmail" || providerType === "yyds_mail") && (
                        <div className="space-y-2">
                          <label className="text-sm font-medium text-stone-700">API Key</label>
                          <Input
                            value={provider.api_key || ""}
                            onChange={(event) => updateProvider(index, { api_key: event.target.value })}
                            className="h-11 rounded-xl border-stone-200 bg-white"
                            disabled={config.enabled}
                          />
                        </div>
                      )}

                      {(providerType === "duckmail" || providerType === "gptmail") && (
                        <div className="space-y-2">
                          <label className="text-sm font-medium text-stone-700">默认域名</label>
                          <Input
                            value={provider.default_domain || ""}
                            onChange={(event) => updateProvider(index, { default_domain: event.target.value })}
                            placeholder={providerType === "duckmail" ? "duckmail.sbs" : ""}
                            className="h-11 rounded-xl border-stone-200 bg-white"
                            disabled={config.enabled}
                          />
                        </div>
                      )}

                      {providerType === "yyds_mail" && (
                        <>
                          <div className="space-y-2">
                            <label className="text-sm font-medium text-stone-700">Subdomain</label>
                            <Input
                              value={provider.subdomain || ""}
                              onChange={(event) => updateProvider(index, { subdomain: event.target.value })}
                              className="h-11 rounded-xl border-stone-200 bg-white"
                              disabled={config.enabled}
                            />
                          </div>
                          <label className="flex items-center gap-3 pt-8 text-sm text-stone-700">
                            <Checkbox
                              checked={Boolean(provider.wildcard)}
                              onCheckedChange={(checked) => updateProvider(index, { wildcard: Boolean(checked) })}
                              disabled={config.enabled}
                            />
                            Wildcard
                          </label>
                        </>
                      )}

                      {(providerType === "tempmail_lol" || providerType === "cloudflare_temp_email" || providerType === "moemail" || providerType === "inbucket" || providerType === "yyds_mail") && (
                        <div className="space-y-2 md:col-span-2">
                          <label className="text-sm font-medium text-stone-700">{providerType === "inbucket" ? "基础域名列表" : "Domains"}</label>
                          <Textarea
                            value={(provider.domains || []).join("\n")}
                            onChange={(event) =>
                              updateProvider(index, {
                                domains: event.target.value
                                  .split(/[\n,]/)
                                  .map((entry) => entry.trim())
                                  .filter(Boolean),
                              })
                            }
                            placeholder={providerType === "inbucket" ? "每行一个基础域名，系统会自动生成随机子域名" : providerType === "moemail" ? "每行一个域名" : "每行一个域名，留空则使用服务默认域名"}
                            className="min-h-24 rounded-xl border-stone-200 bg-white font-mono text-xs"
                            disabled={config.enabled}
                          />
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}

              <Button
                type="button"
                variant="outline"
                className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                onClick={() =>
                  updateConfig(config, onChange, (current) => ({
                    ...current,
                    mail: {
                      ...current.mail,
                        providers: [...current.mail.providers, buildProvider()],
                      },
                    }))
                }
                disabled={config.enabled}
              >
                <UserPlus className="size-4" />
                添加 provider
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="space-y-5 p-6">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <h2 className="text-lg font-semibold tracking-tight">运行状态</h2>
              <p className="text-sm text-stone-500">运行成功后会把 access token 直接写入现有号池，并刷新 quota / status。</p>
            </div>
            <Badge variant={config.enabled ? "success" : "secondary"} className="rounded-md">
              {config.enabled ? "运行中" : "已停止"}
            </Badge>
          </div>

          <div className="grid grid-cols-2 gap-3">
            {[
              ["成功", String(stats.success)],
              ["失败", String(stats.fail)],
              ["完成", String(stats.done)],
              ["线程", String(stats.threads)],
              ["当前额度", String(stats.current_quota || 0)],
              ["正常账号", String(stats.current_available || 0)],
              ["运行时间", `${stats.elapsed_seconds || 0}s`],
              ["成功率", `${stats.success_rate || 0}%`],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl border border-stone-200 bg-stone-50/70 px-3 py-2">
                <div className="text-xs text-stone-400">{label}</div>
                <div className="mt-1 text-base font-semibold text-stone-800">{value}</div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-3 gap-2">
            <Button
              className="h-10 rounded-xl bg-stone-950 px-3 text-white hover:bg-stone-800"
              onClick={onToggle}
              disabled={isSaving || isActing}
            >
              {actionLabel === "starting" || actionLabel === "stopping" ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : config.enabled ? (
                <Square className="size-4" />
              ) : (
                <Play className="size-4" />
              )}
              {config.enabled ? "停止" : "启动"}
            </Button>
            <Button
              variant="outline"
              className="h-10 rounded-xl border-stone-200 bg-white px-3 text-stone-700"
              onClick={onReset}
              disabled={isSaving || isActing || config.enabled}
            >
              {actionLabel === "resetting" ? <LoaderCircle className="size-4 animate-spin" /> : <RotateCcw className="size-4" />}
              重置
            </Button>
            <Button
              variant="outline"
              className="h-10 rounded-xl border-stone-200 bg-white px-3 text-stone-700"
              onClick={onSave}
              disabled={isSaving || isActing || config.enabled || !isDirty}
            >
              {isSaving ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
              保存
            </Button>
          </div>

          <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            <AlertTriangle className="size-4 shrink-0" />
            若 provider 的必填字段缺失，启动时会直接返回错误；保存前请确认类型与对应字段已经填完整。
          </div>

          <div className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-xs leading-5 text-sky-900">
            当前 runner 运行在后端：`目标额度` / `目标可用账号` 模式会常驻巡检，达标后暂停，跌破后自动恢复；
            `注册总数` 模式仍然是一次性任务。
          </div>

          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-stone-800">最近日志</h3>
            <div className="max-h-[360px] overflow-y-auto rounded-2xl border border-stone-200 bg-stone-950 p-3 font-mono text-xs text-stone-200">
              {config.logs && config.logs.length > 0 ? (
                <div className="space-y-2">
                  {config.logs.map((entry, index) => (
                    <div key={`${entry.time}-${index}`} className="space-y-0.5">
                      <div className="text-[11px] text-stone-500">{entry.time}</div>
                      <div>{entry.text}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-stone-500">暂无日志</div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
