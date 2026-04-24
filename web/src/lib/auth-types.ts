export type UserRole = "admin" | "user";
export type ImageHistoryPersistenceMode = "browser" | "server";

export type AuthSession = {
  id: string;
  role: UserRole;
  name: string;
  image_quota: number | null;
  total_generated: number | null;
  last_used_at: string | null;
  image_history_persistence_mode: ImageHistoryPersistenceMode;
};

export type AuthUser = {
  id: string;
  name: string;
  role: "user";
  auth_key: string;
  auth_key_set: boolean;
  image_quota: number;
  total_generated: number;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
};
