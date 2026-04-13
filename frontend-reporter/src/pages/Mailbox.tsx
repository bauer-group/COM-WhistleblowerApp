/**
 * Hinweisgebersystem - Mailbox Page Component.
 *
 * Chat-like interface for the anonymous mailbox.  Displays:
 * - Report status badge
 * - Message list (chronological, auto-scrolling)
 * - Send message form with file upload
 * - Download attachment support
 *
 * Session token is received via React Router location state from
 * the login page.  No localStorage/cookies in anonymous mode.
 *
 * WCAG 2.1 AA compliant:
 * - aria-live region for new messages
 * - Semantic form with associated labels
 * - Keyboard-accessible message input and file upload
 * - Status announcements via role="status"
 * - Responsive layout (320px min width)
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';

import MessageBubble from '@/components/MessageBubble';
import StatusBadge from '@/components/StatusBadge';
import FileUpload from '@/components/FileUpload';
import { useReportStatus, useUploadAttachment, useDownloadAttachment } from '@/hooks/useReport';
import { useMailboxMessages, useSendMessage } from '@/hooks/useMailbox';
import { messageCreateSchema } from '@/schemas/report';
import type { Channel, ReportStatus } from '@/schemas/report';

// ── Types ──────────────────────────────────────────────────────

interface MailboxState {
  token: string;
  caseNumber: string;
  channel: Channel;
  status: ReportStatus;
}

// ── Component ─────────────────────────────────────────────────

export default function Mailbox() {
  const { t } = useTranslation('mailbox');
  const navigate = useNavigate();
  const location = useLocation();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [messageContent, setMessageContent] = useState('');
  const [messageError, setMessageError] = useState<string | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [showFileUpload, setShowFileUpload] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  const state = location.state as MailboxState | null;

  // Guard: no session state
  if (!state?.token) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-center">
        <h1 className="text-xl font-bold text-neutral-900">
          {t('error.no_session_title', 'Keine aktive Sitzung')}
        </h1>
        <p className="mt-2 text-neutral-600">
          {t(
            'error.no_session_text',
            'Bitte melden Sie sich erneut an, um auf Ihr Postfach zuzugreifen.',
          )}
        </p>
        <button
          type="button"
          onClick={() => navigate('/mailbox/login')}
          className="mt-6 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-dark"
        >
          {t('error.go_to_login', 'Zum Login')}
        </button>
      </div>
    );
  }

  return (
    <MailboxContent
      token={state.token}
      caseNumber={state.caseNumber}
      channel={state.channel}
      initialStatus={state.status}
      messageContent={messageContent}
      setMessageContent={setMessageContent}
      messageError={messageError}
      setMessageError={setMessageError}
      files={files}
      setFiles={setFiles}
      showFileUpload={showFileUpload}
      setShowFileUpload={setShowFileUpload}
      downloadingId={downloadingId}
      setDownloadingId={setDownloadingId}
      messagesEndRef={messagesEndRef}
    />
  );
}

// ── Inner component (after session guard) ─────────────────────

interface MailboxContentProps {
  token: string;
  caseNumber: string;
  channel: Channel;
  initialStatus: ReportStatus;
  messageContent: string;
  setMessageContent: (v: string) => void;
  messageError: string | null;
  setMessageError: (v: string | null) => void;
  files: File[];
  setFiles: (v: File[]) => void;
  showFileUpload: boolean;
  setShowFileUpload: (v: boolean) => void;
  downloadingId: string | null;
  setDownloadingId: (v: string | null) => void;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
}

function MailboxContent({
  token,
  caseNumber,
  channel,
  initialStatus,
  messageContent,
  setMessageContent,
  messageError,
  setMessageError,
  files,
  setFiles,
  showFileUpload,
  setShowFileUpload,
  downloadingId,
  setDownloadingId,
  messagesEndRef,
}: MailboxContentProps) {
  const { t } = useTranslation('mailbox');
  const navigate = useNavigate();

  // ── Data fetching ─────────────────────────────────────────

  const {
    data: reportStatus,
  } = useReportStatus({ token, channel });

  const {
    data: messages,
    isLoading: isLoadingMessages,
    error: messagesError,
  } = useMailboxMessages({ token, channel });

  const sendMessage = useSendMessage();
  const uploadAttachment = useUploadAttachment();

  const currentStatus = reportStatus?.status ?? initialStatus;

  // ── Auto-scroll to latest message ─────────────────────────

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, messagesEndRef]);

  // ── Download attachment ───────────────────────────────────

  const { refetch: triggerDownload } = useDownloadAttachment({
    token,
    attachmentId: downloadingId ?? '',
    enabled: false,
  });

  const handleDownloadAttachment = useCallback(
    async (attachmentId: string, filename: string) => {
      setDownloadingId(attachmentId);
      try {
        const result = await triggerDownload();
        if (result.data) {
          const url = URL.createObjectURL(result.data);
          const link = document.createElement('a');
          link.href = url;
          link.download = filename;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          URL.revokeObjectURL(url);
        }
      } finally {
        setDownloadingId(null);
      }
    },
    [triggerDownload, setDownloadingId],
  );

  // ── Send message ──────────────────────────────────────────

  const handleSendMessage = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setMessageError(null);

      const result = messageCreateSchema.safeParse({ content: messageContent });
      if (!result.success) {
        setMessageError(result.error.issues[0]?.message ?? 'Validation error');
        return;
      }

      try {
        const sentMessage = await sendMessage.mutateAsync({
          token,
          content: result.data.content,
          channel,
        });

        // Upload files if any
        for (const file of files) {
          await uploadAttachment.mutateAsync({
            token,
            messageId: sentMessage.id,
            file,
          });
        }

        setMessageContent('');
        setFiles([]);
        setShowFileUpload(false);
      } catch {
        setMessageError(
          t('send.error', 'Nachricht konnte nicht gesendet werden. Bitte versuchen Sie es erneut.'),
        );
      }
    },
    [
      messageContent,
      files,
      token,
      channel,
      sendMessage,
      uploadAttachment,
      setMessageContent,
      setFiles,
      setShowFileUpload,
      setMessageError,
      t,
    ],
  );

  const isSending = sendMessage.isPending || uploadAttachment.isPending;

  // ── Render ────────────────────────────────────────────────

  return (
    <div className="mx-auto flex max-w-3xl flex-col px-4 py-6 sm:px-6 lg:px-8">
      {/* Header with status */}
      <header className="mb-4 flex items-center justify-between rounded-lg border border-neutral-200 bg-white p-4">
        <div>
          <h1 className="text-lg font-bold text-neutral-900 sm:text-xl">
            {t('title', 'Sicheres Postfach')}
          </h1>
          <p className="mt-0.5 text-xs text-neutral-500">
            {t('case_number_label', 'Fallnummer')}: {caseNumber}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={currentStatus} />
          <button
            type="button"
            onClick={() => navigate('/')}
            className="rounded-lg border border-neutral-300 px-3 py-1.5 text-xs font-medium text-neutral-600 transition-colors hover:bg-neutral-50"
            aria-label={t('logout', 'Abmelden')}
          >
            {t('logout', 'Abmelden')}
          </button>
        </div>
      </header>

      {/* Messages area */}
      <div
        className="flex-1 space-y-4 overflow-y-auto rounded-lg border border-neutral-200 bg-neutral-50 p-4"
        style={{ minHeight: '300px', maxHeight: '60vh' }}
        role="log"
        aria-label={t('messages.aria_label', 'Nachrichtenverlauf')}
        aria-live="polite"
      >
        {/* Loading state */}
        {isLoadingMessages && (
          <div className="flex items-center justify-center py-8" role="status">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            <span className="ml-2 text-sm text-neutral-500">
              {t('messages.loading', 'Nachrichten werden geladen...')}
            </span>
          </div>
        )}

        {/* Error state */}
        {messagesError && (
          <div className="rounded-lg border border-danger/30 bg-danger/5 p-4" role="alert">
            <p className="text-sm text-danger">
              {t(
                'messages.error',
                'Nachrichten konnten nicht geladen werden. Die Sitzung ist möglicherweise abgelaufen.',
              )}
            </p>
            <button
              type="button"
              onClick={() => navigate('/mailbox/login')}
              className="mt-2 text-sm font-medium text-primary hover:text-primary-dark"
            >
              {t('messages.relogin', 'Erneut anmelden')}
            </button>
          </div>
        )}

        {/* Empty state */}
        {!isLoadingMessages && !messagesError && messages?.length === 0 && (
          <div className="py-8 text-center">
            <svg
              className="mx-auto h-12 w-12 text-neutral-300"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1}
                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
              />
            </svg>
            <p className="mt-3 text-sm text-neutral-500">
              {t(
                'messages.empty',
                'Noch keine Nachrichten. Senden Sie eine Nachricht oder warten Sie auf eine Rückmeldung.',
              )}
            </p>
          </div>
        )}

        {/* Message list */}
        {messages?.map((msg) => (
          <MessageBubble
            key={msg.id}
            id={msg.id}
            senderType={msg.sender_type}
            content={msg.content}
            createdAt={msg.created_at}
            isRead={msg.is_read}
            attachments={msg.attachments}
            onDownloadAttachment={handleDownloadAttachment}
          />
        ))}

        {/* Scroll anchor */}
        <div ref={messagesEndRef} />
      </div>

      {/* Send message form */}
      <form
        onSubmit={handleSendMessage}
        className="mt-4 rounded-lg border border-neutral-200 bg-white p-4"
      >
        {/* Message error */}
        {messageError && (
          <div className="mb-3 rounded-lg border border-danger/30 bg-danger/5 p-3" role="alert">
            <p className="text-sm text-danger">{t(messageError, messageError)}</p>
          </div>
        )}

        {/* File upload toggle */}
        {showFileUpload && (
          <div className="mb-3">
            <FileUpload files={files} onChange={setFiles} disabled={isSending} />
          </div>
        )}

        <div className="flex items-end gap-2">
          {/* File attachment button */}
          <button
            type="button"
            onClick={() => setShowFileUpload(!showFileUpload)}
            className="shrink-0 rounded-lg border border-neutral-300 p-2.5 text-neutral-500 transition-colors hover:bg-neutral-50 hover:text-neutral-700"
            aria-label={t('send.attach_files', 'Dateien anhängen')}
            title={t('send.attach_files', 'Dateien anhängen')}
          >
            <svg
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
              />
            </svg>
          </button>

          {/* Message input */}
          <div className="flex-1">
            <label htmlFor="message-input" className="sr-only">
              {t('send.message_label', 'Nachricht eingeben')}
            </label>
            <textarea
              id="message-input"
              value={messageContent}
              onChange={(e) => setMessageContent(e.target.value)}
              rows={2}
              maxLength={50_000}
              disabled={isSending}
              placeholder={t('send.placeholder', 'Nachricht schreiben...')}
              className="w-full resize-none rounded-lg border border-neutral-300 px-3 py-2.5 text-sm text-neutral-900 transition-colors focus:border-primary focus:ring-2 focus:ring-primary focus:ring-offset-0 disabled:cursor-not-allowed disabled:bg-neutral-100"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  if (messageContent.trim()) {
                    handleSendMessage(e);
                  }
                }
              }}
            />
          </div>

          {/* Send button */}
          <button
            type="submit"
            disabled={isSending || !messageContent.trim()}
            className="shrink-0 rounded-lg bg-primary p-2.5 text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
            aria-label={t('send.submit', 'Nachricht senden')}
            title={t('send.submit', 'Nachricht senden')}
          >
            {isSending ? (
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : (
              <svg
                className="h-5 w-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
                />
              </svg>
            )}
          </button>
        </div>

        {/* Send hint */}
        <p className="mt-1.5 text-xs text-neutral-400">
          {t('send.hint', 'Enter zum Senden, Shift+Enter für Zeilenumbruch')}
        </p>
      </form>
    </div>
  );
}
