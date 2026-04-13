/**
 * Hinweisgebersystem - MessageBubble Component.
 *
 * Chat-style message display for the anonymous mailbox.
 * Shows sender type (reporter/handler/system), timestamp,
 * message content, and file attachment links.
 *
 * WCAG 2.1 AA compliant:
 * - Semantic <article> element per message
 * - aria-label with sender and timestamp context
 * - Attachment links are keyboard-accessible
 * - Responsive layout (320px min width)
 */

import { useTranslation } from 'react-i18next';

import type { AttachmentSummary, SenderType } from '@/schemas/report';

// ── Types ──────────────────────────────────────────────────────

interface MessageBubbleProps {
  /** Unique message id. */
  id: string;
  /** Who sent the message. */
  senderType: SenderType;
  /** Message body (may be null for attachment-only messages). */
  content: string | null;
  /** ISO 8601 timestamp. */
  createdAt: string;
  /** Whether the message has been read by the recipient. */
  isRead: boolean;
  /** Attached files. */
  attachments: AttachmentSummary[];
  /** Callback when an attachment is clicked for download. */
  onDownloadAttachment?: (attachmentId: string, filename: string) => void;
}

// ── Helpers ────────────────────────────────────────────────────

function formatTimestamp(iso: string, locale: string): string {
  try {
    const date = new Date(iso);
    return new Intl.DateTimeFormat(locale, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(date);
  } catch {
    return iso;
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const senderStyles: Record<SenderType, { bubble: string; align: string }> = {
  reporter: {
    bubble: 'bg-primary text-white',
    align: 'justify-end',
  },
  handler: {
    bubble: 'bg-neutral-100 text-neutral-900 border border-neutral-200',
    align: 'justify-start',
  },
  system: {
    bubble: 'bg-warning/10 text-neutral-800 border border-warning/30',
    align: 'justify-center',
  },
};

const senderLabelKeys: Record<SenderType, string> = {
  reporter: 'mailbox.sender.reporter',
  handler: 'mailbox.sender.handler',
  system: 'mailbox.sender.system',
};

// ── Component ─────────────────────────────────────────────────

export default function MessageBubble({
  id,
  senderType,
  content,
  createdAt,
  isRead,
  attachments,
  onDownloadAttachment,
}: MessageBubbleProps) {
  const { t, i18n } = useTranslation('mailbox');
  const styles = senderStyles[senderType];
  const senderLabel = t(senderLabelKeys[senderType], senderType);
  const formattedTime = formatTimestamp(createdAt, i18n.language);

  return (
    <article
      id={`message-${id}`}
      className={`flex w-full ${styles.align}`}
      aria-label={t('message.aria_label', {
        sender: senderLabel,
        time: formattedTime,
        defaultValue: `Nachricht von ${senderLabel} um ${formattedTime}`,
      })}
    >
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 sm:max-w-[70%] ${styles.bubble}`}
      >
        {/* Sender label and timestamp header */}
        <div className="mb-1 flex items-center gap-2 text-xs opacity-75">
          <span className="font-medium">{senderLabel}</span>
          <time dateTime={createdAt} className="whitespace-nowrap">
            {formattedTime}
          </time>
          {!isRead && senderType !== 'reporter' && (
            <span
              className="inline-block h-2 w-2 rounded-full bg-primary-light"
              aria-label={t('message.unread', 'Ungelesen')}
              title={t('message.unread', 'Ungelesen')}
            />
          )}
        </div>

        {/* Message content */}
        {content && (
          <p className="whitespace-pre-wrap break-words text-sm">{content}</p>
        )}

        {/* Attachments */}
        {attachments.length > 0 && (
          <div className="mt-2 space-y-1">
            {attachments.map((attachment) => (
              <button
                key={attachment.id}
                type="button"
                onClick={() =>
                  onDownloadAttachment?.(
                    attachment.id,
                    attachment.original_filename,
                  )
                }
                className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors ${
                  senderType === 'reporter'
                    ? 'bg-white/15 hover:bg-white/25'
                    : 'bg-neutral-200/50 hover:bg-neutral-200'
                }`}
                aria-label={t('message.download_attachment', {
                  name: attachment.original_filename,
                  defaultValue: `${attachment.original_filename} herunterladen`,
                })}
              >
                {/* File icon */}
                <svg
                  className="h-4 w-4 shrink-0"
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
                <span className="min-w-0 flex-1 truncate">
                  {attachment.original_filename}
                </span>
                <span className="shrink-0 text-[10px] opacity-60">
                  {formatFileSize(attachment.file_size)}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}
