/**
 * Hinweisgebersystem – Admin Users API Functions.
 *
 * All admin-facing API calls for backend user management.  Users are
 * handlers, admins, and auditors who authenticate via OIDC (Microsoft
 * Entra ID).  Supports listing with filters, creating new users
 * (pre-registration before first OIDC login), and updating role,
 * active status, and custodian designation.
 *
 * Authentication is handled automatically by the axios interceptor
 * in ``client.ts`` which attaches the OIDC Bearer token.
 */

import apiClient from '@/api/client';
import type { PaginatedResponse, PaginationMeta } from '@/api/cases';

// ── Enums ──────────────────────────────────────────────────────

export const UserRole = {
  SYSTEM_ADMIN: 'system_admin',
  TENANT_ADMIN: 'tenant_admin',
  HANDLER: 'handler',
  REVIEWER: 'reviewer',
  AUDITOR: 'auditor',
} as const;
export type UserRole = (typeof UserRole)[keyof typeof UserRole];

// ── Response Types ─────────────────────────────────────────────

export interface UserResponse {
  id: string;
  tenant_id: string;
  email: string;
  display_name: string;
  oidc_subject: string;
  role: UserRole;
  is_active: boolean;
  is_custodian: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface UserSummary {
  id: string;
  email: string;
  display_name: string;
  role: UserRole;
}

export type UserListResponse = PaginatedResponse<UserResponse>;

// ── Request Types ──────────────────────────────────────────────

export interface UserCreateRequest {
  email: string;
  display_name: string;
  oidc_subject: string;
  role?: UserRole;
  is_custodian?: boolean;
}

export interface UserUpdateRequest {
  display_name?: string;
  role?: UserRole;
  is_active?: boolean;
  is_custodian?: boolean;
}

// ── Filter / Query Parameters ──────────────────────────────────

export interface UserListParams {
  page?: number;
  page_size?: number;
  role?: UserRole;
  is_active?: boolean;
  is_custodian?: boolean;
  search?: string;
}

// ── Users API ──────────────────────────────────────────────────

/**
 * Fetch paginated user list with filters.
 *
 * Supports filtering by role, active status, custodian status,
 * and free-text search on email / display name.
 */
export async function getUsers(
  params: UserListParams = {},
): Promise<UserListResponse> {
  const response = await apiClient.get<UserListResponse>('/admin/users', {
    params,
  });
  return response.data;
}

/**
 * Get a single user by ID.
 *
 * Returns the full user record including role, active status,
 * custodian capability, and timestamps.
 */
export async function getUser(userId: string): Promise<UserResponse> {
  const response = await apiClient.get<UserResponse>(
    `/admin/users/${userId}`,
  );
  return response.data;
}

/**
 * Create a new backend user (pre-register before first OIDC login).
 *
 * The user will be created with the specified OIDC subject claim
 * so that on their first OIDC login they are automatically matched
 * to this pre-registered account with the assigned role.
 */
export async function createUser(
  data: UserCreateRequest,
): Promise<UserResponse> {
  const response = await apiClient.post<UserResponse>('/admin/users', data);
  return response.data;
}

/**
 * Update a user's role, display name, activation status, or
 * custodian capability.
 *
 * All fields are optional — only provided fields will be updated.
 * Role changes are validated against the privilege hierarchy.
 */
export async function updateUser(
  userId: string,
  data: UserUpdateRequest,
): Promise<UserResponse> {
  const response = await apiClient.patch<UserResponse>(
    `/admin/users/${userId}`,
    data,
  );
  return response.data;
}
