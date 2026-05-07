import { httpRequest } from "@/lib/request";
import type {
  AuthSession,
  AuthUser,
  ImageHistoryPersistenceMode,
} from "@/lib/auth-types";

export type {
  AuthSession,
  AuthUser,
  ImageHistoryPersistenceMode,
} from "@/lib/auth-types";

export type AccountType = "Free" | "Plus" | "ProLite" | "Pro" | "Team";
export type AccountStatus = "正常" | "限流" | "异常" | "禁用";
export type ImageModel = "auto" | "gpt-image-1" | "gpt-image-2" | "codex-gpt-image-2" | "gpt-image-think";
export type ImageGenerationRoute = "regular" | "thinking" | "fallback";
export type GeneratedImageResponseItem = {
  b64_json?: string;
  url?: string;
  revised_prompt?: string;
  mime_type?: string;
  generation_route?: ImageGenerationRoute;
};
export type GeneratedImageResponse = { created: number; data: GeneratedImageResponseItem[] };
export type ImageJobStatus = "queued" | "running" | "success" | "error";
export type ImageJobRequestOptions = {
  size?: string;
  quality?: "auto" | "low" | "medium" | "high";
  background?: "auto" | "opaque";
  output_format?: "png" | "jpeg" | "webp";
  compression?: number;
};
export type ImageJob<T> = {
  id: string;
  status: ImageJobStatus;
  result?: T;
  error?: string;
};
type ImageJobResponse<T> = {
  job: ImageJob<T>;
};
export type LegacyProxySettings = {
  proxy_url: string;
  enabled: boolean;
  scheme: string | null;
};
export type ProxyPoolEntry = {
  id: string;
  name: string;
  proxy_url: string;
  scheme: "socks5" | "socks5h";
  last_checked_at: string | null;
  last_check_ok: boolean | null;
  last_check_status: number | null;
  last_check_error: string | null;
  created_at: string;
  updated_at: string;
};
export type ProxyPoolSettings = {
  items: ProxyPoolEntry[];
  enabled: boolean;
  selection_strategy: "round_robin";
  validate_on_save: boolean;
};

export type Account = {
  id: string;
  access_token: string;
  type: AccountType;
  status: AccountStatus;
  quota: number;
  imageQuotaUnknown?: boolean;
  email?: string | null;
  user_id?: string | null;
  limits_progress?: Array<{
    feature_name?: string;
    remaining?: number;
    reset_after?: string;
  }>;
  default_model_slug?: string | null;
  restoreAt?: string | null;
  success: number;
  fail: number;
  lastUsedAt: string | null;
};

type AccountListResponse = {
  items: Account[];
};

type AccountMutationResponse = {
  items: Account[];
  added?: number;
  skipped?: number;
  removed?: number;
  refreshed?: number;
  errors?: Array<{ access_token: string; error: string }>;
};

const IMAGE_JOB_POLL_INTERVAL_MS = 2_000;
const IMAGE_JOB_MAX_WAIT_MS = 15 * 60_000;

function sleep(ms: number) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function readImageJobResult<T>(job: ImageJob<T>) {
  if (job.status === "success") {
    if (!job.result) {
      throw new Error("图片任务未返回结果");
    }
    return job.result;
  }
  if (job.status === "error") {
    throw new Error(job.error || "图片任务失败");
  }
  return null;
}

export async function getImageJob<T>(jobId: string) {
  const { job } = await httpRequest<ImageJobResponse<T>>(`/api/image-jobs/${jobId}`);
  return job;
}

export async function waitForImageJob<T>(initialJobOrId: ImageJob<T> | string) {
  const initialJob = typeof initialJobOrId === "string" ? await getImageJob<T>(initialJobOrId) : initialJobOrId;
  const initialResult = readImageJobResult(initialJob);
  if (initialResult) {
    return initialResult;
  }

  const deadline = Date.now() + IMAGE_JOB_MAX_WAIT_MS;
  while (Date.now() < deadline) {
    await sleep(IMAGE_JOB_POLL_INTERVAL_MS);
    const job = await getImageJob<T>(initialJob.id);
    const result = readImageJobResult(job);
    if (result) {
      return result;
    }
  }
  throw new Error("图片任务仍在处理中，请稍后刷新历史记录查看结果");
}

