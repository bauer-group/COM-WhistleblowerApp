/**
 * Hinweisgebersystem – TanStack Query Hooks for Admin Operations.
 *
 * Provides React Query v5 hooks (object syntax) for:
 * - Case listing with pagination, filtering, search, and sorting
 * - Case detail with messages and audit trail
 * - Case updates (status, priority, assignment)
 * - Handler messaging and internal notes
 * - Custodian identity disclosure workflow
 * - Dashboard statistics
 * - User management CRUD
 * - Tenant management CRUD
 * - Category management
 *
 * All hooks follow TanStack Query v5 conventions:
 * - Object syntax for useQuery/useMutation
 * - queryKey as array
 * - invalidateQueries on mutation success
 */

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import {
  approveDisclosure,
  createNote,
  getCase,
  getCaseAudit,
  getCases,
  getDashboardStats,
  getDisclosure,
  getPendingDisclosures,
  getReportDisclosures,
  requestDisclosure,
  revealIdentity,
  sendMessage,
  updateCase,
} from '@/api/cases';
import type {
  CaseDetailResponse,
  CaseListItem,
  CaseListParams,
  CaseListResponse,
  CaseUpdateRequest,
  DashboardStatsResponse,
  DisclosureDecisionRequest,
  DisclosureRequestCreate,
  DisclosureResponse,
  AuditLogEntry,
  IdentityRevealResponse,
  MessageResponse,
} from '@/api/cases';
import {
  getLabels,
  assignLabelToCase,
  removeLabelFromCase,
} from '@/api/labels';
import type {
  LabelListParams,
  LabelListResponse,
  LabelSummary,
} from '@/api/labels';
import {
  createUser,
  getUser,
  getUsers,
  updateUser,
} from '@/api/users';
import type {
  UserCreateRequest,
  UserListParams,
  UserListResponse,
  UserResponse,
  UserUpdateRequest,
} from '@/api/users';
import {
  createCategory,
  createTenant,
  getCategories,
  getChannelActivation,
  getEmailTemplates,
  getI18nConfig,
  getTenant,
  getTenants,
  updateCategory,
  updateChannelActivation,
  updateEmailTemplates,
  updateI18nConfig,
  updateTenant,
} from '@/api/tenants';
import type {
  CategoryCreateRequest,
  CategoryResponse,
  CategoryUpdateRequest,
  ChannelActivationUpdateRequest,
  EmailTemplateUpdateRequest,
  I18nConfigUpdateRequest,
  TenantCreateRequest,
  TenantListParams,
  TenantListResponse,
  TenantResponse,
  TenantUpdateRequest,
} from '@/api/tenants';

// ── Query Keys ──────────────────────────────────────────────────

export const caseKeys = {
  all: ['cases'] as const,
  lists: () => [...caseKeys.all, 'list'] as const,
  list: (params: CaseListParams) =>
    [...caseKeys.lists(), params] as const,
  details: () => [...caseKeys.all, 'detail'] as const,
  detail: (id: string) => [...caseKeys.details(), id] as const,
  audit: (id: string) => [...caseKeys.all, 'audit', id] as const,
  disclosures: (reportId: string) =>
    [...caseKeys.all, 'disclosures', reportId] as const,
} as const;

export const dashboardKeys = {
  all: ['dashboard'] as const,
  stats: () => [...dashboardKeys.all, 'stats'] as const,
} as const;

export const disclosureKeys = {
  all: ['disclosures'] as const,
  pending: () => [...disclosureKeys.all, 'pending'] as const,
  detail: (id: string) => [...disclosureKeys.all, 'detail', id] as const,
} as const;

export const userKeys = {
  all: ['users'] as const,
  lists: () => [...userKeys.all, 'list'] as const,
  list: (params: UserListParams) =>
    [...userKeys.lists(), params] as const,
  detail: (id: string) => [...userKeys.all, 'detail', id] as const,
} as const;

