/**
 * Hinweisgebersystem – Settings Page.
 *
 * Tenant-specific configuration management with tabbed interface:
 * - Branding: Logo URL, primary/accent colors
 * - SMTP: Email server configuration for notifications
 * - Languages: Available languages and default language
 * - Channels: HinSchG/LkSG channel activation
 * - Retention: Data retention periods per channel
 * - Email Templates: Notification template editing per language
 * - Labels: Report label CRUD management
 * - Sub-Statuses: Configurable refinements per lifecycle status
 * - Two-Factor: TOTP 2FA setup and management
 * - PGP Keys: PGP public key upload for encrypted email notifications
 *
 * All settings use optimistic locking (version field) to prevent
 * concurrent modification conflicts.
 *
 * Requires tenant_admin role. Data is fetched via TanStack Query hooks.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  useTenant,
  useUpdateTenant,
  useChannelActivation,
  useUpdateChannelActivation,
  useEmailTemplates,
  useUpdateEmailTemplates,
} from '@/hooks/useCases';
import { useAuth } from '@/hooks/useAuth';
import apiClient from '@/api/client';
import LabelManager from '@/components/LabelManager';
import SubStatusManager from '@/components/SubStatusManager';
import TwoFactorSetup from '@/components/TwoFactorSetup';
import type {
  TenantConfig,
  TenantBranding,
  TenantSMTPConfig,
  TenantUpdateRequest,
  ChannelActivationUpdateRequest,
  EmailTemplateUpdateRequest,
} from '@/api/tenants';

// ── Types ─────────────────────────────────────────────────────

type SettingsTab = 'branding' | 'smtp' | 'languages' | 'channels' | 'retention' | 'email_templates' | 'labels' | 'sub_statuses' | 'two_factor' | 'pgp_keys';

const TAB_KEYS: SettingsTab[] = ['branding', 'smtp', 'languages', 'channels', 'retention', 'email_templates', 'labels', 'sub_statuses', 'two_factor', 'pgp_keys'];

interface PGPKeyResponse {
  fingerprint: string;
  expires_at: string | null;
  user_ids: string[];
  message: string;
}

interface PGPKeyDeleteResponse {
  message: string;
}

const DEFAULT_SMTP: TenantSMTPConfig = {
  host: '',
  port: 587,
  user: '',
  password: '',
  from_address: '',
  use_tls: true,
};

// ── Success Banner ────────────────────────────────────────────

function SuccessBanner({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, 4000);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  return (
    <div className="mb-4 flex items-center justify-between rounded-md border border-success/20 bg-success/5 px-4 py-3 text-sm text-success">
      <span>{message}</span>
      <button
        type="button"
        onClick={onDismiss}
        className="text-success/70 transition-colors hover:text-success"
        aria-label="Close"
      >
        &times;
      </button>
    </div>
  );
}

// ── Settings Page ─────────────────────────────────────────────

export default function Settings() {
  const { t } = useTranslation('admin');
  const { user } = useAuth();
  const tenantId = user?.tenantId ?? '';

  // ── State ───────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<SettingsTab>('branding');
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [emailTemplateLang, setEmailTemplateLang] = useState('de');

  // ── Branding State ──────────────────────────────────────────
  const [branding, setBranding] = useState<TenantBranding>({
    logo_url: null,
    primary_color: null,
    accent_color: null,
  });

  // ── SMTP State ──────────────────────────────────────────────
  const [smtp, setSmtp] = useState<TenantSMTPConfig>({ ...DEFAULT_SMTP });

  // ── Language State ──────────────────────────────────────────
  const [languages, setLanguages] = useState<string[]>(['de']);
  const [defaultLanguage, setDefaultLanguage] = useState('de');

  // ── Retention State ─────────────────────────────────────────
  const [retentionHinschg, setRetentionHinschg] = useState(3);
  const [retentionLksg, setRetentionLksg] = useState(5);

  // ── Channel State ───────────────────────────────────────────
  const [hinschgEnabled, setHinschgEnabled] = useState(true);
  const [lksgEnabled, setLksgEnabled] = useState(false);

  // ── Two-Factor State ─────────────────────────────────────────
  const [twoFactorEnabled, setTwoFactorEnabled] = useState(user?.totp_enabled ?? false);

  // ── PGP Key State ───────────────────────────────────────────
  const [pgpKeyText, setPgpKeyText] = useState('');
  const [pgpFingerprint, setPgpFingerprint] = useState<string | null>(null);
  const [pgpExpiresAt, setPgpExpiresAt] = useState<string | null>(null);
  const [pgpUserIds, setPgpUserIds] = useState<string[]>([]);
  const [pgpLoading, setPgpLoading] = useState(false);
  const [pgpFetching, setPgpFetching] = useState(false);
  const pgpFileInputRef = useRef<HTMLInputElement>(null);

  // ── Email Template State ────────────────────────────────────
  const [emailTemplateData, setEmailTemplateData] = useState({
    confirmation_subject: '',
    confirmation_body: '',
    feedback_subject: '',
    feedback_body: '',
    magic_link_subject: '',
    magic_link_body: '',
  });

  // ── Queries ─────────────────────────────────────────────────
  const { data: tenant, isLoading: tenantLoading, error: tenantError } = useTenant(tenantId, !!tenantId);
  const { data: channelData } = useChannelActivation(tenantId, !!tenantId);
  const { data: emailTemplateRemote } = useEmailTemplates({
    tenantId,
    language: emailTemplateLang,
    enabled: !!tenantId && activeTab === 'email_templates',
  });

  const updateTenantMutation = useUpdateTenant();
  const updateChannelMutation = useUpdateChannelActivation();
  const updateEmailTemplateMutation = useUpdateEmailTemplates();

  // ── Sync state from queries ─────────────────────────────────
  useEffect(() => {
    if (tenant?.config) {
      setBranding({ ...tenant.config.branding });
      if (tenant.config.smtp) {
        setSmtp({ ...tenant.config.smtp });
      }
      setLanguages([...tenant.config.languages]);
      setDefaultLanguage(tenant.config.default_language);
      setRetentionHinschg(tenant.config.retention_hinschg_years);
      setRetentionLksg(tenant.config.retention_lksg_years);
    }
  }, [tenant]);

  useEffect(() => {
    if (channelData) {
      setHinschgEnabled(channelData.hinschg_enabled);
      setLksgEnabled(channelData.lksg_enabled);
    }
  }, [channelData]);

  useEffect(() => {
    if (emailTemplateRemote) {
      setEmailTemplateData({
        confirmation_subject: emailTemplateRemote.confirmation_subject,
        confirmation_body: emailTemplateRemote.confirmation_body,
        feedback_subject: emailTemplateRemote.feedback_subject,
        feedback_body: emailTemplateRemote.feedback_body,
        magic_link_subject: emailTemplateRemote.magic_link_subject,
        magic_link_body: emailTemplateRemote.magic_link_body,
      });
    }
  }, [emailTemplateRemote]);

  useEffect(() => {
    if (user?.totp_enabled !== undefined) {
      setTwoFactorEnabled(user.totp_enabled);
    }
  }, [user?.totp_enabled]);

  // ── Fetch PGP key status on tab activation ──────────────────
  useEffect(() => {
    if (activeTab !== 'pgp_keys' || !user?.id) return;

    let cancelled = false;
    setPgpFetching(true);

    apiClient
      .get<{ pgp_fingerprint: string | null; pgp_key_expires_at: string | null }>(`/admin/users/${user.id}`)
      .then((res) => {
        if (cancelled) return;
        const data = res.data;
        setPgpFingerprint(data.pgp_fingerprint ?? null);
        setPgpExpiresAt(data.pgp_key_expires_at ?? null);
      })
      .catch(() => {
        // Silently ignore — fingerprint remains null
      })
      .finally(() => {
        if (!cancelled) setPgpFetching(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeTab, user?.id]);

  // ── Save Handlers ───────────────────────────────────────────

  const handleSaveBranding = useCallback(() => {
    if (!tenant) return;
    setErrorMessage(null);

    const config: TenantConfig = {
      ...tenant.config,
      branding,
    };

    const updateData: TenantUpdateRequest = {
      config,
      version: tenant.version,
    };

    updateTenantMutation.mutate(
      { tenantId, data: updateData },
      {
        onSuccess: () => setSuccessMessage(t('settings.saved_success')),
        onError: (err) => setErrorMessage(err.message),
      },
    );
  }, [tenant, branding, tenantId, updateTenantMutation]);

  const handleSaveSMTP = useCallback(() => {
    if (!tenant) return;
    setErrorMessage(null);

    const config: TenantConfig = {
      ...tenant.config,
      smtp,
    };

    const updateData: TenantUpdateRequest = {
      config,
      version: tenant.version,
    };

    updateTenantMutation.mutate(
      { tenantId, data: updateData },
      {
        onSuccess: () => setSuccessMessage(t('settings.saved_success')),
        onError: (err) => setErrorMessage(err.message),
      },
    );
  }, [tenant, smtp, tenantId, updateTenantMutation]);

  const handleSaveLanguages = useCallback(() => {
    if (!tenant) return;
    setErrorMessage(null);

    const config: TenantConfig = {
      ...tenant.config,
      languages,
      default_language: defaultLanguage,
    };

    const updateData: TenantUpdateRequest = {
      config,
      version: tenant.version,
    };

    updateTenantMutation.mutate(
      { tenantId, data: updateData },
      {
        onSuccess: () => setSuccessMessage(t('settings.saved_success')),
        onError: (err) => setErrorMessage(err.message),
      },
    );
  }, [tenant, languages, defaultLanguage, tenantId, updateTenantMutation]);

  const handleSaveRetention = useCallback(() => {
    if (!tenant) return;
    setErrorMessage(null);

    const config: TenantConfig = {
      ...tenant.config,
      retention_hinschg_years: retentionHinschg,
      retention_lksg_years: retentionLksg,
    };

    const updateData: TenantUpdateRequest = {
      config,
      version: tenant.version,
    };

    updateTenantMutation.mutate(
      { tenantId, data: updateData },
      {
        onSuccess: () => setSuccessMessage(t('settings.saved_success')),
        onError: (err) => setErrorMessage(err.message),
      },
    );
  }, [tenant, retentionHinschg, retentionLksg, tenantId, updateTenantMutation]);

  const handleSaveChannels = useCallback(() => {
    if (!tenant) return;
    setErrorMessage(null);

    const data: ChannelActivationUpdateRequest = {
      hinschg_enabled: hinschgEnabled,
      lksg_enabled: lksgEnabled,
      version: tenant.version,
    };

    updateChannelMutation.mutate(
      { tenantId, data },
      {
        onSuccess: () => setSuccessMessage(t('settings.saved_success')),
        onError: (err) => setErrorMessage(err.message),
      },
    );
  }, [tenant, hinschgEnabled, lksgEnabled, tenantId, updateChannelMutation]);

  const handleSaveEmailTemplates = useCallback(() => {
    if (!tenant) return;
    setErrorMessage(null);

    const data: EmailTemplateUpdateRequest = {
      ...emailTemplateData,
      version: tenant.version,
    };

    updateEmailTemplateMutation.mutate(
      { tenantId, language: emailTemplateLang, data },
      {
        onSuccess: () => setSuccessMessage(t('settings.saved_success')),
        onError: (err) => setErrorMessage(err.message),
      },
    );
  }, [tenant, emailTemplateData, emailTemplateLang, tenantId, updateEmailTemplateMutation]);

  const handleLanguageToggle = useCallback((lang: string) => {
    setLanguages((prev) =>
      prev.includes(lang)
        ? prev.filter((l) => l !== lang)
        : [...prev, lang],
    );
  }, []);

  // ── PGP Key Handlers ───────────────────────────────────────

  const handlePgpUpload = useCallback(async (armoredKey: string) => {
    if (!user?.id || !armoredKey.trim()) return;
    setPgpLoading(true);
    setErrorMessage(null);

    try {
      const res = await apiClient.post<PGPKeyResponse>(
        `/admin/users/${user.id}/pgp-key`,
        { public_key: armoredKey.trim() },
      );
      setPgpFingerprint(res.data.fingerprint);
      setPgpExpiresAt(res.data.expires_at);
      setPgpUserIds(res.data.user_ids);
      setPgpKeyText('');
      setSuccessMessage(t('settings.pgp.upload_success', 'PGP key uploaded successfully.'));
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : t('settings.pgp.upload_error', 'Failed to upload PGP key.');
      setErrorMessage(message);
    } finally {
      setPgpLoading(false);
    }
  }, [user?.id, t]);

  const handlePgpDelete = useCallback(async () => {
    if (!user?.id) return;
    setPgpLoading(true);
    setErrorMessage(null);

    try {
      await apiClient.delete<PGPKeyDeleteResponse>(`/admin/users/${user.id}/pgp-key`);
      setPgpFingerprint(null);
      setPgpExpiresAt(null);
      setPgpUserIds([]);
      setPgpKeyText('');
      setSuccessMessage(t('settings.pgp.delete_success', 'PGP key removed successfully.'));
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : t('settings.pgp.delete_error', 'Failed to remove PGP key.');
      setErrorMessage(message);
    } finally {
      setPgpLoading(false);
    }
  }, [user?.id, t]);

  const handlePgpFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result;
      if (typeof content === 'string') {
        setPgpKeyText(content);
      }
    };
    reader.readAsText(file);

    // Reset file input so the same file can be re-selected
    e.target.value = '';
  }, []);

  // ── Loading / Error State ───────────────────────────────────

  if (tenantLoading) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="flex items-center justify-center py-16" role="status" aria-label={t('settings.loading', 'Loading...')}>
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        </div>
      </div>
    );
  }

  if (tenantError || !tenant) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="rounded-lg border border-danger/20 bg-danger/5 p-6 text-center" role="alert">
          <h2 className="text-lg font-semibold text-danger">{t('settings.error.load')}</h2>
        </div>
      </div>
    );
  }

  const isSaving =
    updateTenantMutation.isPending ||
    updateChannelMutation.isPending ||
    updateEmailTemplateMutation.isPending;

  // ── Render ──────────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Page Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-neutral-900">{t('settings.title')}</h1>
        <p className="mt-1 text-sm text-neutral-500">
          {t('settings.subtitle')}
        </p>
      </div>

      {/* Success / Error Banners */}
      {successMessage && (
        <SuccessBanner
          message={successMessage}
          onDismiss={() => setSuccessMessage(null)}
        />
      )}
      {errorMessage && (
        <div className="mb-4 rounded-md border border-danger/20 bg-danger/5 px-4 py-3 text-sm text-danger" role="alert">
          {errorMessage}
        </div>
      )}

      {/* Tab Navigation */}
      <div className="mb-6 border-b border-neutral-200">
        <nav className="-mb-px flex gap-4" role="tablist" aria-label={t('settings.title')}>
          {TAB_KEYS.map((tabKey) => (
            <button
              key={tabKey}
              type="button"
              role="tab"
              aria-selected={activeTab === tabKey}
              onClick={() => setActiveTab(tabKey)}
              className={`whitespace-nowrap border-b-2 px-1 py-3 text-sm font-medium transition-colors ${
                activeTab === tabKey
                  ? 'border-primary text-primary'
                  : 'border-transparent text-neutral-500 hover:border-neutral-300 hover:text-neutral-700'
              }`}
            >
              {t(`settings.tabs.${tabKey}`)}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      <div className="rounded-lg border border-neutral-200 bg-white p-6 shadow-sm">
        {/* ── Branding Tab ──────────────────────────────────── */}
        {activeTab === 'branding' && (
          <div>
            <h2 className="mb-1 text-lg font-semibold text-neutral-900">{t('settings.branding.title')}</h2>
            <p className="mb-6 text-sm text-neutral-500">
              {t('settings.branding.description')}
            </p>

            <div className="space-y-4">
              <div>
                <label htmlFor="s-logo-url" className="mb-1 block text-sm font-medium text-neutral-700">
                  {t('settings.branding.logo_url')}
                </label>
                <input
                  id="s-logo-url"
                  type="url"
                  value={branding.logo_url ?? ''}
                  onChange={(e) => setBranding((prev) => ({ ...prev, logo_url: e.target.value || null }))}
                  placeholder="https://..."
                  className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label htmlFor="s-primary-color" className="mb-1 block text-sm font-medium text-neutral-700">
                    {t('settings.branding.primary_color')}
                  </label>
                  <div className="flex gap-2">
                    <input
                      id="s-primary-color"
                      type="color"
                      value={branding.primary_color ?? '#1e40af'}
                      onChange={(e) => setBranding((prev) => ({ ...prev, primary_color: e.target.value }))}
                      className="h-10 w-12 cursor-pointer rounded border border-neutral-300"
                    />
                    <input
                      type="text"
                      value={branding.primary_color ?? ''}
                      onChange={(e) => setBranding((prev) => ({ ...prev, primary_color: e.target.value || null }))}
                      placeholder="#1e40af"
                      className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                </div>
                <div>
                  <label htmlFor="s-accent-color" className="mb-1 block text-sm font-medium text-neutral-700">
                    {t('settings.branding.accent_color')}
                  </label>
                  <div className="flex gap-2">
                    <input
                      id="s-accent-color"
                      type="color"
                      value={branding.accent_color ?? '#3b82f6'}
                      onChange={(e) => setBranding((prev) => ({ ...prev, accent_color: e.target.value }))}
                      className="h-10 w-12 cursor-pointer rounded border border-neutral-300"
                    />
                    <input
                      type="text"
                      value={branding.accent_color ?? ''}
                      onChange={(e) => setBranding((prev) => ({ ...prev, accent_color: e.target.value || null }))}
                      placeholder="#3b82f6"
                      className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="mt-6 flex justify-end">
              <button
                type="button"
                onClick={handleSaveBranding}
                disabled={isSaving}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {isSaving ? t('settings.saving', 'Saving...') : t('settings.save', 'Save')}
              </button>
            </div>
          </div>
        )}

        {/* ── SMTP Tab ──────────────────────────────────────── */}
        {activeTab === 'smtp' && (
          <div>
            <h2 className="mb-1 text-lg font-semibold text-neutral-900">{t('settings.smtp.title')}</h2>
            <p className="mb-6 text-sm text-neutral-500">
              {t('settings.smtp.description')}
            </p>

            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-4">
                <div className="col-span-2">
                  <label htmlFor="s-smtp-host" className="mb-1 block text-sm font-medium text-neutral-700">
                    {t('settings.smtp.host')}
                  </label>
                  <input
                    id="s-smtp-host"
                    type="text"
                    value={smtp.host}
                    onChange={(e) => setSmtp((prev) => ({ ...prev, host: e.target.value }))}
                    placeholder="smtp.example.com"
                    className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
                <div>
                  <label htmlFor="s-smtp-port" className="mb-1 block text-sm font-medium text-neutral-700">
                    {t('settings.smtp.port')}
                  </label>
                  <input
                    id="s-smtp-port"
                    type="number"
                    min={1}
                    max={65535}
                    value={smtp.port}
                    onChange={(e) => setSmtp((prev) => ({ ...prev, port: Number(e.target.value) }))}
                    className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label htmlFor="s-smtp-user" className="mb-1 block text-sm font-medium text-neutral-700">
                    {t('settings.smtp.user')}
                  </label>
                  <input
                    id="s-smtp-user"
                    type="text"
                    value={smtp.user}
                    onChange={(e) => setSmtp((prev) => ({ ...prev, user: e.target.value }))}
                    placeholder="smtp-user"
                    className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
                <div>
                  <label htmlFor="s-smtp-password" className="mb-1 block text-sm font-medium text-neutral-700">
                    {t('settings.smtp.password')}
                  </label>
                  <input
                    id="s-smtp-password"
                    type="password"
                    value={smtp.password}
                    onChange={(e) => setSmtp((prev) => ({ ...prev, password: e.target.value }))}
                    placeholder="••••••••"
                    className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
              </div>
              <div>
                <label htmlFor="s-smtp-from" className="mb-1 block text-sm font-medium text-neutral-700">
                  {t('settings.smtp.from_address')}
                </label>
                <input
                  id="s-smtp-from"
                  type="email"
                  value={smtp.from_address}
                  onChange={(e) => setSmtp((prev) => ({ ...prev, from_address: e.target.value }))}
                  placeholder="noreply@example.com"
                  className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
              <div className="flex items-center gap-2">
                <input
                  id="s-smtp-tls"
                  type="checkbox"
                  checked={smtp.use_tls}
                  onChange={(e) => setSmtp((prev) => ({ ...prev, use_tls: e.target.checked }))}
                  className="h-4 w-4 rounded border-neutral-300 text-primary focus:ring-primary"
                />
                <label htmlFor="s-smtp-tls" className="text-sm font-medium text-neutral-700">
                  {t('settings.smtp.use_tls')}
                </label>
              </div>
            </div>

            <div className="mt-6 flex justify-end">
              <button
                type="button"
                onClick={handleSaveSMTP}
                disabled={isSaving}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {isSaving ? t('settings.saving', 'Saving...') : t('settings.save', 'Save')}
              </button>
            </div>
          </div>
        )}

        {/* ── Languages Tab ─────────────────────────────────── */}
        {activeTab === 'languages' && (
          <div>
            <h2 className="mb-1 text-lg font-semibold text-neutral-900">{t('settings.languages.title')}</h2>
            <p className="mb-6 text-sm text-neutral-500">
              {t('settings.languages.description')}
            </p>

            <div className="space-y-4">
              <div>
                <p className="mb-2 text-sm font-medium text-neutral-700">{t('settings.languages.available')}</p>
                <div className="flex flex-col gap-2">
                  {[
                    { value: 'de', label: t('settings.lang_de', 'Deutsch') },
                    { value: 'en', label: t('settings.lang_en', 'English') },
                  ].map((lang) => (
                    <div key={lang.value} className="flex items-center gap-2">
                      <input
                        id={`lang-${lang.value}`}
                        type="checkbox"
                        checked={languages.includes(lang.value)}
                        onChange={() => handleLanguageToggle(lang.value)}
                        disabled={lang.value === defaultLanguage}
                        className="h-4 w-4 rounded border-neutral-300 text-primary focus:ring-primary disabled:opacity-50"
                      />
                      <label htmlFor={`lang-${lang.value}`} className="text-sm text-neutral-700">
                        {lang.label}
                      </label>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <label htmlFor="s-default-lang" className="mb-1 block text-sm font-medium text-neutral-700">
                  {t('settings.languages.default')}
                </label>
                <select
                  id="s-default-lang"
                  value={defaultLanguage}
                  onChange={(e) => setDefaultLanguage(e.target.value)}
                  className="w-full max-w-xs rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  {languages.map((lang) => (
                    <option key={lang} value={lang}>
                      {lang === 'de' ? t('settings.lang_de', 'Deutsch') : lang === 'en' ? t('settings.lang_en', 'English') : lang.toUpperCase()}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="mt-6 flex justify-end">
              <button
                type="button"
                onClick={handleSaveLanguages}
                disabled={isSaving}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {isSaving ? t('settings.saving', 'Saving...') : t('settings.save', 'Save')}
              </button>
            </div>
          </div>
        )}

        {/* ── Channels Tab ──────────────────────────────────── */}
        {activeTab === 'channels' && (
          <div>
            <h2 className="mb-1 text-lg font-semibold text-neutral-900">{t('settings.channels.title')}</h2>
            <p className="mb-6 text-sm text-neutral-500">
              {t('settings.channels.description')}
            </p>

            <div className="space-y-4">
              <div className="flex items-center gap-3 rounded-md border border-neutral-200 p-4">
                <input
                  id="s-hinschg-enabled"
                  type="checkbox"
                  checked={hinschgEnabled}
                  onChange={(e) => setHinschgEnabled(e.target.checked)}
                  className="h-5 w-5 rounded border-neutral-300 text-primary focus:ring-primary"
                />
                <div>
                  <label htmlFor="s-hinschg-enabled" className="text-sm font-medium text-neutral-900">
                    {t('settings.channels.hinschg_enabled')}
                  </label>
                  <p className="text-xs text-neutral-500">
                    {t('settings.channels.hinschg_description', 'Internal reporting channel per Whistleblower Protection Act')}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3 rounded-md border border-neutral-200 p-4">
                <input
                  id="s-lksg-enabled"
                  type="checkbox"
                  checked={lksgEnabled}
                  onChange={(e) => setLksgEnabled(e.target.checked)}
                  className="h-5 w-5 rounded border-neutral-300 text-primary focus:ring-primary"
                />
                <div>
                  <label htmlFor="s-lksg-enabled" className="text-sm font-medium text-neutral-900">
                    {t('settings.channels.lksg_enabled')}
                  </label>
                  <p className="text-xs text-neutral-500">
                    {t('settings.channels.lksg_description', 'Public complaint channel per Supply Chain Due Diligence Act')}
                  </p>
                </div>
              </div>
            </div>

            <div className="mt-6 flex justify-end">
              <button
                type="button"
                onClick={handleSaveChannels}
                disabled={isSaving}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {isSaving ? t('settings.saving', 'Saving...') : t('settings.save', 'Save')}
              </button>
            </div>
          </div>
        )}

        {/* ── Retention Tab ─────────────────────────────────── */}
        {activeTab === 'retention' && (
          <div>
            <h2 className="mb-1 text-lg font-semibold text-neutral-900">{t('settings.retention.title')}</h2>
            <p className="mb-6 text-sm text-neutral-500">
              {t('settings.retention.description')}
            </p>

            <div className="grid grid-cols-2 gap-6">
              <div>
                <label htmlFor="s-retention-hinschg" className="mb-1 block text-sm font-medium text-neutral-700">
                  {t('settings.retention.hinschg_years')}
                </label>
                <input
                  id="s-retention-hinschg"
                  type="number"
                  min={1}
                  max={10}
                  value={retentionHinschg}
                  onChange={(e) => setRetentionHinschg(Number(e.target.value))}
                  className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                />
                <p className="mt-1 text-xs text-neutral-500">
                  {t('settings.retention.hinschg_hint', 'Statutory minimum: 3 years after case closure')}
                </p>
              </div>
              <div>
                <label htmlFor="s-retention-lksg" className="mb-1 block text-sm font-medium text-neutral-700">
                  {t('settings.retention.lksg_years')}
                </label>
                <input
                  id="s-retention-lksg"
                  type="number"
                  min={1}
                  max={10}
                  value={retentionLksg}
                  onChange={(e) => setRetentionLksg(Number(e.target.value))}
                  className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                />
                <p className="mt-1 text-xs text-neutral-500">
                  {t('settings.retention.lksg_hint', 'Recommended retention: 5 years')}
                </p>
              </div>
            </div>

            <div className="mt-6 flex justify-end">
              <button
                type="button"
                onClick={handleSaveRetention}
                disabled={isSaving}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {isSaving ? t('settings.saving', 'Saving...') : t('settings.save', 'Save')}
              </button>
            </div>
          </div>
        )}

        {/* ── Email Templates Tab ───────────────────────────── */}
        {activeTab === 'email_templates' && (
          <div>
            <h2 className="mb-1 text-lg font-semibold text-neutral-900">{t('settings.email_templates.title')}</h2>
            <p className="mb-6 text-sm text-neutral-500">
              {t('settings.email_templates.description')}
            </p>

            {/* Language Selector */}
            <div className="mb-6">
              <label htmlFor="s-email-lang" className="mb-1 block text-sm font-medium text-neutral-700">
                {t('settings.email_templates.language')}
              </label>
              <select
                id="s-email-lang"
                value={emailTemplateLang}
                onChange={(e) => setEmailTemplateLang(e.target.value)}
                className="rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="de">{t('settings.lang_de', 'Deutsch')}</option>
                <option value="en">{t('settings.lang_en', 'English')}</option>
              </select>
            </div>

            <div className="space-y-6">
              {/* Confirmation */}
              <fieldset className="rounded-md border border-neutral-200 p-4">
                <legend className="px-2 text-sm font-semibold text-neutral-800">
                  {t('settings.email_templates.confirmation_legend', 'Confirmation')}
                </legend>
                <div className="space-y-3">
                  <div>
                    <label htmlFor="s-conf-subject" className="mb-1 block text-sm font-medium text-neutral-700">
                      {t('settings.email_templates.subject_label', 'Subject')}
                    </label>
                    <input
                      id="s-conf-subject"
                      type="text"
                      value={emailTemplateData.confirmation_subject}
                      onChange={(e) =>
                        setEmailTemplateData((prev) => ({ ...prev, confirmation_subject: e.target.value }))
                      }
                      className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                  <div>
                    <label htmlFor="s-conf-body" className="mb-1 block text-sm font-medium text-neutral-700">
                      {t('settings.email_templates.body_label', 'Body')}
                    </label>
                    <textarea
                      id="s-conf-body"
                      rows={4}
                      value={emailTemplateData.confirmation_body}
                      onChange={(e) =>
                        setEmailTemplateData((prev) => ({ ...prev, confirmation_body: e.target.value }))
                      }
                      className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                </div>
              </fieldset>

              {/* Feedback */}
              <fieldset className="rounded-md border border-neutral-200 p-4">
                <legend className="px-2 text-sm font-semibold text-neutral-800">{t('settings.email_templates.feedback_legend', 'Feedback')}</legend>
                <div className="space-y-3">
                  <div>
                    <label htmlFor="s-fb-subject" className="mb-1 block text-sm font-medium text-neutral-700">
                      {t('settings.email_templates.subject_label', 'Subject')}
                    </label>
                    <input
                      id="s-fb-subject"
                      type="text"
                      value={emailTemplateData.feedback_subject}
                      onChange={(e) =>
                        setEmailTemplateData((prev) => ({ ...prev, feedback_subject: e.target.value }))
                      }
                      className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                  <div>
                    <label htmlFor="s-fb-body" className="mb-1 block text-sm font-medium text-neutral-700">
                      {t('settings.email_templates.body_label', 'Body')}
                    </label>
                    <textarea
                      id="s-fb-body"
                      rows={4}
                      value={emailTemplateData.feedback_body}
                      onChange={(e) =>
                        setEmailTemplateData((prev) => ({ ...prev, feedback_body: e.target.value }))
                      }
                      className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                </div>
              </fieldset>

              {/* Magic Link */}
              <fieldset className="rounded-md border border-neutral-200 p-4">
                <legend className="px-2 text-sm font-semibold text-neutral-800">{t('settings.email_templates.magic_link_legend', 'Magic Link')}</legend>
                <div className="space-y-3">
                  <div>
                    <label htmlFor="s-ml-subject" className="mb-1 block text-sm font-medium text-neutral-700">
                      {t('settings.email_templates.subject_label', 'Subject')}
                    </label>
                    <input
                      id="s-ml-subject"
                      type="text"
                      value={emailTemplateData.magic_link_subject}
                      onChange={(e) =>
                        setEmailTemplateData((prev) => ({ ...prev, magic_link_subject: e.target.value }))
                      }
                      className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                  <div>
                    <label htmlFor="s-ml-body" className="mb-1 block text-sm font-medium text-neutral-700">
                      {t('settings.email_templates.body_label', 'Body')}
                    </label>
                    <textarea
                      id="s-ml-body"
                      rows={4}
                      value={emailTemplateData.magic_link_body}
                      onChange={(e) =>
                        setEmailTemplateData((prev) => ({ ...prev, magic_link_body: e.target.value }))
                      }
                      className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                </div>
              </fieldset>
            </div>

            <div className="mt-6 flex justify-end">
              <button
                type="button"
                onClick={handleSaveEmailTemplates}
                disabled={isSaving}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {isSaving ? t('settings.saving', 'Saving...') : t('settings.save', 'Save')}
              </button>
            </div>
          </div>
        )}

        {/* ── Labels Tab ─────────────────────────────────────── */}
        {activeTab === 'labels' && (
          <div>
            <h2 className="mb-1 text-lg font-semibold text-neutral-900">
              {t('settings.labels.title', 'Labels')}
            </h2>
            <p className="mb-6 text-sm text-neutral-500">
              {t('settings.labels.description', 'Labels zur Kategorisierung und Filterung von Fällen verwalten.')}
            </p>
            <LabelManager canEdit={true} />
          </div>
        )}

        {/* ── Sub-Statuses Tab ──────────────────────────────── */}
        {activeTab === 'sub_statuses' && (
          <div>
            <h2 className="mb-1 text-lg font-semibold text-neutral-900">
              {t('settings.sub_statuses.title', 'Unterstatus')}
            </h2>
            <p className="mb-6 text-sm text-neutral-500">
              {t('settings.sub_statuses.description', 'Konfigurierbare Unterstatus-Verfeinerungen je Hauptstatus verwalten.')}
            </p>
            <SubStatusManager canEdit={true} />
          </div>
        )}

        {/* ── Two-Factor Tab ───────────────────────────────── */}
        {activeTab === 'two_factor' && (
          <TwoFactorSetup
            isEnabled={twoFactorEnabled}
            onStatusChange={(enabled) => {
              setTwoFactorEnabled(enabled);
              setSuccessMessage(
                enabled
                  ? t('settings.two_factor.enabled_success', '2FA erfolgreich aktiviert.')
                  : t('settings.two_factor.disabled_success', '2FA erfolgreich deaktiviert.'),
              );
            }}
          />
        )}

        {/* ── PGP Keys Tab ────────────────────────────────── */}
        {activeTab === 'pgp_keys' && (
          <div>
            <h2 className="mb-1 text-lg font-semibold text-neutral-900">
              {t('settings.pgp.title', 'PGP Key Management')}
            </h2>
            <p className="mb-6 text-sm text-neutral-500">
              {t(
                'settings.pgp.description',
                'Upload a PGP public key to encrypt email notifications sent to your account.',
              )}
            </p>

            {pgpFetching ? (
              <div className="flex items-center justify-center py-8" role="status">
                <div className="h-6 w-6 animate-spin rounded-full border-4 border-primary border-t-transparent" />
              </div>
            ) : pgpFingerprint ? (
              /* ── Current Key Info ────────────────────────── */
              <div className="space-y-4">
                <div className="rounded-md border border-success/20 bg-success/5 p-4">
                  <div className="flex items-start gap-3">
                    <svg
                      className="mt-0.5 h-5 w-5 flex-shrink-0 text-success"
                      fill="none"
                      viewBox="0 0 24 24"
                      strokeWidth={1.5}
                      stroke="currentColor"
                      aria-hidden="true"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z"
                      />
                    </svg>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-success">
                        {t('settings.pgp.key_active', 'PGP key is active')}
                      </p>
                      <div className="mt-2 space-y-1">
                        <p className="text-sm text-neutral-700">
                          <span className="font-medium">{t('settings.pgp.fingerprint', 'Fingerprint')}:</span>{' '}
                          <code className="break-all rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-xs text-neutral-800">
                            {pgpFingerprint}
                          </code>
                        </p>
                        {pgpExpiresAt && (
                          <p className="text-sm text-neutral-700">
                            <span className="font-medium">{t('settings.pgp.expires_at', 'Expires')}:</span>{' '}
                            {new Date(pgpExpiresAt).toLocaleDateString()}
                          </p>
                        )}
                        {pgpUserIds.length > 0 && (
                          <p className="text-sm text-neutral-700">
                            <span className="font-medium">{t('settings.pgp.key_uids', 'Key UIDs')}:</span>{' '}
                            {pgpUserIds.join(', ')}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={handlePgpDelete}
                    disabled={pgpLoading}
                    className="rounded-md bg-danger px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-danger/90 disabled:opacity-50"
                  >
                    {pgpLoading
                      ? t('settings.pgp.deleting', 'Removing...')
                      : t('settings.pgp.delete', 'Remove PGP Key')}
                  </button>
                </div>
              </div>
            ) : (
              /* ── Upload Form ─────────────────────────────── */
              <div className="space-y-4">
                <div>
                  <label htmlFor="s-pgp-key" className="mb-1 block text-sm font-medium text-neutral-700">
                    {t('settings.pgp.paste_label', 'Paste ASCII-armored PGP public key')}
                  </label>
                  <textarea
                    id="s-pgp-key"
                    rows={8}
                    value={pgpKeyText}
                    onChange={(e) => setPgpKeyText(e.target.value)}
                    placeholder={
                      '-----BEGIN PGP PUBLIC KEY BLOCK-----\n\n...\n\n-----END PGP PUBLIC KEY BLOCK-----'
                    }
                    className="w-full rounded-md border border-neutral-300 px-3 py-2 font-mono text-sm placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>

                <div className="flex items-center gap-4">
                  <span className="text-sm text-neutral-500">
                    {t('settings.pgp.or_upload', 'or upload a .asc file:')}
                  </span>
                  <input
                    ref={pgpFileInputRef}
                    type="file"
                    accept=".asc,.gpg,.pgp,.key,application/pgp-keys"
                    onChange={handlePgpFileChange}
                    className="hidden"
                    aria-label={t('settings.pgp.file_upload_label', 'Upload PGP key file')}
                  />
                  <button
                    type="button"
                    onClick={() => pgpFileInputRef.current?.click()}
                    className="inline-flex items-center gap-1.5 rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
                  >
                    <svg
                      className="h-4 w-4"
                      fill="none"
                      viewBox="0 0 24 24"
                      strokeWidth={1.5}
                      stroke="currentColor"
                      aria-hidden="true"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5"
                      />
                    </svg>
                    {t('settings.pgp.choose_file', 'Choose File')}
                  </button>
                </div>

                <div className="mt-6 flex justify-end">
                  <button
                    type="button"
                    onClick={() => handlePgpUpload(pgpKeyText)}
                    disabled={pgpLoading || !pgpKeyText.trim()}
                    className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
                  >
                    {pgpLoading
                      ? t('settings.pgp.uploading', 'Uploading...')
                      : t('settings.pgp.upload', 'Upload PGP Key')}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
