/**
 * Hinweisgebersystem – Admin Tenants API Functions.
 *
 * All admin-facing API calls for multi-tenant management.  Each
 * tenant represents an organisation using the whistleblower platform,
 * with its own branding, SMTP configuration, language settings,
 * data retention periods, and report categories.
 *
 * Tenant management is a system-level operation — only SYSTEM_ADMIN
 * and TENANT_ADMIN roles have access via OIDC scopes.
 *
 * Authentication is handled automatically by the axios interceptor
 * in ``client.ts`` which attaches the OIDC Bearer token.
 */

import apiClient from '@/api/client';
import type { PaginatedResponse } from '@/api/cases';

// ── Response Types ─────────────────────────────────────────────

export interface TenantBranding {
  logo_url: string | null;
  primary_color: string | null;
  accent_color: string | null;
}

export interface TenantSMTPConfig {
  host: string;
  port: number;
  user: string;
  password: string;
  from_address: string;
  use_tls: boolean;
}

export interface TenantConfig {
  branding: TenantBranding;
  smtp: TenantSMTPConfig | null;
  languages: string[];
  default_language: string;
  retention_hinschg_years: number;
  retention_lksg_years: number;
}

export interface TenantResponse {
  id: string;
  slug: string;
  name: string;
  is_active: boolean;
  config: TenantConfig;
  version: number;
  created_at: string;
  updated_at: string;
}

export type TenantListResponse = PaginatedResponse<TenantResponse>;

// ── Category Types ─────────────────────────────────────────────

