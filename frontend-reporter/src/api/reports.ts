/**
 * Hinweisgebersystem - Report API Functions.
 *
 * All reporter-facing API calls for submitting reports, authenticating
 * to the mailbox, and managing the mailbox session.  Supports both
 * HinSchG (internal) and LkSG (public) channels.
 *
 * Authentication for mailbox endpoints uses short-lived JWT tokens
 * passed via the Authorization header.  No cookies or localStorage
 * are used in anonymous mode.
 */

import apiClient from '@/api/client';
import type {
  AttachmentSummary,
  MailboxLoginResponse,
  MagicLinkResponse,
  MagicLinkVerifyResponse,
  ReportCreateResponse,
  ReportFormData,
  ReportMailboxResponse,
} from '@/schemas/report';

// ── Helper: Authorization header ────────────────────────────

function authHeader(token: string) {
  return { Authorization: `Bearer ${token}` };
}

// ── Report Submission ───────────────────────────────────────

/**
 * Submit a new HinSchG (internal) report.
 *
 * The backend auto-assigns `channel: "hinschg"`, generates a
 * 16-character case number, and returns the 6-word BIP-39 passphrase
 * (if no self-chosen password was provided).
 */
export async function createReport(
  data: ReportFormData,
): Promise<ReportCreateResponse> {
  const response = await apiClient.post<ReportCreateResponse>(
    '/reports',
    data,
  );
  return response.data;
}

/**
 * Submit a new LkSG (public) complaint.
 *
 * Same payload structure as `createReport` but posted to the public
 * complaints endpoint.  Requires LkSG-extended fields (country,
 * organization, lksg_category).
 */
export async function createLksgComplaint(
  data: ReportFormData,
): Promise<ReportCreateResponse> {
  const response = await apiClient.post<ReportCreateResponse>(
    '/public/complaints',
    data,
  );
  return response.data;
}

// ── Mailbox Authentication ──────────────────────────────────

/**
 * Authenticate to the HinSchG anonymous mailbox.
 *
 * Returns a JWT session token valid for 4 hours.
 */
export async function verifyCredentials(
  caseNumber: string,
  passphrase: string,
): Promise<MailboxLoginResponse> {
  const response = await apiClient.post<MailboxLoginResponse>(
    '/reports/verify',
    {
      case_number: caseNumber,
      passphrase,
    },
  );
  return response.data;
}

/**
 * Authenticate to the LkSG anonymous mailbox.
 *
 * Validates that the case belongs to the LkSG channel before issuing
 * a session token.
 */
export async function verifyLksgCredentials(
  caseNumber: string,
  passphrase: string,
): Promise<MailboxLoginResponse> {
  const response = await apiClient.post<MailboxLoginResponse>(
    '/public/complaints/verify',
    {
      case_number: caseNumber,
      passphrase,
    },
  );
  return response.data;
}

/**
 * Request a magic link email for non-anonymous reporters.
 *
 * Always returns a success message regardless of whether the email
 * was found, to prevent user enumeration.
 */
export async function requestMagicLink(
  caseNumber: string,
  email: string,
): Promise<MagicLinkResponse> {
  const response = await apiClient.post<MagicLinkResponse>(
    '/auth/magic-link/request',
    {
      case_number: caseNumber,
      email,
    },
  );
  return response.data;
}

/**
 * Verify a magic link JWT token from the email URL.
 *
 * Returns the same session data as a mailbox login (token valid 24h).
 */
export async function verifyMagicLink(
  token: string,
): Promise<MagicLinkVerifyResponse> {
  const response = await apiClient.post<MagicLinkVerifyResponse>(
    '/auth/magic-link/verify',
    { token },
  );
  return response.data;
}

// ── Mailbox Status ──────────────────────────────────────────

/**
 * Get the current report status for the authenticated mailbox session.
 *
 * Returns a limited view (excludes priority, assignment, internal notes).
 */
export async function getStatus(
  token: string,
): Promise<ReportMailboxResponse> {
  const response = await apiClient.get<ReportMailboxResponse>(
    '/reports/mailbox/status',
    { headers: authHeader(token) },
  );
  return response.data;
}

/**
 * Get the LkSG complaint status for the authenticated mailbox session.
 */
export async function getLksgStatus(
  token: string,
): Promise<ReportMailboxResponse> {
  const response = await apiClient.get<ReportMailboxResponse>(
    '/public/complaints/mailbox/status',
    { headers: authHeader(token) },
  );
  return response.data;
}

// ── File Attachments ────────────────────────────────────────

/**
 * Upload a file attachment directly to a report.
 *
 * Used immediately after report creation to attach files without
 * requiring a message ID.  The backend creates an initial system
 * message if needed.
 */
export async function uploadReportAttachment(
  token: string,
  file: File,
): Promise<AttachmentSummary> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await apiClient.post<AttachmentSummary>(
    '/reports/mailbox/attachments',
    formData,
    {
      headers: {
        ...authHeader(token),
        'Content-Type': 'multipart/form-data',
      },
      timeout: 120_000,
    },
  );
  return response.data;
}

/**
 * Upload a file attachment to a message.
 *
 * Files are encrypted server-side with AES-256-GCM before storage.
 * Max 50 MB per file, max 10 files per message.
 */
export async function uploadAttachment(
  token: string,
  messageId: string,
  file: File,
): Promise<AttachmentSummary> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await apiClient.post<AttachmentSummary>(
    `/reports/mailbox/messages/${messageId}/attachments`,
    formData,
    {
      headers: {
        ...authHeader(token),
        'Content-Type': 'multipart/form-data',
      },
      timeout: 120_000, // 2 minutes for large files
    },
  );
  return response.data;
}

/**
 * Download a file attachment.
 *
 * Returns a Blob of the decrypted file.
 */
export async function downloadAttachment(
  token: string,
  attachmentId: string,
): Promise<Blob> {
  const response = await apiClient.get(
    `/reports/mailbox/attachments/${attachmentId}`,
    {
      headers: authHeader(token),
      responseType: 'blob',
      timeout: 120_000,
    },
  );
  return response.data as Blob;
}
