/**
 * Hinweisgebersystem - FileUpload Component.
 *
 * Drag & drop file upload with size validation.
 * Constraints: 50 MB max per file, 10 files max per message.
 *
 * WCAG 2.1 AA compliant:
 * - Keyboard-accessible drop zone (Enter/Space to open file picker)
 * - ARIA live region for upload status announcements
 * - File list with individual remove buttons
 * - Error messages with role="alert"
 * - Responsive design (320px min width)
 */

import { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

// ── Constants ──────────────────────────────────────────────────

const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50 MB
const MAX_FILE_COUNT = 10;

// ── Types ──────────────────────────────────────────────────────

interface FileUploadProps {
  /** Currently selected files. */
  files: File[];
  /** Callback when files are added or removed. */
  onChange: (files: File[]) => void;
  /** Whether the upload zone is disabled. */
  disabled?: boolean;
  /** Error message to display. */
  error?: string;
  /** HTML id for the input element. */
  id?: string;
}

interface FileError {
  fileName: string;
  reason: string;
}

// ── Helpers ────────────────────────────────────────────────────

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── Component ─────────────────────────────────────────────────

export default function FileUpload({
  files,
  onChange,
  disabled = false,
  error,
  id = 'file-upload',
}: FileUploadProps) {
  const { t } = useTranslation('report');
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [fileErrors, setFileErrors] = useState<FileError[]>([]);

  const errorId = `${id}-error`;
  const descriptionId = `${id}-description`;

  const validateAndAddFiles = useCallback(
    (incoming: FileList | File[]) => {
      const newErrors: FileError[] = [];
      const validFiles: File[] = [];
      const remainingSlots = MAX_FILE_COUNT - files.length;

      const fileArray = Array.from(incoming);

      if (fileArray.length > remainingSlots) {
        newErrors.push({
          fileName: '',
          reason: t('upload.error_max_files', {
            max: MAX_FILE_COUNT,
            defaultValue: `Maximal ${MAX_FILE_COUNT} Dateien erlaubt.`,
          }),
        });
      }

      const filesToProcess = fileArray.slice(0, remainingSlots);

      for (const file of filesToProcess) {
        if (file.size > MAX_FILE_SIZE) {
          newErrors.push({
            fileName: file.name,
            reason: t('upload.error_file_size', {
              name: file.name,
              max: '50 MB',
              defaultValue: `"${file.name}" überschreitet die maximale Dateigröße von 50 MB.`,
            }),
          });
          continue;
        }

        // Skip duplicates by name + size
        const isDuplicate = files.some(
          (existing) =>
            existing.name === file.name && existing.size === file.size,
        );
        if (isDuplicate) {
          continue;
        }

        validFiles.push(file);
      }

      setFileErrors(newErrors);

      if (validFiles.length > 0) {
        onChange([...files, ...validFiles]);
      }
    },
    [files, onChange, t],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);

      if (disabled) return;

      const droppedFiles = e.dataTransfer.files;
      if (droppedFiles.length > 0) {
        validateAndAddFiles(droppedFiles);
      }
    },
    [disabled, validateAndAddFiles],
  );

  const handleDragOver = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      if (!disabled) {
        setIsDragOver(true);
      }
    },
    [disabled],
  );

  const handleDragLeave = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);
    },
    [],
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selectedFiles = e.target.files;
      if (selectedFiles && selectedFiles.length > 0) {
        validateAndAddFiles(selectedFiles);
      }
      // Reset the input so the same file can be selected again
      if (inputRef.current) {
        inputRef.current.value = '';
      }
    },
    [validateAndAddFiles],
  );

  const handleRemoveFile = useCallback(
    (index: number) => {
      const updated = files.filter((_, i) => i !== index);
      onChange(updated);
      setFileErrors([]);
    },
    [files, onChange],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        inputRef.current?.click();
      }
    },
    [],
  );

  const isAtLimit = files.length >= MAX_FILE_COUNT;

  return (
    <div className="w-full">
      <label
        htmlFor={id}
        className="mb-1.5 block text-sm font-medium text-neutral-700"
      >
        {t('fields.attachments', 'Dateien anhängen')}
      </label>

      {/* Drop zone */}
      <div
        role="button"
        tabIndex={disabled || isAtLimit ? -1 : 0}
        aria-describedby={`${descriptionId}${error ? ` ${errorId}` : ''}`}
        aria-disabled={disabled || isAtLimit}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onKeyDown={handleKeyDown}
        onClick={() => !disabled && !isAtLimit && inputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors ${
          disabled || isAtLimit
            ? 'cursor-not-allowed border-neutral-200 bg-neutral-50 text-neutral-400'
            : isDragOver
              ? 'border-primary bg-primary/5 text-primary'
              : 'border-neutral-300 bg-white text-neutral-600 hover:border-primary hover:bg-neutral-50'
        }`}
      >
        {/* Upload icon */}
        <svg
          className="mb-2 h-8 w-8"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
          />
        </svg>

        <span className="text-sm font-medium">
          {isDragOver
            ? t('upload.drop_here', 'Dateien hier ablegen')
            : t('upload.drag_or_click', 'Dateien hierher ziehen oder klicken')}
        </span>

        <span id={descriptionId} className="mt-1 text-xs text-neutral-500">
          {t('upload.constraints', {
            maxSize: '50 MB',
            maxCount: MAX_FILE_COUNT,
            defaultValue: `Max. 50 MB pro Datei, max. ${MAX_FILE_COUNT} Dateien`,
          })}
        </span>
      </div>

      {/* Hidden file input */}
      <input
        ref={inputRef}
        id={id}
        type="file"
        multiple
        onChange={handleInputChange}
        disabled={disabled || isAtLimit}
        className="sr-only"
        aria-hidden="true"
        tabIndex={-1}
      />

      {/* File list */}
      {files.length > 0 && (
        <ul
          className="mt-3 space-y-2"
          aria-label={t('upload.file_list', 'Ausgewählte Dateien')}
        >
          {files.map((file, index) => (
            <li
              key={`${file.name}-${file.size}-${index}`}
              className="flex items-center justify-between rounded-md border border-neutral-200 bg-neutral-50 px-3 py-2"
            >
              <div className="mr-2 min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-neutral-700">
                  {file.name}
                </p>
                <p className="text-xs text-neutral-500">
                  {formatFileSize(file.size)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => handleRemoveFile(index)}
                disabled={disabled}
                className="shrink-0 rounded p-1 text-neutral-400 transition-colors hover:bg-neutral-200 hover:text-danger focus:text-danger disabled:cursor-not-allowed disabled:opacity-50"
                aria-label={t('upload.remove_file', {
                  name: file.name,
                  defaultValue: `${file.name} entfernen`,
                })}
              >
                <svg
                  className="h-4 w-4"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* File count indicator */}
      {files.length > 0 && (
        <p className="mt-1.5 text-xs text-neutral-500" aria-live="polite">
          {t('upload.file_count', {
            count: files.length,
            max: MAX_FILE_COUNT,
            defaultValue: `${files.length} von ${MAX_FILE_COUNT} Dateien ausgewählt`,
          })}
        </p>
      )}

      {/* Validation errors from file processing */}
      {fileErrors.length > 0 && (
        <div role="alert" className="mt-2 space-y-1">
          {fileErrors.map((err, index) => (
            <p key={index} className="text-sm text-danger">
              {err.reason}
            </p>
          ))}
        </div>
      )}

      {/* External error (e.g. from form validation) */}
      {error && (
        <p id={errorId} className="mt-1.5 text-sm text-danger" role="alert">
          {t(error, error)}
        </p>
      )}
    </div>
  );
}
