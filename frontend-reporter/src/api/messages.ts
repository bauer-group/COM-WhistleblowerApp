/**
 * Hinweisgebersystem - Messages API Functions.
 *
 * Reporter-facing API calls for the anonymous mailbox message system.
 * Handles fetching messages, sending new messages, and marking
 * messages as read.  Internal handler notes are filtered out
 * server-side and never reach the reporter frontend.
 */

import apiClient from '@/api/client';
import type { MessageMailboxResponse } from '@/schemas/report';

// ── Helper: Authorization header ────────────────────────────

function authHeader(token: string) {
  return { Authorization: `Bearer ${token}` };
}

// ── Messages ────────────────────────────────────────────────

/**
 * Fetch all messages for the authenticated mailbox session.
 *
 * Automatically marks unread handler/system messages as read on
 * the server side.  Internal notes (is_internal=true) are excluded
 * by the backend.
 */
export async function getMessages(
  token: string,
): Promise<MessageMailboxResponse[]> {
  const response = await apiClient.get<MessageMailboxResponse[]>(
    '/reports/mailbox/messages',
    { headers: authHeader(token) },
  );
  return response.data;
}

/**
 * Fetch all messages for a LkSG complaint mailbox session.
 */
export async function getLksgMessages(
  token: string,
): Promise<MessageMailboxResponse[]> {
  const response = await apiClient.get<MessageMailboxResponse[]>(
    '/public/complaints/mailbox/messages',
    { headers: authHeader(token) },
  );
  return response.data;
}

/**
 * Send a new message in the HinSchG mailbox.
 *
 * Content is encrypted at the ORM level (PGPString).
 * Sender is always marked as REPORTER by the backend.
 */
export async function sendMessage(
  token: string,
  content: string,
): Promise<MessageMailboxResponse> {
  const response = await apiClient.post<MessageMailboxResponse>(
    '/reports/mailbox/messages',
    { content },
    { headers: authHeader(token) },
  );
  return response.data;
}

/**
 * Send a new message in the LkSG complaint mailbox.
 */
export async function sendLksgMessage(
  token: string,
  content: string,
): Promise<MessageMailboxResponse> {
  const response = await apiClient.post<MessageMailboxResponse>(
    '/public/complaints/mailbox/messages',
    { content },
    { headers: authHeader(token) },
  );
  return response.data;
}
