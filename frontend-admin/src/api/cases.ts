/**
 * Hinweisgebersystem – Admin Cases API Functions.
 *
 * All admin-facing API calls for case (report) management.  Covers
 * the complete case lifecycle: listing with filters/search/pagination,
 * detail view, status/priority/assignment updates, messaging, internal
 * notes, audit trail, and custodian identity disclosure workflow.
 *
 * Authentication is handled automatically by the axios interceptor
 * in ``client.ts`` which attaches the OIDC Bearer token from the
 * current session.
 */

import apiClient from '@/api/client';
import type { LabelSummary } from '@/api/labels';

// ── TypeScript Types ───────────────────────────────────────────
// Mirror backend Pydantic schemas as TypeScript interfaces.
// These are read-only response types — no Zod validation needed
// for admin-consumed data.

// ── Enums ──────────────────────────────────────────────────────

export const ReportStatus = {
  EINGEGANGEN: 'eingegangen',
  IN_PRUEFUNG: 'in_pruefung',
  IN_BEARBEITUNG: 'in_bearbeitung',
  RUECKMELDUNG: 'rueckmeldung',
  ABGESCHLOSSEN: 'abgeschlossen',
} as const;
export type ReportStatus = (typeof ReportStatus)[keyof typeof ReportStatus];

export const Priority = {
  LOW: 'low',
  MEDIUM: 'medium',
  HIGH: 'high',
  CRITICAL: 'critical',
} as const;
export type Priority = (typeof Priority)[keyof typeof Priority];

export const Channel = {
  HINSCHG: 'hinschg',
  LKSG: 'lksg',
} as const;
export type Channel = (typeof Channel)[keyof typeof Channel];

export const SenderType = {
  REPORTER: 'reporter',
  HANDLER: 'handler',
  SYSTEM: 'system',
} as const;
export type SenderType = (typeof SenderType)[keyof typeof SenderType];

export const DisclosureStatus = {
  PENDING: 'pending',
  APPROVED: 'approved',
  REJECTED: 'rejected',
  EXPIRED: 'expired',
} as const;
export type DisclosureStatus =
  (typeof DisclosureStatus)[keyof typeof DisclosureStatus];

// ── Response Types ─────────────────────────────────────────────

export interface PaginationMeta {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  pagination: PaginationMeta;
}

export interface AttachmentSummary {
  id: string;
  original_filename: string;
  content_type: string;
  file_size: number;
  created_at: string;
}

export interface MessageResponse {
  id: string;
  report_id: string;
  sender_type: SenderType;
  sender_user_id: string | null;
  is_internal: boolean;
  is_read: boolean;
  created_at: string;
  content: string | null;
  attachments: AttachmentSummary[];
}

