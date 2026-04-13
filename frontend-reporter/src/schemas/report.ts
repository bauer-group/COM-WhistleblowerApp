/**
 * Hinweisgebersystem - Zod Validation Schemas for Report Submission.
 *
 * Mirrors the backend Pydantic schemas (ReportCreate, MailboxLoginRequest)
 * with client-side validation.  LkSG-extended fields are conditionally
 * required when channel === 'lksg'.
 */

import { z } from 'zod';

// ── Enums (mirroring backend Python enums) ──────────────────

export const Channel = {
  HINSCHG: 'hinschg',
  LKSG: 'lksg',
} as const;
export type Channel = (typeof Channel)[keyof typeof Channel];

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

export const SenderType = {
  REPORTER: 'reporter',
  HANDLER: 'handler',
  SYSTEM: 'system',
} as const;
export type SenderType = (typeof SenderType)[keyof typeof SenderType];

export const ReporterRelationship = {
  EMPLOYEE: 'employee',
  SUPPLIER: 'supplier',
  CONTRACTOR: 'contractor',
  COMMUNITY_MEMBER: 'community_member',
  NGO: 'ngo',
  OTHER: 'other',
} as const;
export type ReporterRelationship =
  (typeof ReporterRelationship)[keyof typeof ReporterRelationship];

export const SupplyChainTier = {
  OWN_OPERATIONS: 'own_operations',
  DIRECT_SUPPLIER: 'direct_supplier',
  INDIRECT_SUPPLIER: 'indirect_supplier',
  UNKNOWN: 'unknown',
} as const;
export type SupplyChainTier =
  (typeof SupplyChainTier)[keyof typeof SupplyChainTier];

export const LkSGCategory = {
  CHILD_LABOR: 'child_labor',
  FORCED_LABOR: 'forced_labor',
  DISCRIMINATION: 'discrimination',
  FREEDOM_OF_ASSOCIATION: 'freedom_of_association',
  WORKING_CONDITIONS: 'working_conditions',
  FAIR_WAGES: 'fair_wages',
  ENVIRONMENTAL_DAMAGE: 'environmental_damage',
  LAND_RIGHTS: 'land_rights',
  SECURITY_FORCES: 'security_forces',
  OTHER_HUMAN_RIGHTS: 'other_human_rights',
  OTHER_ENVIRONMENTAL: 'other_environmental',
} as const;
export type LkSGCategory = (typeof LkSGCategory)[keyof typeof LkSGCategory];

// ── Zod Schemas ─────────────────────────────────────────────

/**
 * Base report form schema with all fields.
 *
 * Conditional validation (LkSG fields, reporter identity) is applied
 * via `.superRefine()` so that the wizard steps can validate
 * incrementally while the final submission enforces all constraints.
 */