export const tenantKeys = {
  all: ['tenants'] as const,
  lists: () => [...tenantKeys.all, 'list'] as const,
  list: (params: TenantListParams) =>
    [...tenantKeys.lists(), params] as const,
  detail: (id: string) => [...tenantKeys.all, 'detail', id] as const,
  categories: (tenantId: string, language: string) =>
    [...tenantKeys.all, 'categories', tenantId, language] as const,
  i18n: (tenantId: string) =>
    [...tenantKeys.all, 'i18n', tenantId] as const,
  channels: (tenantId: string) =>
    [...tenantKeys.all, 'channels', tenantId] as const,
  emailTemplates: (tenantId: string, language: string) =>
    [...tenantKeys.all, 'email-templates', tenantId, language] as const,
} as const;

// ── Case List (Paginated with Filters) ──────────────────────────

interface UseCasesOptions {
  /** Query parameters for filtering, pagination, search, and sorting. */
  params?: CaseListParams;
  /** Whether the query should execute. Defaults to true. */
  enabled?: boolean;
}

/**
 * Fetch paginated case list with filters, search, and sorting.
 *
 * Uses ``keepPreviousData`` for smooth pagination transitions.
 * Automatically refetches every 30 seconds for near-real-time
 * dashboard updates.
 */
export function useCases({ params = {}, enabled = true }: UseCasesOptions = {}) {
  return useQuery<CaseListResponse, Error>({
    queryKey: caseKeys.list(params),
    queryFn: () => getCases(params),
    enabled,
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
}

// ── Case Detail ─────────────────────────────────────────────────

interface UseCaseDetailOptions {
  /** Case UUID. */
  caseId: string;
  /** Whether the query should execute. Defaults to true. */
  enabled?: boolean;
}

/**
 * Fetch full case detail with messages and audit trail.
 *
 * Returns the complete case record with decrypted fields, all
 * messages (including internal handler notes), and the chronological
 * audit trail.  Refetches every 15 seconds for live message updates.
 */
export function useCaseDetail({
  caseId,
  enabled = true,
}: UseCaseDetailOptions) {
  return useQuery<CaseDetailResponse, Error>({
    queryKey: caseKeys.detail(caseId),
    queryFn: () => getCase(caseId),
    enabled: enabled && !!caseId,
    refetchInterval: 15_000,
  });
}

// ── Case Audit Trail ────────────────────────────────────────────

interface UseCaseAuditOptions {
  /** Case UUID. */
  caseId: string;
  /** Whether the query should execute. Defaults to true. */
  enabled?: boolean;
}

/**
 * Fetch the audit trail for a specific case.
 */
export function useCaseAudit({
  caseId,
  enabled = true,
}: UseCaseAuditOptions) {
  return useQuery<AuditLogEntry[], Error>({
    queryKey: caseKeys.audit(caseId),
    queryFn: () => getCaseAudit(caseId),
    enabled: enabled && !!caseId,
  });
}

// ── Case Update ─────────────────────────────────────────────────

interface UpdateCaseParams {
  caseId: string;
  data: CaseUpdateRequest;
}

/**
 * Update case metadata (status, priority, assignment, category).
 *
 * On success, invalidates the case detail and list queries so
 * the UI reflects the changes immediately.
 */
export function useUpdateCase() {
  const queryClient = useQueryClient();

  return useMutation<CaseListItem, Error, UpdateCaseParams>({
    mutationFn: ({ caseId, data }) => updateCase(caseId, data),
    onSuccess: (_data, { caseId }) => {
      queryClient.invalidateQueries({ queryKey: caseKeys.detail(caseId) });
      queryClient.invalidateQueries({ queryKey: caseKeys.lists() });
      queryClient.invalidateQueries({ queryKey: dashboardKeys.stats() });
    },
  });
}

// ── Send Message to Reporter ────────────────────────────────────

interface SendMessageParams {
  caseId: string;
  content: string;
}

/**
 * Send a message to the reporter visible in the anonymous mailbox.
 *
 * Invalidates the case detail query on success so the new message
 * appears in the timeline.
 */
export function useSendMessage() {
  const queryClient = useQueryClient();

  return useMutation<MessageResponse, Error, SendMessageParams>({
    mutationFn: ({ caseId, content }) => sendMessage(caseId, content),
    onSuccess: (_data, { caseId }) => {
      queryClient.invalidateQueries({ queryKey: caseKeys.detail(caseId) });
    },
  });
}

// ── Create Internal Note ────────────────────────────────────────

interface CreateNoteParams {
  caseId: string;
  content: string;
}

/**
 * Create an internal note visible only to handlers.
 *
 * Invalidates the case detail query on success so the new note
 * appears in the timeline.
 */
export function useCreateNote() {
  const queryClient = useQueryClient();

  return useMutation<MessageResponse, Error, CreateNoteParams>({
    mutationFn: ({ caseId, content }) => createNote(caseId, content),
    onSuccess: (_data, { caseId }) => {
      queryClient.invalidateQueries({ queryKey: caseKeys.detail(caseId) });
    },
  });
}

// ── Dashboard Statistics ────────────────────────────────────────

interface UseDashboardStatsOptions {
  /** Whether the query should execute. Defaults to true. */
  enabled?: boolean;
}

/**
 * Fetch KPI dashboard statistics.
 *
 * Returns case counts by status, channel, priority, overdue count,
 * average resolution time, and monthly trend data.  Automatically
 * refetches every 60 seconds.
 */
export function useDashboardStats({
  enabled = true,
}: UseDashboardStatsOptions = {}) {
  return useQuery<DashboardStatsResponse, Error>({
    queryKey: dashboardKeys.stats(),
    queryFn: getDashboardStats,
    enabled,
    refetchInterval: 60_000,
  });
}

// ── Custodian / Identity Disclosure ─────────────────────────────

/**
 * Request identity disclosure for an anonymous report.
 *
 * Invalidates the case detail and pending disclosures queries.
 */
export function useRequestDisclosure() {
  const queryClient = useQueryClient();

  return useMutation<DisclosureResponse, Error, DisclosureRequestCreate>({
    mutationFn: requestDisclosure,
    onSuccess: (data) => {
      queryClient.invalidateQueries({
        queryKey: caseKeys.disclosures(data.report_id),
      });
      queryClient.invalidateQueries({
        queryKey: disclosureKeys.pending(),
      });
    },
  });
}

interface ApproveDisclosureParams {
  disclosureId: string;
  data: DisclosureDecisionRequest;
}

/**
 * Approve or reject a pending disclosure request.
 *
 * Invalidates disclosure-related queries on success.
 */
export function useApproveDisclosure() {
  const queryClient = useQueryClient();

  return useMutation<DisclosureResponse, Error, ApproveDisclosureParams>({
    mutationFn: ({ disclosureId, data }) =>
      approveDisclosure(disclosureId, data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({
        queryKey: disclosureKeys.pending(),
      });
      queryClient.invalidateQueries({
        queryKey: disclosureKeys.detail(data.id),
      });
      queryClient.invalidateQueries({
        queryKey: caseKeys.disclosures(data.report_id),
      });
    },
  });
}

/**
 * Fetch all pending disclosure requests for the tenant.
 */
export function usePendingDisclosures(enabled = true) {
  return useQuery<DisclosureResponse[], Error>({
    queryKey: disclosureKeys.pending(),
    queryFn: getPendingDisclosures,
    enabled,
    refetchInterval: 30_000,
  });
}

/**
 * Fetch a single disclosure request by ID.
 */
export function useDisclosure(disclosureId: string, enabled = true) {
  return useQuery<DisclosureResponse, Error>({
    queryKey: disclosureKeys.detail(disclosureId),
    queryFn: () => getDisclosure(disclosureId),
    enabled: enabled && !!disclosureId,
  });
}

/**
 * Fetch all disclosure requests for a specific report.
 */
export function useReportDisclosures(reportId: string, enabled = true) {
  return useQuery<DisclosureResponse[], Error>({
    queryKey: caseKeys.disclosures(reportId),
    queryFn: () => getReportDisclosures(reportId),
    enabled: enabled && !!reportId,
  });
}

/**
 * Reveal the sealed reporter identity after approved disclosure.
 *
 * Invalidates disclosure queries on success.
 */
export function useRevealIdentity() {
  const queryClient = useQueryClient();

  return useMutation<IdentityRevealResponse, Error, string>({
    mutationFn: revealIdentity,
    onSuccess: (data) => {
      queryClient.invalidateQueries({
        queryKey: disclosureKeys.detail(data.disclosure_id),
      });
    },
  });
}

// ── User Management ─────────────────────────────────────────────

interface UseUsersOptions {
  /** Query parameters for filtering and pagination. */
  params?: UserListParams;
  /** Whether the query should execute. Defaults to true. */
  enabled?: boolean;
}

/**
 * Fetch paginated user list with filters.
 *
 * Supports filtering by role, active status, custodian status,
 * and free-text search.  Uses ``keepPreviousData`` for smooth
 * pagination transitions.
 */
export function useUsers({ params = {}, enabled = true }: UseUsersOptions = {}) {
  return useQuery<UserListResponse, Error>({
    queryKey: userKeys.list(params),
    queryFn: () => getUsers(params),
    enabled,
    placeholderData: keepPreviousData,
  });
}

/**
 * Fetch a single user by ID.
 */
export function useUser(userId: string, enabled = true) {
  return useQuery<UserResponse, Error>({
    queryKey: userKeys.detail(userId),
    queryFn: () => getUser(userId),
    enabled: enabled && !!userId,
  });
}

/**
 * Create a new backend user.
 *
 * Invalidates the user list query on success.
 */
export function useCreateUser() {
  const queryClient = useQueryClient();

  return useMutation<UserResponse, Error, UserCreateRequest>({
    mutationFn: createUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: userKeys.lists() });
    },
  });
}

