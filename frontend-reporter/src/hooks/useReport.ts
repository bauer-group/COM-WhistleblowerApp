/**
 * Hinweisgebersystem - TanStack Query Hooks for Report Operations.
 *
 * Provides React Query v5 hooks (object syntax) for:
 * - Submitting reports (HinSchG and LkSG)
 * - Authenticating to the mailbox
 * - Fetching report status
 * - Magic link authentication flow
 * - File attachment upload/download
 *
 * All hooks follow TanStack Query v5 conventions:
 * - Object syntax for useQuery/useMutation
 * - queryKey as array
 * - invalidateQueries on mutation success
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createLksgComplaint,
  createReport,
  downloadAttachment,
  getLksgStatus,
  getStatus,
  requestMagicLink,
  uploadAttachment,
  verifyCredentials,
  verifyLksgCredentials,
  verifyMagicLink,
} from '@/api/reports';
import type {
  MailboxLoginResponse,
  MagicLinkResponse,
  MagicLinkVerifyResponse,
  ReportCreateResponse,
  ReportFormData,
  ReportMailboxResponse,
} from '@/schemas/report';
import type { Channel } from '@/schemas/report';

// ── Query Keys ──────────────────────────────────────────────

export const reportKeys = {
  all: ['report'] as const,
  status: (token: string) => [...reportKeys.all, 'status', token] as const,
  attachment: (token: string, attachmentId: string) =>
    [...reportKeys.all, 'attachment', token, attachmentId] as const,
} as const;

// ── Report Submission ───────────────────────────────────────

/**
 * Submit a new report (HinSchG or LkSG based on channel).
 *
 * On success returns the case number and passphrase that the
 * reporter must save for mailbox access.
 */
export function useCreateReport() {
  return useMutation<ReportCreateResponse, Error, ReportFormData>({
    mutationFn: (data) => {
      if (data.channel === 'lksg') {
        return createLksgComplaint(data);
      }
      return createReport(data);
    },
  });
}

// ── Mailbox Authentication ──────────────────────────────────

interface VerifyCredentialsParams {
  caseNumber: string;
  passphrase: string;
  channel?: Channel;
}

/**
 * Authenticate to the anonymous mailbox.
 *
 * Routes to the correct endpoint based on the channel (HinSchG or LkSG).
 * Returns a JWT session token for subsequent mailbox API calls.
 */
export function useVerifyCredentials() {
  return useMutation<MailboxLoginResponse, Error, VerifyCredentialsParams>({
    mutationFn: ({ caseNumber, passphrase, channel }) => {
      if (channel === 'lksg') {
        return verifyLksgCredentials(caseNumber, passphrase);
      }
      return verifyCredentials(caseNumber, passphrase);
    },
  });
}

// ── Magic Link ──────────────────────────────────────────────

interface MagicLinkRequestParams {
  caseNumber: string;
  email: string;
}

/**
 * Request a magic link email for non-anonymous reporters.
 */
export function useRequestMagicLink() {
  return useMutation<MagicLinkResponse, Error, MagicLinkRequestParams>({
    mutationFn: ({ caseNumber, email }) =>
      requestMagicLink(caseNumber, email),
  });
}

/**
 * Verify a magic link JWT token from the email URL.
 *
 * Returns a 24-hour session token for mailbox access.
 */
export function useVerifyMagicLink() {
  return useMutation<MagicLinkVerifyResponse, Error, string>({
    mutationFn: (token) => verifyMagicLink(token),
  });
}

// ── Report Status ───────────────────────────────────────────

interface UseReportStatusOptions {
  /** JWT session token from mailbox login. */
  token: string;
  /** Reporting channel to route to the correct endpoint. */
  channel?: Channel;
  /** Whether the query should execute. Defaults to true. */
  enabled?: boolean;
}

/**
 * Fetch the report status for the authenticated mailbox session.
 *
 * Returns a limited reporter view (excludes priority, assignment,
 * internal notes).  Automatically refetches every 60 seconds.
 */
export function useReportStatus({
  token,
  channel,
  enabled = true,
}: UseReportStatusOptions) {
  return useQuery<ReportMailboxResponse, Error>({
    queryKey: reportKeys.status(token),
    queryFn: () => {
      if (channel === 'lksg') {
        return getLksgStatus(token);
      }
      return getStatus(token);
    },
    enabled: enabled && !!token,
    refetchInterval: 60_000, // Poll every 60 seconds for status updates
  });
}

// ── File Attachments ────────────────────────────────────────

interface UploadAttachmentParams {
  token: string;
  messageId: string;
  file: File;
}

/**
 * Upload a file attachment to a message.
 *
 * Invalidates the mailbox messages query on success so the
 * attachment appears in the message list.
 */
export function useUploadAttachment() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ token, messageId, file }: UploadAttachmentParams) =>
      uploadAttachment(token, messageId, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mailbox', 'messages'] });
    },
  });
}

interface DownloadAttachmentOptions {
  /** JWT session token. */
  token: string;
  /** Attachment UUID. */
  attachmentId: string;
  /** Whether the query should execute. Defaults to false (manual trigger). */
  enabled?: boolean;
}

/**
 * Download a file attachment.
 *
 * Disabled by default — call `refetch()` to trigger the download.
 * Returns a Blob that can be saved via URL.createObjectURL().
 */
export function useDownloadAttachment({
  token,
  attachmentId,
  enabled = false,
}: DownloadAttachmentOptions) {
  return useQuery<Blob, Error>({
    queryKey: reportKeys.attachment(token, attachmentId),
    queryFn: () => downloadAttachment(token, attachmentId),
    enabled,
    staleTime: Infinity, // File content doesn't change
  });
}