export async function createImageGenerationJob(
  prompt: string,
  model: ImageModel = "gpt-image-2",
  options: ImageJobRequestOptions = {},
) {
  const { job } = await httpRequest<ImageJobResponse<GeneratedImageResponse>>(
    "/api/image-jobs/generations",
    {
      method: "POST",
      body: {
        prompt,
        model,
        ...options,
        n: 1,
        response_format: "b64_json",
      },
    },
  );
  return job;
}

export async function createImageEditJob(
  files: File | File[],
  prompt: string,
  model: ImageModel = "gpt-image-2",
  options: ImageJobRequestOptions = {},
) {
  const formData = new FormData();
  const uploadFiles = Array.isArray(files) ? files : [files];

  uploadFiles.forEach((file) => {
    formData.append("image", file);
  });
  formData.append("prompt", prompt);
  formData.append("model", model);
  if (options.size) {
    formData.append("size", options.size);
  }
  if (options.quality) {
    formData.append("quality", options.quality);
  }
  if (options.background) {
    formData.append("background", options.background);
  }
  if (options.output_format) {
    formData.append("output_format", options.output_format);
  }
  if (typeof options.compression === "number") {
    formData.append("compression", String(options.compression));
  }
  formData.append("n", "1");

  const { job } = await httpRequest<ImageJobResponse<GeneratedImageResponse>>(
    "/api/image-jobs/edits",
    {
      method: "POST",
      body: formData,
    },
  );
  return job;
}

type AccountRefreshResponse = {
  items: Account[];
  refreshed: number;
  errors: Array<{ access_token: string; error: string }>;
};

type AccountUpdateResponse = {
  item: Account;
  items: Account[];
};

type AuthLoginResponse = {
  ok: boolean;
  version: string;
  session: AuthSession;
};

type AuthSessionResponse = {
  session: AuthSession;
};

export type SettingsConfig = {
  proxy: string;
  base_url?: string;
  "auth-key"?: string;
  auth_key_configured?: boolean;
  refresh_account_interval_minute?: number | string;
  refresh_account_batch_size?: number | string;
  remote_account_sync_interval_minute?: number | string;
  auto_remove_rate_limited_accounts?: boolean;
  sensitive_word_filter_enabled?: boolean;
  sensitive_words?: string[];
  image_history_persistence_mode?: ImageHistoryPersistenceMode | string;
  [key: string]: unknown;
};

type AuthUserListResponse = {
  items: AuthUser[];
};

type AuthUserMutationResponse = {
  item?: AuthUser;
  items: AuthUser[];
};

export type RegisterMode = "total" | "quota" | "available";
export type SystemLogSource = "all" | "server" | "register";
export type SystemLogLevel = "all" | "info" | "warning" | "error" | "success";

export type RegisterMailProvider = {
  id: string;
  type: string;
  enabled: boolean;
  api_key?: string;
  api_base?: string;
  admin_password?: string;
  default_domain?: string;
  expiry_time?: number;
  random_subdomain?: boolean;
  subdomain?: string;
  wildcard?: boolean;
  domains: string[];
};

export type RegisterConfig = {
  enabled: boolean;
  mail: {
    request_timeout: number;
    wait_timeout: number;
    wait_interval: number;
    providers: RegisterMailProvider[];
  };
  proxy: string;
  total: number;
  threads: number;
  mode: RegisterMode;
  target_quota: number;
  target_available: number;
  check_interval: number;
  stats: {
    job_id?: string;
    success: number;
    fail: number;
    done: number;
    running: number;
    threads: number;
    elapsed_seconds?: number;
    avg_seconds?: number;
    success_rate?: number;
    current_quota?: number;
    current_available?: number;
    started_at?: string;
    updated_at?: string;
    finished_at?: string;
  };
  logs?: Array<{
    time: string;
    text: string;
    level: string;
  }>;
};