interface UpdateUserParams {
  userId: string;
  data: UserUpdateRequest;
}

/**
 * Update a user's role, status, or custodian capability.
 *
 * Invalidates both the user detail and list queries on success.
 */
export function useUpdateUser() {
  const queryClient = useQueryClient();

  return useMutation<UserResponse, Error, UpdateUserParams>({
    mutationFn: ({ userId, data }) => updateUser(userId, data),
    onSuccess: (_data, { userId }) => {
      queryClient.invalidateQueries({ queryKey: userKeys.detail(userId) });
      queryClient.invalidateQueries({ queryKey: userKeys.lists() });
    },
  });
}

// ── Tenant Management ───────────────────────────────────────────

interface UseTenantsOptions {
  /** Query parameters for filtering and pagination. */
  params?: TenantListParams;
  /** Whether the query should execute. Defaults to true. */
  enabled?: boolean;
}

/**
 * Fetch paginated tenant list with filters.
 *
 * Uses ``keepPreviousData`` for smooth pagination transitions.
 */
export function useTenants({
  params = {},
  enabled = true,
}: UseTenantsOptions = {}) {
  return useQuery<TenantListResponse, Error>({
    queryKey: tenantKeys.list(params),
    queryFn: () => getTenants(params),
    enabled,
    placeholderData: keepPreviousData,
  });
}

