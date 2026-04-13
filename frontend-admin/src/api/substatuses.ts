/**
 * Hinweisgebersystem – Admin Sub-Statuses API Functions.
 *
 * All admin-facing API calls for sub-status management.  Sub-statuses
 * are tenant-scoped refinements of the five fixed HinSchG case
 * lifecycle statuses (e.g. "Waiting for external input" under
 * ``in_bearbeitung``).
 *
 * Supports full CRUD operations: listing (with optional parent status
 * filter), creation, retrieval, update, and soft deletion.
 *
 * Authentication is handled automatically by the axios interceptor
 * in ``client.ts`` which attaches the OIDC Bearer token.
 */

import apiClient from '@/api/client';
import type { ReportStatus, PaginatedResponse } from '@/api/cases';

// ── Response Types ─────────────────────────────────────────────

export interface SubStatusResponse {
  id: string;
  tenant_id: string;
  parent_status: ReportStatus;
  name: string;
  display_order: number;
  is_default: boolean;
  is_active: boolean;
  created_at: string;
}

export interface SubStatusSummary {
  id: string;
  parent_status: ReportStatus;
  name: string;
}

export type SubStatusListResponse = PaginatedResponse<SubStatusResponse>;

// ── Request Types ──────────────────────────────────────────────

export interface SubStatusCreateRequest {
  parent_status: ReportStatus;
  name: string;
  display_order?: number;
  is_default?: boolean;
}

export interface SubStatusUpdateRequest {
  name?: string;
  display_order?: number;
  is_default?: boolean;
  is_active?: boolean;
}

// ── Filter / Query Parameters ──────────────────────────────────

export interface SubStatusListParams {
  parent_status?: ReportStatus;
  active_only?: boolean;
  page?: number;
  page_size?: number;
}

// ── Sub-Statuses CRUD API ──────────────────────────────────────

/**
 * Fetch paginated sub-status list for the current tenant.
 *
 * Supports filtering by parent status (for populating dropdowns
 * per lifecycle stage) and active-only filtering.  Results are
 * sorted by parent status, display order, then name.
 */
export async function getSubStatuses(
  params: SubStatusListParams = {},
): Promise<SubStatusListResponse> {
  const response = await apiClient.get<SubStatusListResponse>(
    '/admin/substatuses',
    { params },
  );
  return response.data;
}

/**
 * Get a single sub-status by ID.
 *
 * Returns the full sub-status record including parent status,
 * display order, default flag, active status, and timestamps.
 */
export async function getSubStatus(
  subStatusId: string,
): Promise<SubStatusResponse> {
  const response = await apiClient.get<SubStatusResponse>(
    `/admin/substatuses/${subStatusId}`,
  );
  return response.data;
}

/**
 * Create a new sub-status for the current tenant.
 *
 * The sub-status name must be unique within the tenant and parent
 * status combination.  An optional display order and default flag
 * can be provided.  If ``is_default`` is true, any existing default
 * for the same parent status will be unset.
 */
export async function createSubStatus(
  data: SubStatusCreateRequest,
): Promise<SubStatusResponse> {
  const response = await apiClient.post<SubStatusResponse>(
    '/admin/substatuses',
    data,
  );
  return response.data;
}

/**
 * Update a sub-status's name, display order, default flag, or
 * active status.
 *
 * All fields are optional — only provided fields will be updated.
 * If ``is_default`` is set to true, any existing default for the
 * same parent status will be unset.
 */
export async function updateSubStatus(
  subStatusId: string,
  data: SubStatusUpdateRequest,
): Promise<SubStatusResponse> {
  const response = await apiClient.put<SubStatusResponse>(
    `/admin/substatuses/${subStatusId}`,
    data,
  );
  return response.data;
}

/**
 * Deactivate a sub-status (soft delete).
 *
 * The sub-status is not physically deleted — it is marked as
 * inactive so that existing report assignments are preserved.
 * Inactive sub-statuses are hidden from new assignment dropdowns.
 */
export async function deleteSubStatus(
  subStatusId: string,
): Promise<void> {
  await apiClient.delete(`/admin/substatuses/${subStatusId}`);
}