export interface CategoryResponse {
  id: string;
  tenant_id: string;
  category_key: string;
  language: string;
  label: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CategoryCreateRequest {
  category_key: string;
  label: string;
  description?: string;
  sort_order?: number;
}

export interface CategoryUpdateRequest {
  label?: string;
  description?: string;
  sort_order?: number;
  is_active?: boolean;
}

// ── i18n Types ─────────────────────────────────────────────────

export interface I18nConfigResponse {
  languages: string[];
  default_language: string;
}

export interface I18nConfigUpdateRequest {
  languages: string[];
  default_language: string;
  version: number;
}

// ── Channel Activation Types ───────────────────────────────────

export interface ChannelActivationResponse {
  hinschg_enabled: boolean;
  lksg_enabled: boolean;
}

export interface ChannelActivationUpdateRequest {
  hinschg_enabled?: boolean;
  lksg_enabled?: boolean;
  version: number;
}

// ── Email Template Types ───────────────────────────────────────

export interface EmailTemplateResponse {
  language: string;
  confirmation_subject: string;
  confirmation_body: string;
  feedback_subject: string;
  feedback_body: string;
  magic_link_subject: string;
  magic_link_body: string;
}

export interface EmailTemplateUpdateRequest {
  confirmation_subject?: string;
  confirmation_body?: string;
  feedback_subject?: string;
  feedback_body?: string;
  magic_link_subject?: string;
  magic_link_body?: string;
  version: number;
}

// ── Request Types ──────────────────────────────────────────────

export interface TenantCreateRequest {
  slug: string;
  name: string;
  config?: Partial<TenantConfig>;
}

export interface TenantUpdateRequest {
  name?: string;
  is_active?: boolean;
  config?: TenantConfig;
  version: number;
}

// ── Filter / Query Parameters ──────────────────────────────────

export interface TenantListParams {
  page?: number;
  page_size?: number;
  is_active?: boolean;
  search?: string;
}

// ── Tenants API ────────────────────────────────────────────────

/**
 * Fetch paginated tenant list with optional filters.
 *
 * Supports filtering by active status and free-text search on
 * slug and name.
 */
export async function getTenants(
  params: TenantListParams = {},
): Promise<TenantListResponse> {
  const response = await apiClient.get<TenantListResponse>(
    '/admin/tenants',
    { params },
  );
  return response.data;
}

/**
 * Get a single tenant's full detail including configuration.
 *
 * Returns the complete tenant record with branding, SMTP config,
 * language settings, retention periods, and version number for
 * optimistic locking.
 */
export async function getTenant(tenantId: string): Promise<TenantResponse> {
  const response = await apiClient.get<TenantResponse>(
    `/admin/tenants/${tenantId}`,
  );
  return response.data;
}

/**
 * Create a new tenant with DEK generation and default categories.
 *
 * A fresh Data Encryption Key (DEK) is generated server-side.
 * Default report categories are seeded for all enabled languages.
 */
export async function createTenant(
  data: TenantCreateRequest,
): Promise<TenantResponse> {
  const response = await apiClient.post<TenantResponse>(
    '/admin/tenants',
    data,
  );
  return response.data;
}

/**
 * Update tenant metadata with optimistic locking.
 *
 * Supports updating the organisation name, active status, and full
 * configuration (branding, SMTP, languages, retention).  The
 * ``version`` field must match the current database version.
 */
export async function updateTenant(
  tenantId: string,
  data: TenantUpdateRequest,
): Promise<TenantResponse> {
  const response = await apiClient.patch<TenantResponse>(
    `/admin/tenants/${tenantId}`,
    data,
  );
  return response.data;
}

// ── Categories API ─────────────────────────────────────────────

/**
 * List category translations for a tenant in a specific language.
 *
 * Returns all categories (or only active ones) sorted by sort order.
 */
export async function getCategories(
  tenantId: string,
  language: string,
  activeOnly = false,
): Promise<CategoryResponse[]> {
  const response = await apiClient.get<CategoryResponse[]>(
    `/admin/tenants/${tenantId}/categories/${language}`,
    { params: { active_only: activeOnly } },
  );
  return response.data;
}

/**
 * Create a new category translation for a tenant and language.
 *
 * The ``category_key`` is the machine-readable identifier shared
 * across languages.
 */
export async function createCategory(
  tenantId: string,
  language: string,
  data: CategoryCreateRequest,
): Promise<CategoryResponse> {
  const response = await apiClient.post<CategoryResponse>(
    `/admin/tenants/${tenantId}/categories/${language}`,
    data,
  );
  return response.data;
}

/**
 * Update a category translation's label, description, sort order,
 * or active status.
 */
export async function updateCategory(
  tenantId: string,
  language: string,
  categoryId: string,
  data: CategoryUpdateRequest,
): Promise<CategoryResponse> {
  const response = await apiClient.put<CategoryResponse>(
    `/admin/tenants/${tenantId}/categories/${language}/${categoryId}`,
    data,
  );
  return response.data;
}

// ── i18n API ───────────────────────────────────────────────────

/**
 * Get the language/i18n configuration for a tenant.
 */
export async function getI18nConfig(
  tenantId: string,
): Promise<I18nConfigResponse> {
  const response = await apiClient.get<I18nConfigResponse>(
    `/admin/tenants/${tenantId}/i18n`,
  );
  return response.data;
}

/**
 * Update the language/i18n configuration for a tenant.
 *
 * The default language must be included in the languages list.
 */
export async function updateI18nConfig(
  tenantId: string,
  data: I18nConfigUpdateRequest,
): Promise<TenantResponse> {
  const response = await apiClient.put<TenantResponse>(
    `/admin/tenants/${tenantId}/i18n`,
    data,
  );
  return response.data;
}

// ── Channel Activation API ─────────────────────────────────────

/**
 * Get channel activation status (HinSchG / LkSG) for a tenant.
 */
export async function getChannelActivation(
  tenantId: string,
): Promise<ChannelActivationResponse> {
  const response = await apiClient.get<ChannelActivationResponse>(
    `/admin/tenants/${tenantId}/channels`,
  );
  return response.data;
}

/**
 * Update channel activation (enable/disable HinSchG and LkSG).
 */
export async function updateChannelActivation(
  tenantId: string,
  data: ChannelActivationUpdateRequest,
): Promise<TenantResponse> {
  const response = await apiClient.put<TenantResponse>(
    `/admin/tenants/${tenantId}/channels`,
    data,
  );
  return response.data;
}

// ── Email Templates API ────────────────────────────────────────

/**
 * Get email templates for a tenant in a specific language.
 */
export async function getEmailTemplates(
  tenantId: string,
  language: string,
): Promise<EmailTemplateResponse> {
  const response = await apiClient.get<EmailTemplateResponse>(
    `/admin/tenants/${tenantId}/email-templates/${language}`,
  );
  return response.data;
}

/**
 * Update email templates for a tenant and language.
 *
 * Only provided fields will be updated — omitted fields retain
 * their current values.
 */
export async function updateEmailTemplates(
  tenantId: string,
  language: string,
  data: EmailTemplateUpdateRequest,
): Promise<EmailTemplateResponse> {
  const response = await apiClient.put<EmailTemplateResponse>(
    `/admin/tenants/${tenantId}/email-templates/${language}`,
    data,
  );
  return response.data;
}