export type SystemLog = {
  id: string;
  source: SystemLogSource;
  level: Exclude<SystemLogLevel, "all">;
  time?: string | null;
  summary: string;
  message: string;
  detail?: Record<string, unknown>;
};

type LegacyProxySettingsResponse = {
  item: LegacyProxySettings;
};
type ProxyPoolSettingsResponse = ProxyPoolSettings;
export async function login(authKey: string) {
  const normalizedAuthKey = String(authKey || "").trim();
  return httpRequest<AuthLoginResponse>("/auth/login", {
    method: "POST",
    body: {},
    headers: {
      Authorization: `Bearer ${normalizedAuthKey}`,
    },
    redirectOnUnauthorized: false,
  });
}

export async function fetchSession() {
  return httpRequest<AuthSessionResponse>("/auth/session");
}

export async function logout() {
  return httpRequest<{ ok: boolean }>("/auth/logout", {
    method: "POST",
  });
}

export async function fetchSettingsConfig() {
  return httpRequest<{ config: SettingsConfig }>("/api/settings");
}

export async function updateSettingsConfig(settings: SettingsConfig) {
  return httpRequest<{ config: SettingsConfig }>("/api/settings", {
    method: "POST",
    body: settings,
  });
}

export async function fetchRegisterConfig() {
  return httpRequest<{ register: RegisterConfig }>("/api/register");
}

export async function updateRegisterConfig(register: {
  mail: RegisterConfig["mail"];
  proxy: string;
  total: number;
  threads: number;
  mode: RegisterMode;
  target_quota: number;
  target_available: number;
  check_interval: number;
}) {
  return httpRequest<{ register: RegisterConfig }>("/api/register", {
    method: "POST",
    body: register,
  });
}

export async function startRegisterRunner() {
  return httpRequest<{ register: RegisterConfig }>("/api/register/start", {
    method: "POST",
  });
}

export async function stopRegisterRunner() {
  return httpRequest<{ register: RegisterConfig }>("/api/register/stop", {
    method: "POST",
  });
}

export async function resetRegisterRunner() {
  return httpRequest<{ register: RegisterConfig }>("/api/register/reset", {
    method: "POST",
  });
}

