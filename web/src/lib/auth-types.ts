export type UserRole = "admin" | "user";

export type AuthSession = {
  role: UserRole;
  name: string;
  image_quota: number | null;
  total_generated: number | null;
  last_used_at: string | null;
};

export type AuthUser = {
  id: string;
  name: string;
  role: "user";
  auth_key: string;
  image_quota: number;
  total_generated: number;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
};
