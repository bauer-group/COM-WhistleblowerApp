/**
 * Hinweisgebersystem - TanStack Query Hooks for Mailbox Operations.
 *
 * Provides React Query v5 hooks for the anonymous mailbox:
 * - Fetching messages (with auto-read marking)
 * - Sending messages (with query invalidation)
 * - Sending LkSG messages
 *
 * All hooks follow TanStack Query v5 conventions:
 * - Object syntax for useQuery/useMutation
 * - queryKey as array
 * - invalidateQueries on mutation success
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  getLksgMessages,
  getMessages,
  sendLksgMessage,
  sendMessage,
} from '@/api/messages';
import type { Channel, MessageMailboxResponse } from '@/schemas/report';

// ── Query Keys ──────────────────────────────────────────────

export const mailboxKeys = {
  all: ['mailbox'] as const,
  messages: (token: string) =>
    [...mailboxKeys.all, 'messages', token] as const,
} as const;

// ── Messages ────────────────────────────────────────────────

interface UseMailboxMessagesOptions {
  /** JWT session token from mailbox login. */
  token: string;
  /** Reporting channel to route to the correct endpoint. */
  channel?: Channel;
  /** Whether the query should execute. Defaults to true. */
  enabled?: boolean;
}

/**
 * Fetch all messages for the authenticated mailbox session.
 *
 * The server automatically marks unread handler/system messages
 * as read when this endpoint is called.  Internal notes are
 * filtered out server-side.
 *
 * Polls every 30 seconds for new messages.
 */
export function useMailboxMessages({
  token,
  channel,
  enabled = true,
}: UseMailboxMessagesOptions) {
  return useQuery<MessageMailboxResponse[], Error>({
    queryKey: mailboxKeys.messages(token),
    queryFn: () => {
      if (channel === 'lksg') {
        return getLksgMessages(token);
      }
      return getMessages(token);
    },
    enabled: enabled && !!token,
    refetchInterval: 30_000, // Poll every 30 seconds for new messages
  });
}

// ── Send Message ────────────────────────────────────────────

interface SendMessageParams {
  token: string;
  content: string;
  channel?: Channel;
}

/**
 * Send a new message in the mailbox.
 *
 * Routes to the correct endpoint based on the channel (HinSchG or LkSG).
 * Invalidates the messages query on success so the new message appears
 * in the list immediately.  Also invalidates the report status query
 * in case the status changed (e.g. new communication triggers a status
 * update).
 */
export function useSendMessage() {
  const queryClient = useQueryClient();

  return useMutation<MessageMailboxResponse, Error, SendMessageParams>({
    mutationFn: ({ token, content, channel }) => {
      if (channel === 'lksg') {
        return sendLksgMessage(token, content);
      }
      return sendMessage(token, content);
    },
    onSuccess: (_data, variables) => {
      // Invalidate messages so the sent message appears immediately
      queryClient.invalidateQueries({
        queryKey: mailboxKeys.messages(variables.token),
      });
      // Also invalidate report status in case it changed
      queryClient.invalidateQueries({
        queryKey: ['report', 'status', variables.token],
      });
    },
  });
}