export async function fetchSystemLogs(filters: {
  source?: SystemLogSource;
  query?: string;
  level?: SystemLogLevel;
  limit?: number;
}) {
  const params = new URLSearchParams();
  if (filters.source && filters.source !== "all") {
    params.set("source", filters.source);
  }
  if (filters.query) {
    params.set("query", filters.query);
  }
  if (filters.level && filters.level !== "all") {
    params.set("level", filters.level);
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  return httpRequest<{ items: SystemLog[]; query: { source: string; query: string; level: string; limit: number } }>(
    `/api/logs${params.toString() ? `?${params.toString()}` : ""}`,
  );
}

export async function fetchAccounts() {
  return httpRequest<AccountListResponse>("/api/accounts");
}

export async function createAccounts(tokens: string[]) {
  return httpRequest<AccountMutationResponse>("/api/accounts", {
    method: "POST",
    body: { tokens },
  });
}

export async function deleteAccounts(tokens: string[]) {
  return httpRequest<AccountMutationResponse>("/api/accounts", {
    method: "DELETE",
    body: { tokens },
  });
}

export async function refreshAccounts(accessTokens: string[]) {
  return httpRequest<AccountRefreshResponse>("/api/accounts/refresh", {
    method: "POST",
    body: { access_tokens: accessTokens },
  });
}

export async function updateAccount(
  accessToken: string,
  updates: {
    type?: AccountType;
    status?: AccountStatus;
    quota?: number;
  },
) {
  return httpRequest<AccountUpdateResponse>("/api/accounts/update", {
    method: "POST",
    body: {
      access_token: accessToken,
      ...updates,
    },
  });
}

export async function fetchAuthUsers() {
  return httpRequest<AuthUserListResponse>("/api/auth-users");
}

export async function createAuthUser(payload: { name: string; auth_key: string; image_quota: number }) {
  return httpRequest<AuthUserMutationResponse>("/api/auth-users", {
    method: "POST",
    body: payload,
  });
}

export async function updateAuthUser(
  userId: string,
  updates: {
    name?: string;
    auth_key?: string;
    image_quota?: number;
  },
) {
  return httpRequest<AuthUserMutationResponse>(`/api/auth-users/${userId}`, {
    method: "POST",
    body: updates,
  });
}

export async function deleteAuthUser(userId: string) {
  return httpRequest<AuthUserMutationResponse>(`/api/auth-users/${userId}`, {
    method: "DELETE",
  });
}

export async function fetchProxySettings() {
  return httpRequest<LegacyProxySettingsResponse>("/api/settings/proxy");
}

export async function updateProxySettings(proxyUrl: string) {
  return httpRequest<LegacyProxySettingsResponse>("/api/settings/proxy", {
    method: "POST",
    body: { proxy_url: proxyUrl },
  });
}

export async function fetchProxyPoolSettings() {
  return httpRequest<ProxyPoolSettingsResponse>("/api/settings/proxies");
}

export async function createProxyEntry(payload: { name: string; proxy_url: string }) {
  return httpRequest<ProxyPoolSettingsResponse>("/api/settings/proxies", {
    method: "POST",
    body: payload,
  });
}

export async function updateProxyEntry(
  proxyId: string,
  updates: {
    name?: string;
    proxy_url?: string;
  },
) {
  return httpRequest<ProxyPoolSettingsResponse>(`/api/settings/proxies/${proxyId}`, {
    method: "POST",
    body: updates,
  });
}

export async function deleteProxyEntry(proxyId: string) {
  return httpRequest<ProxyPoolSettingsResponse>(`/api/settings/proxies/${proxyId}`, {
    method: "DELETE",
  });
}

export async function generateImage(
  prompt: string,
  model: ImageModel = "gpt-image-2",
  options: ImageJobRequestOptions = {},
) {
  const job = await createImageGenerationJob(prompt, model, options);
  return waitForImageJob(job);
}

export async function editImage(
  files: File | File[],
  prompt: string,
  model: ImageModel = "gpt-image-2",
  options: ImageJobRequestOptions = {},
) {
  const job = await createImageEditJob(files, prompt, model, options);
  return waitForImageJob(job);
}

// ── CPA (CLIProxyAPI) ──────────────────────────────────────────────

export type CPAPool = {
  id: string;
  name: string;
  base_url: string;
  auto_sync_enabled: boolean;
  import_job?: CPAImportJob | null;
};

export type CPARemoteFile = {
  name: string;
  email: string;
};

export type CPAImportJob = {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed";
  created_at: string;
  updated_at: string;
  total: number;
  completed: number;
  added: number;
  skipped: number;
  refreshed: number;
  failed: number;
  errors: Array<{ name: string; error: string }>;
};

export async function fetchCPAPools() {
  return httpRequest<{ pools: CPAPool[] }>("/api/cpa/pools");
}

export async function createCPAPool(pool: {
  name: string;
  base_url: string;
  secret_key: string;
  auto_sync_enabled: boolean;
}) {
  return httpRequest<{ pool: CPAPool; pools: CPAPool[] }>("/api/cpa/pools", {
    method: "POST",
    body: pool,
  });
}

export async function updateCPAPool(
  poolId: string,
  updates: { name?: string; base_url?: string; secret_key?: string; auto_sync_enabled?: boolean },
) {
  return httpRequest<{ pool: CPAPool; pools: CPAPool[] }>(`/api/cpa/pools/${poolId}`, {
    method: "POST",
    body: updates,
  });
}

export async function deleteCPAPool(poolId: string) {
  return httpRequest<{ pools: CPAPool[] }>(`/api/cpa/pools/${poolId}`, {
    method: "DELETE",
  });
}

export async function fetchCPAPoolFiles(poolId: string) {
  return httpRequest<{ pool_id: string; files: CPARemoteFile[] }>(`/api/cpa/pools/${poolId}/files`);
}

export async function startCPAImport(poolId: string, names: string[]) {
  return httpRequest<{ import_job: CPAImportJob | null }>(`/api/cpa/pools/${poolId}/import`, {
    method: "POST",
    body: { names },
  });
}

export async function fetchCPAPoolImportJob(poolId: string) {
  return httpRequest<{ import_job: CPAImportJob | null }>(`/api/cpa/pools/${poolId}/import`);
}

// ── Sub2API ────────────────────────────────────────────────────────

export type Sub2APIServer = {
  id: string;
  name: string;
  base_url: string;
  email: string;
  has_api_key: boolean;
  group_id: string;
  auto_sync_enabled: boolean;
  import_job?: CPAImportJob | null;
};

export type Sub2APIRemoteAccount = {
  id: string;
  name: string;
  email: string;
  plan_type: string;
  status: string;
  expires_at: string;
  has_refresh_token: boolean;
};

export type Sub2APIRemoteGroup = {
  id: string;
  name: string;
  description: string;
  platform: string;
  status: string;
  account_count: number;
  active_account_count: number;
};

export async function fetchSub2APIServers() {
  return httpRequest<{ servers: Sub2APIServer[] }>("/api/sub2api/servers");
}

export async function createSub2APIServer(server: {
  name: string;
  base_url: string;
  email: string;
  password: string;
  api_key: string;
  group_id: string;
  auto_sync_enabled: boolean;
}) {
  return httpRequest<{ server: Sub2APIServer; servers: Sub2APIServer[] }>("/api/sub2api/servers", {
    method: "POST",
    body: server,
  });
}

export async function updateSub2APIServer(
  serverId: string,
  updates: {
    name?: string;
    base_url?: string;
    email?: string;
    password?: string;
    api_key?: string;
    group_id?: string;
    auto_sync_enabled?: boolean;
  },
) {
  return httpRequest<{ server: Sub2APIServer; servers: Sub2APIServer[] }>(`/api/sub2api/servers/${serverId}`, {
    method: "POST",
    body: updates,
  });
}

export async function fetchSub2APIServerGroups(serverId: string) {
  return httpRequest<{ server_id: string; groups: Sub2APIRemoteGroup[] }>(
    `/api/sub2api/servers/${serverId}/groups`,
  );
}

export async function deleteSub2APIServer(serverId: string) {
  return httpRequest<{ servers: Sub2APIServer[] }>(`/api/sub2api/servers/${serverId}`, {
    method: "DELETE",
  });
}

export async function fetchSub2APIServerAccounts(serverId: string) {
  return httpRequest<{ server_id: string; accounts: Sub2APIRemoteAccount[] }>(
    `/api/sub2api/servers/${serverId}/accounts`,
  );
}

export async function startSub2APIImport(serverId: string, accountIds: string[]) {
  return httpRequest<{ import_job: CPAImportJob | null }>(`/api/sub2api/servers/${serverId}/import`, {
    method: "POST",
    body: { account_ids: accountIds },
  });
}

export async function fetchSub2APIImportJob(serverId: string) {
  return httpRequest<{ import_job: CPAImportJob | null }>(`/api/sub2api/servers/${serverId}/import`);
}

// ── Upstream proxy ────────────────────────────────────────────────

export type ProxySettings = {
  enabled: boolean;
  url: string;
};

export type ProxyTestResult = {
  ok: boolean;
  status: number;
  latency_ms: number;
  error: string | null;
};

export async function fetchProxy() {
  return httpRequest<{ proxy: ProxySettings }>("/api/proxy");
}

export async function updateProxy(updates: { enabled?: boolean; url?: string }) {
  return httpRequest<{ proxy: ProxySettings }>("/api/proxy", {
    method: "POST",
    body: updates,
  });
}

export async function testProxy(url?: string) {
  return httpRequest<{ result: ProxyTestResult }>("/api/proxy/test", {
    method: "POST",
    body: { url: url ?? "" },
  });
}
