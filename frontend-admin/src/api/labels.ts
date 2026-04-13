/**
 * Hinweisgebersystem – Admin Labels API Functions.
 *
 * All admin-facing API calls for label management.  Labels are
 * tenant-scoped tags that can be assigned to reports for flexible
 * categorisation and filtering (e.g. "Urgent", "Compliance",
 * "Follow-up needed").
 *
 * Supports full CRUD operations on labels and assignment/removal
 * of labels to/from individual cases.
 *
 * Authentication is handled automatically by the axios interceptor
 * in ``client.ts`` which attaches the OIDC Bearer token.
 */

import apiClient from '@/api/client';
import type { PaginatedResponse, PaginationMeta } from '@/api/cases';

// ── Response Types ─────────────────────────────────────────────

export interface LabelResponse {
  id: string;
  tenant_id: string;
  name: string;
  color: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface LabelSummary {
  id: string;
  name: string;
  color: string;
}

export type LabelListResponse = PaginatedResponse<LabelResponse>;

// ── Request Types ──────────────────────────────────────────────

export interface LabelCreateRequest {
  name: string;
  color?: string;
  description?: string | null;
}

export interface LabelUpdateRequest {
  name?: string;
  color?: string;
  description?: string | null;
  is_active?: boolean;
}

export interface LabelAssignmentRequest {
  label_id: string;
}

// ── Filter / Query Parameters ──────────────────────────────────

export interface LabelListParams {
  page?: number;
  page_size?: number;
  active_only?: boolean;
}

// ── Labels CRUD API ────────────────────────────────────────────

/**
 * Fetch paginated label list for the current tenant.
 *
 * Supports filtering to active-only labels (for assignment
 * dropdowns) and pagination.  Labels are sorted by name.
 */
export async function getLabels(
  params: LabelListParams = {},
): Promise<LabelListResponse> {
  const response = await apiClient.get<LabelListResponse>('/admin/labels', {
    params,
  });
  return response.data;
}

/**
 * Get a single label by ID.
 *
 * Returns the full label record including colour, description,
 * active status, and timestamps.
 */
export async function getLabel(labelId: string): Promise<LabelResponse> {
  const response = await apiClient.get<LabelResponse>(
    `/admin/labels/${labelId}`,
  );
  return response.data;
}

/**
 * Create a new label for the current tenant.
 *
 * The label name must be unique within the tenant.  An optional
 * hex colour code and description can be provided.
 */
export async function createLabel(
  data: LabelCreateRequest,
): Promise<LabelResponse> {
  const response = await apiClient.post<LabelResponse>('/admin/labels', data);
  return response.data;
}

/**
 * Update a label's name, colour, description, or active status.
 *
 * All fields are optional — only provided fields will be updated.
 */
export async function updateLabel(
  labelId: string,
  data: LabelUpdateRequest,
): Promise<LabelResponse> {
  const response = await apiClient.put<LabelResponse>(
    `/admin/labels/${labelId}`,
    data,
  );
  return response.data;
}

/**
 * Deactivate a label (soft delete).
 *
 * The label is not physically deleted — it is marked as inactive
 * so that existing report assignments are preserved.  Inactive
 * labels are hidden from new assignment dropdowns.
 */
export async function deleteLabel(labelId: string): Promise<void> {
  await apiClient.delete(`/admin/labels/${labelId}`);
}

// ── Label Assignment API ───────────────────────────────────────

/**
 * Assign a label to a case.
 *
 * The label must belong to the same tenant and be active.
 * Returns the updated list of labels assigned to the case.
 */
export async function assignLabelToCase(
  caseId: string,
  labelId: string,
): Promise<LabelSummary[]> {
  const response = await apiClient.post<LabelSummary[]>(
    `/admin/cases/${caseId}/labels`,
    { label_id: labelId } satisfies LabelAssignmentRequest,
  );
  return response.data;
}

/**
 * Remove a label from a case.
 *
 * Returns the updated list of labels assigned to the case.
 */
export async function removeLabelFromCase(
  caseId: string,
  labelId: string,
): Promise<LabelSummary[]> {
  const response = await apiClient.delete<LabelSummary[]>(
    `/admin/cases/${caseId}/labels/${labelId}`,
  );
  return response.data;
}