export interface AuditLogEntry {
  id: string;
  action: string;
  actor_id: string | null;
  actor_type: string;
  resource_type: string;
  resource_id: string;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

export interface CaseListItem {
  id: string;
  tenant_id: string;
  case_number: string;
  is_anonymous: boolean;
  channel: Channel;
  status: ReportStatus;
  priority: Priority;
  category: string | null;
  language: string;
  subject: string | null;
  description: string | null;
  reporter_name: string | null;
  reporter_email: string | null;
  reporter_phone: string | null;
  country: string | null;
  organization: string | null;
  supply_chain_tier: string | null;
  reporter_relationship: string | null;
  lksg_category: string | null;
  assigned_to: string | null;
  confirmation_deadline: string | null;
  feedback_deadline: string | null;
  confirmation_sent_at: string | null;
  feedback_sent_at: string | null;
  retention_until: string | null;
  related_case_numbers: string[] | null;
  version: number;
  created_at: string;
  updated_at: string;
  unread_count: number;
  is_overdue_confirmation: boolean;
  is_overdue_feedback: boolean;
  labels: LabelSummary[];
}

export interface CaseDetailResponse extends CaseListItem {
  messages: MessageResponse[];
  audit_trail: AuditLogEntry[];
}

export type CaseListResponse = PaginatedResponse<CaseListItem>;

// ── Request Types ──────────────────────────────────────────────

export interface CaseUpdateRequest {
  status?: ReportStatus;
  priority?: Priority;
  assigned_to?: string;
  category?: string;
  related_case_numbers?: string[];
  version: number;
}

export interface MessageCreateRequest {
  content: string;
  is_internal?: boolean;
}

export interface DisclosureRequestCreate {
  report_id: string;
  reason: string;
}

export interface DisclosureDecisionRequest {
  approved: boolean;
  decision_reason?: string;
}

export interface DisclosureResponse {
  id: string;
  report_id: string;
  tenant_id: string;
  requester_id: string;
  reason: string;
  status: DisclosureStatus;
  custodian_id: string | null;
  decision_reason: string | null;
  decided_at: string | null;
  created_at: string;
}

export interface IdentityRevealResponse {
  reporter_name: string | null;
  reporter_email: string | null;
  reporter_phone: string | null;
  disclosure_id: string;
}

// ── Filter / Query Parameters ──────────────────────────────────

export interface CaseListParams {
  page?: number;
  page_size?: number;
  status?: ReportStatus;
  priority?: Priority;
  channel?: Channel;
  category?: string;
  assigned_to?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
  overdue_only?: boolean;
  label_id?: string;
  sort_by?: string;
  sort_desc?: boolean;
}

// ── Dashboard Types ────────────────────────────────────────────

export interface StatusCount {
  status: string;
  count: number;
}

export interface ChannelCount {
  channel: string;
  count: number;
}

export interface PriorityCount {
  priority: string;
  count: number;
}

export interface MonthlyTrend {
  month: string;
  count: number;
}

export interface DashboardStatsResponse {
  total_cases: number;
  by_status: StatusCount[];
  by_channel: ChannelCount[];
  by_priority: PriorityCount[];
  overdue_count: number;
  avg_resolution_days: number | null;
  monthly_trend: MonthlyTrend[];
}

// ── Cases API ──────────────────────────────────────────────────

/**
 * Fetch paginated case list with filters, search, and sorting.
 *
 * Supports full-text search with German stemming, multi-field
 * filtering, and configurable sort order.  Deadline overdue
 * highlighting is included for each case.
 */
export async function getCases(
  params: CaseListParams = {},
): Promise<CaseListResponse> {
  const response = await apiClient.get<CaseListResponse>('/admin/cases', {
    params,
  });
  return response.data;
}

/**
 * Fetch full case detail with messages and audit trail.
 *
 * Returns the complete case record with decrypted fields, all
 * messages (including internal handler notes), and the chronological
 * audit trail.  Automatically marks unread reporter messages as read.
 */
export async function getCase(caseId: string): Promise<CaseDetailResponse> {
  const response = await apiClient.get<CaseDetailResponse>(
    `/admin/cases/${caseId}`,
  );
  return response.data;
}

/**
 * Update case metadata with optimistic locking.
 *
 * Supports updating status (with workflow validation), priority,
 * handler assignment, category, and related case numbers.  The
 * ``version`` field must match the current database version.
 */
export async function updateCase(
  caseId: string,
  data: CaseUpdateRequest,
): Promise<CaseListItem> {
  const response = await apiClient.patch<CaseListItem>(
    `/admin/cases/${caseId}`,
    data,
  );
  return response.data;
}

/**
 * Send a message to the reporter visible in the anonymous mailbox.
 *
 * Message content is encrypted at the ORM level via pgcrypto.
 */
export async function sendMessage(
  caseId: string,
  content: string,
): Promise<MessageResponse> {
  const response = await apiClient.post<MessageResponse>(
    `/admin/cases/${caseId}/messages`,
    { content, is_internal: false },
  );
  return response.data;
}

/**
 * Create an internal note visible only to handlers.
 *
 * Internal notes are never shown to the reporter in the anonymous
 * mailbox.  Used for handler-to-handler communication and
 * investigation documentation.
 */
export async function createNote(
  caseId: string,
  content: string,
): Promise<MessageResponse> {
  const response = await apiClient.post<MessageResponse>(
    `/admin/cases/${caseId}/notes`,
    { content, is_internal: true },
  );
  return response.data;
}

/**
 * Get the chronological audit trail for a specific case.
 *
 * Returns all audit log entries associated with the given case,
 * ordered from oldest to newest.
 */
export async function getCaseAudit(
  caseId: string,
): Promise<AuditLogEntry[]> {
  const response = await apiClient.get<AuditLogEntry[]>(
    `/admin/cases/${caseId}/audit`,
  );
  return response.data;
}

/**
 * Fetch KPI dashboard statistics.
 *
 * Returns case counts by status, channel, priority, overdue count,
 * average resolution time, and monthly trend data.
 */
export async function getDashboardStats(): Promise<DashboardStatsResponse> {
  const response = await apiClient.get<DashboardStatsResponse>(
    '/admin/dashboard/stats',
  );
  return response.data;
}

// ── Custodian / Identity Disclosure ────────────────────────────

/**
 * Request identity disclosure for an anonymous report (handler action).
 *
 * A mandatory reason must be provided for audit compliance.
 * The request enters PENDING status and must be approved by a
 * designated custodian.
 */
export async function requestDisclosure(
  data: DisclosureRequestCreate,
): Promise<DisclosureResponse> {
  const response = await apiClient.post<DisclosureResponse>(
    '/admin/custodian/disclosures',
    data,
  );
  return response.data;
}

/**
 * Approve or reject a pending disclosure request (custodian action).
 *
 * Only users designated as custodians may decide on requests.
 * The custodian must be a different person than the requester
 * (4-eyes principle).
 */
export async function approveDisclosure(
  disclosureId: string,
  data: DisclosureDecisionRequest,
): Promise<DisclosureResponse> {
  const response = await apiClient.post<DisclosureResponse>(
    `/admin/custodian/disclosures/${disclosureId}/decide`,
    data,
  );
  return response.data;
}

/**
 * List all pending disclosure requests for the tenant.
 *
 * Used by custodians to see which requests are awaiting their
 * decision.
 */
export async function getPendingDisclosures(): Promise<DisclosureResponse[]> {
  const response = await apiClient.get<DisclosureResponse[]>(
    '/admin/custodian/disclosures/pending',
  );
  return response.data;
}

/**
 * Get a single disclosure request by ID.
 */
export async function getDisclosure(
  disclosureId: string,
): Promise<DisclosureResponse> {
  const response = await apiClient.get<DisclosureResponse>(
    `/admin/custodian/disclosures/${disclosureId}`,
  );
  return response.data;
}

/**
 * List all disclosure requests for a specific report.
 */
export async function getReportDisclosures(
  reportId: string,
): Promise<DisclosureResponse[]> {
  const response = await apiClient.get<DisclosureResponse[]>(
    `/admin/custodian/reports/${reportId}/disclosures`,
  );
  return response.data;
}

/**
 * Reveal the sealed reporter identity after approved disclosure.
 *
 * Only callable when the disclosure status is APPROVED.  Only the
 * original requester may view the identity.  Access is logged for
 * compliance.
 */
export async function revealIdentity(
  disclosureId: string,
): Promise<IdentityRevealResponse> {
  const response = await apiClient.post<IdentityRevealResponse>(
    `/admin/custodian/disclosures/${disclosureId}/reveal`,
  );
  return response.data;
}