/**
 * Fetch a single tenant by ID.
 */
export function useTenant(tenantId: string, enabled = true) {
  return useQuery<TenantResponse, Error>({
    queryKey: tenantKeys.detail(tenantId),
    queryFn: () => getTenant(tenantId),
    enabled: enabled && !!tenantId,
  });
}

/**
 * Create a new tenant.
 *
 * Invalidates the tenant list query on success.
 */
export function useCreateTenant() {
  const queryClient = useQueryClient();

  return useMutation<TenantResponse, Error, TenantCreateRequest>({
    mutationFn: createTenant,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: tenantKeys.lists() });
    },
  });
}

interface UpdateTenantParams {
  tenantId: string;
  data: TenantUpdateRequest;
}

/**
 * Update a tenant's metadata or configuration.
 *
 * Invalidates both the tenant detail and list queries on success.
 */
export function useUpdateTenant() {
  const queryClient = useQueryClient();

  return useMutation<TenantResponse, Error, UpdateTenantParams>({
    mutationFn: ({ tenantId, data }) => updateTenant(tenantId, data),
    onSuccess: (_data, { tenantId }) => {
      queryClient.invalidateQueries({
        queryKey: tenantKeys.detail(tenantId),
      });
      queryClient.invalidateQueries({ queryKey: tenantKeys.lists() });
    },
  });
}