export const reportFormSchema = z
  .object({
    // ── Core fields ───────────────────────────────────────
    subject: z
      .string()
      .trim()
      .min(1, 'report.validation.subject_required')
      .max(500, 'report.validation.subject_max'),
    description: z
      .string()
      .trim()
      .min(1, 'report.validation.description_required')
      .max(50_000, 'report.validation.description_max'),
    channel: z.enum(['hinschg', 'lksg']).default('hinschg'),
    category: z.string().max(100).nullish(),
    language: z.string().max(5).default('de'),

    // ── Anonymity ─────────────────────────────────────────
    is_anonymous: z.boolean().default(true),

    // ── Reporter identity (non-anonymous only) ────────────
    reporter_name: z.string().max(255).nullish(),
    reporter_email: z.string().email('report.validation.email_invalid').max(255).nullish(),
    reporter_phone: z.string().max(50).nullish(),

    // ── Self-chosen password (optional) ───────────────────
    password: z
      .string()
      .min(10, 'report.validation.password_min')
      .max(128, 'report.validation.password_max')
      .nullish(),

    // ── LkSG-extended fields ──────────────────────────────
    country: z
      .string()
      .length(3, 'report.validation.country_code')
      .transform((v) => v.toUpperCase())
      .nullish(),
    organization: z.string().max(255).nullish(),
    supply_chain_tier: z
      .enum([
        'own_operations',
        'direct_supplier',
        'indirect_supplier',
        'unknown',
      ])
      .nullish(),
    reporter_relationship: z
      .enum([
        'employee',
        'supplier',
        'contractor',
        'community_member',
        'ngo',
        'other',
      ])
      .nullish(),
    lksg_category: z
      .enum([
        'child_labor',
        'forced_labor',
        'discrimination',
        'freedom_of_association',
        'working_conditions',
        'fair_wages',
        'environmental_damage',
        'land_rights',
        'security_forces',
        'other_human_rights',
        'other_environmental',
      ])
      .nullish(),

    // ── Bot protection ────────────────────────────────────
    captcha_token: z.string().min(1, 'Captcha is required'),
  })
  .superRefine((data, ctx) => {
    // ── Non-anonymous reports require reporter identity ──
    if (!data.is_anonymous) {
      if (!data.reporter_name?.trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'report.validation.name_required',
          path: ['reporter_name'],
        });
      }
      if (!data.reporter_email?.trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'report.validation.email_required',
          path: ['reporter_email'],
        });
      }
    }

    // ── LkSG channel requires extended fields ───────────
    if (data.channel === 'lksg') {
      if (!data.lksg_category) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'report.validation.lksg_category_required',
          path: ['lksg_category'],
        });
      }
      if (!data.country?.trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'report.validation.country_required',
          path: ['country'],
        });
      }
      if (!data.organization?.trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'report.validation.organization_required',
          path: ['organization'],
        });
      }
    }
  });

export type ReportFormData = z.infer<typeof reportFormSchema>;

/**
 * Mailbox login form schema.
 *
 * Validates the 16-character case number and passphrase/password
 * required to access the anonymous mailbox.
 */
export const mailboxLoginSchema = z.object({
  case_number: z
    .string()
    .trim()
    .length(16, 'mailbox.validation.case_number_length'),
  passphrase: z
    .string()
    .trim()
    .min(1, 'mailbox.validation.passphrase_required')
    .max(500),
});

export type MailboxLoginData = z.infer<typeof mailboxLoginSchema>;

/**
 * Magic link request schema.
 */
export const magicLinkRequestSchema = z.object({
  case_number: z
    .string()
    .trim()
    .length(16, 'mailbox.validation.case_number_length'),
  email: z.string().email('report.validation.email_invalid'),
});

export type MagicLinkRequestData = z.infer<typeof magicLinkRequestSchema>;

/**
 * Message creation schema (reporter-facing).
 */
export const messageCreateSchema = z.object({
  content: z
    .string()
    .trim()
    .min(1, 'mailbox.validation.message_required')
    .max(50_000, 'mailbox.validation.message_max'),
});

export type MessageCreateData = z.infer<typeof messageCreateSchema>;

// ── Response Types (read-only, no Zod validation needed) ────

export interface AttachmentSummary {
  id: string;
  original_filename: string;
  content_type: string;
  file_size: number;
  created_at: string;
}

export interface ReportCreateResponse {
  case_number: string;
  report_id: string;
  passphrase: string | null;
  access_token: string;
  message: string;
}

export interface MailboxLoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  case_number: string;
  channel: Channel;
  status: ReportStatus;
}

export interface MagicLinkResponse {
  message: string;
}

export interface MagicLinkVerifyResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  case_number: string;
  channel: Channel;
  status: ReportStatus;
}

export interface ReportMailboxResponse {
  case_number: string;
  channel: Channel;
  status: ReportStatus;
  category: string | null;
  language: string;
  subject: string | null;
  created_at: string;
  updated_at: string;
  country: string | null;
  organization: string | null;
  lksg_category: LkSGCategory | null;
}

export interface MessageMailboxResponse {
  id: string;
  sender_type: SenderType;
  is_read: boolean;
  created_at: string;
  content: string | null;
  attachments: AttachmentSummary[];
}

export interface ErrorResponse {
  detail: string;
  status_code: number;
  errors?: Array<{
    field?: string;
    message: string;
    code?: string;
  }>;
}