// ── Category Management ─────────────────────────────────────────

interface UseCategoriesOptions {
  tenantId: string;
  language: string;
  activeOnly?: boolean;
  enabled?: boolean;
}

/**
 * Fetch category translations for a tenant in a specific language.
 */
export function useCategories({
  tenantId,
  language,
  activeOnly = false,
  enabled = true,
}: UseCategoriesOptions) {
  return useQuery<CategoryResponse[], Error>({
    queryKey: tenantKeys.categories(tenantId, language),
    queryFn: () => getCategories(tenantId, language, activeOnly),
    enabled: enabled && !!tenantId && !!language,
  });
}

interface CreateCategoryParams {
  tenantId: string;
  language: string;
  data: CategoryCreateRequest;
}

/**
 * Create a new category translation.
 *
 * Invalidates the category list query on success.
 */
export function useCreateCategory() {
  const queryClient = useQueryClient();

  return useMutation<CategoryResponse, Error, CreateCategoryParams>({
    mutationFn: ({ tenantId, language, data }) =>
      createCategory(tenantId, language, data),
    onSuccess: (_data, { tenantId, language }) => {
      queryClient.invalidateQueries({
        queryKey: tenantKeys.categories(tenantId, language),
      });
    },
  });
}

interface UpdateCategoryParams {
  tenantId: string;
  language: string;
  categoryId: string;
  data: CategoryUpdateRequest;
}

/**
 * Update a category translation.
 *
 * Invalidates the category list query on success.
 */
export function useUpdateCategory() {
  const queryClient = useQueryClient();

  return useMutation<CategoryResponse, Error, UpdateCategoryParams>({
    mutationFn: ({ tenantId, language, categoryId, data }) =>
      updateCategory(tenantId, language, categoryId, data),
    onSuccess: (_data, { tenantId, language }) => {
      queryClient.invalidateQueries({
        queryKey: tenantKeys.categories(tenantId, language),
      });
    },
  });
}

// ── i18n Configuration ──────────────────────────────────────────

/**
 * Fetch the i18n configuration for a tenant.
 */
export function useI18nConfig(tenantId: string, enabled = true) {
  return useQuery({
    queryKey: tenantKeys.i18n(tenantId),
    queryFn: () => getI18nConfig(tenantId),
    enabled: enabled && !!tenantId,
  });
}

interface UpdateI18nConfigParams {
  tenantId: string;
  data: I18nConfigUpdateRequest;
}

/**
 * Update the i18n configuration for a tenant.
 *
 * Invalidates both the i18n config and tenant detail queries.
 */
export function useUpdateI18nConfig() {
  const queryClient = useQueryClient();

  return useMutation<TenantResponse, Error, UpdateI18nConfigParams>({
    mutationFn: ({ tenantId, data }) => updateI18nConfig(tenantId, data),
    onSuccess: (_data, { tenantId }) => {
      queryClient.invalidateQueries({
        queryKey: tenantKeys.i18n(tenantId),
      });
      queryClient.invalidateQueries({
        queryKey: tenantKeys.detail(tenantId),
      });
    },
  });
}

// ── Channel Activation ──────────────────────────────────────────

/**
 * Fetch channel activation status for a tenant.
 */
export function useChannelActivation(tenantId: string, enabled = true) {
  return useQuery({
    queryKey: tenantKeys.channels(tenantId),
    queryFn: () => getChannelActivation(tenantId),
    enabled: enabled && !!tenantId,
  });
}

interface UpdateChannelActivationParams {
  tenantId: string;
  data: ChannelActivationUpdateRequest;
}

/**
 * Update channel activation for a tenant.
 *
 * Invalidates both the channel activation and tenant detail queries.
 */
export function useUpdateChannelActivation() {
  const queryClient = useQueryClient();

  return useMutation<TenantResponse, Error, UpdateChannelActivationParams>({
    mutationFn: ({ tenantId, data }) =>
      updateChannelActivation(tenantId, data),
    onSuccess: (_data, { tenantId }) => {
      queryClient.invalidateQueries({
        queryKey: tenantKeys.channels(tenantId),
      });
      queryClient.invalidateQueries({
        queryKey: tenantKeys.detail(tenantId),
      });
    },
  });
}

// ── Email Templates ─────────────────────────────────────────────

interface UseEmailTemplatesOptions {
  tenantId: string;
  language: string;
  enabled?: boolean;
}

/**
 * Fetch email templates for a tenant in a specific language.
 */
export function useEmailTemplates({
  tenantId,
  language,
  enabled = true,
}: UseEmailTemplatesOptions) {
  return useQuery({
    queryKey: tenantKeys.emailTemplates(tenantId, language),
    queryFn: () => getEmailTemplates(tenantId, language),
    enabled: enabled && !!tenantId && !!language,
  });
}

interface UpdateEmailTemplatesParams {
  tenantId: string;
  language: string;
  data: EmailTemplateUpdateRequest;
}

/**
 * Update email templates for a tenant and language.
 *
 * Invalidates the email template query on success.
 */
export function useUpdateEmailTemplates() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ tenantId, language, data }: UpdateEmailTemplatesParams) =>
      updateEmailTemplates(tenantId, language, data),
    onSuccess: (_data: unknown, { tenantId, language }: UpdateEmailTemplatesParams) => {
      queryClient.invalidateQueries({
        queryKey: tenantKeys.emailTemplates(tenantId, language),
      });
    },
  });
}

// ── Labels ─────────────────────────────────────────────────────

export const labelKeys = {
  all: ['labels'] as const,
  lists: () => [...labelKeys.all, 'list'] as const,
  list: (params: LabelListParams) =>
    [...labelKeys.lists(), params] as const,
} as const;

interface UseLabelsOptions {
  /** Query parameters for filtering and pagination. */
  params?: LabelListParams;
  /** Whether the query should execute. Defaults to true. */
  enabled?: boolean;
}

/**
 * Fetch paginated label list for the current tenant.
 *
 * Supports filtering to active-only labels (for assignment
 * dropdowns) and pagination.
 */
export function useLabels({
  params = {},
  enabled = true,
}: UseLabelsOptions = {}) {
  return useQuery<LabelListResponse, Error>({
    queryKey: labelKeys.list(params),
    queryFn: () => getLabels(params),
    enabled,
  });
}

// ── Label Assignment ───────────────────────────────────────────

interface AssignLabelParams {
  caseId: string;
  labelId: string;
}

/**
 * Assign a label to a case.
 *
 * Invalidates the case detail and list queries on success so the
 * label assignment is reflected immediately.
 */
export function useAssignLabel() {
  const queryClient = useQueryClient();

  return useMutation<LabelSummary[], Error, AssignLabelParams>({
    mutationFn: ({ caseId, labelId }) => assignLabelToCase(caseId, labelId),
    onSuccess: (_data, { caseId }) => {
      queryClient.invalidateQueries({ queryKey: caseKeys.detail(caseId) });
      queryClient.invalidateQueries({ queryKey: caseKeys.lists() });
    },
  });
}

interface RemoveLabelParams {
  caseId: string;
  labelId: string;
}

/**
 * Remove a label from a case.
 *
 * Invalidates the case detail and list queries on success so the
 * label removal is reflected immediately.
 */
export function useRemoveLabel() {
  const queryClient = useQueryClient();

  return useMutation<LabelSummary[], Error, RemoveLabelParams>({
    mutationFn: ({ caseId, labelId }) => removeLabelFromCase(caseId, labelId),
    onSuccess: (_data, { caseId }) => {
      queryClient.invalidateQueries({ queryKey: caseKeys.detail(caseId) });
      queryClient.invalidateQueries({ queryKey: caseKeys.lists() });
    },
  });
}
