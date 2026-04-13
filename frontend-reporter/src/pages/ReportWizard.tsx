/**
 * Hinweisgebersystem - ReportWizard Page Component.
 *
 * 3-step wizard for submitting a whistleblower report:
 *   Step 1: Channel confirmation + category selection
 *   Step 2: Description, optional files, optional identity, LkSG-extended fields
 *   Step 3: Review all data + hCaptcha verification + submit
 *
 * On successful submission, navigates to ReportSuccess with the case
 * credentials.  Form state is ephemeral (no localStorage persistence
 * in anonymous mode).
 *
 * WCAG 2.1 AA compliant:
 * - StepIndicator with aria-current="step"
 * - aria-live regions for error announcements
 * - Keyboard-navigable form controls
 * - Required field indicators with screen reader text
 * - 4.5:1 contrast ratio
 * - Responsive layout (320px min width)
 */

import { useCallback, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';

import StepIndicator, { DEFAULT_REPORT_STEPS } from '@/components/StepIndicator';
import CategorySelect from '@/components/CategorySelect';
import FileUpload from '@/components/FileUpload';
import CaptchaWidget, { type CaptchaWidgetHandle } from '@/components/CaptchaWidget';
import LanguageSelector from '@/components/LanguageSelector';
import { useCreateReport } from '@/hooks/useReport';
import { uploadReportAttachment } from '@/api/reports';
import { reportFormSchema, type ReportFormData, type Channel } from '@/schemas/report';

// ── Types ──────────────────────────────────────────────────────

interface FormState {
  channel: Channel;
  category: string;
  subject: string;
  description: string;
  is_anonymous: boolean;
  reporter_name: string;
  reporter_email: string;
  reporter_phone: string;
  password: string;
  country: string;
  organization: string;
  supply_chain_tier: string;
  reporter_relationship: string;
  lksg_category: string;
  captcha_token: string;
  language: string;
}

type FormErrors = Partial<Record<keyof FormState | string, string>>;

// ── Helpers ────────────────────────────────────────────────────

function getInitialFormState(channel: Channel, language: string): FormState {
  return {
    channel,
    category: '',
    subject: '',
    description: '',
    is_anonymous: true,
    reporter_name: '',
    reporter_email: '',
    reporter_phone: '',
    password: '',
    country: '',
    organization: '',
    supply_chain_tier: '',
    reporter_relationship: '',
    lksg_category: '',
    captcha_token: '',
    language,
  };
}

/** Validate a subset of fields for a given wizard step. */
function validateStep(form: FormState, step: number): FormErrors {
  const errors: FormErrors = {};

  if (step === 0) {
    // Step 1: Category (required for LkSG)
    if (form.channel === 'lksg' && !form.lksg_category) {
      errors.lksg_category = 'report.validation.lksg_category_required';
    }
  }

  if (step === 1) {
    // Step 2: Subject + Description required
    if (!form.subject.trim()) {
      errors.subject = 'report.validation.subject_required';
    }
    if (form.subject.length > 500) {
      errors.subject = 'report.validation.subject_max';
    }
    if (!form.description.trim()) {
      errors.description = 'report.validation.description_required';
    }
    if (form.description.length > 50_000) {
      errors.description = 'report.validation.description_max';
    }

    // Non-anonymous: require name + email
    if (!form.is_anonymous) {
      if (!form.reporter_name.trim()) {
        errors.reporter_name = 'report.validation.name_required';
      }
      if (!form.reporter_email.trim()) {
        errors.reporter_email = 'report.validation.email_required';
      }
    }

    // LkSG extended fields
    if (form.channel === 'lksg') {
      if (!form.country.trim()) {
        errors.country = 'report.validation.country_required';
      } else if (form.country.trim().length !== 3) {
        errors.country = 'report.validation.country_code';
      }
      if (!form.organization.trim()) {
        errors.organization = 'report.validation.organization_required';
      }
    }

    // Optional password validation
    if (form.password && form.password.length < 10) {
      errors.password = 'report.validation.password_min';
    }
  }

  return errors;
}

// ── Component ─────────────────────────────────────────────────

export default function ReportWizard() {
  const { t, i18n } = useTranslation('report');
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const captchaRef = useRef<CaptchaWidgetHandle>(null);

  const initialChannel = (searchParams.get('channel') as Channel) || 'hinschg';

  const [currentStep, setCurrentStep] = useState(0);
  const [form, setForm] = useState<FormState>(() =>
    getInitialFormState(initialChannel, i18n.language?.split('-')[0] ?? 'de'),
  );
  const [files, setFiles] = useState<File[]>([]);
  const [errors, setErrors] = useState<FormErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);

  const createReport = useCreateReport();

  // ── Form field updater ──────────────────────────────────────

  const updateField = useCallback(
    <K extends keyof FormState>(field: K, value: FormState[K]) => {
      setForm((prev) => ({ ...prev, [field]: value }));
      // Clear field error on change
      setErrors((prev) => {
        if (!prev[field]) return prev;
        const next = { ...prev };
        delete next[field];
        return next;
      });
    },
    [],
  );

  // ── Navigation ──────────────────────────────────────────────

  const handleNext = useCallback(() => {
    const stepErrors = validateStep(form, currentStep);
    if (Object.keys(stepErrors).length > 0) {
      setErrors(stepErrors);
      return;
    }
    setErrors({});
    setCurrentStep((prev) => Math.min(prev + 1, 2));
  }, [form, currentStep]);

  const handleBack = useCallback(() => {
    setErrors({});
    setCurrentStep((prev) => Math.max(prev - 1, 0));
  }, []);

  // ── Submission ──────────────────────────────────────────────

  const handleSubmit = useCallback(async () => {
    setSubmitError(null);

    // Build the form data for Zod validation
    const formData: Record<string, unknown> = {
      subject: form.subject,
      description: form.description,
      channel: form.channel,
      category: form.channel === 'lksg' ? form.lksg_category : (form.category || undefined),
      language: form.language,
      is_anonymous: form.is_anonymous,
      captcha_token: form.captcha_token || undefined,
    };

    // Conditional fields
    if (!form.is_anonymous) {
      formData.reporter_name = form.reporter_name || undefined;
      formData.reporter_email = form.reporter_email || undefined;
      formData.reporter_phone = form.reporter_phone || undefined;
    }

    if (form.password) {
      formData.password = form.password;
    }

    if (form.channel === 'lksg') {
      formData.country = form.country || undefined;
      formData.organization = form.organization || undefined;
      formData.supply_chain_tier = form.supply_chain_tier || undefined;
      formData.reporter_relationship = form.reporter_relationship || undefined;
      formData.lksg_category = form.lksg_category || undefined;
    }

    // Validate with Zod
    const result = reportFormSchema.safeParse(formData);
    if (!result.success) {
      const zodErrors: FormErrors = {};
      for (const issue of result.error.issues) {
        const key = issue.path.join('.') || 'form';
        zodErrors[key] = issue.message;
      }
      setErrors(zodErrors);
      return;
    }

    try {
      const response = await createReport.mutateAsync(result.data as ReportFormData);

      // Upload files after report creation using the session token.
      if (files.length > 0 && response.access_token) {
        for (const file of files) {
          try {
            await uploadReportAttachment(response.access_token, file);
          } catch (uploadErr) {
            // Log but don't block navigation — files can be re-uploaded via mailbox.
            console.warn('File upload failed:', file.name, uploadErr);
          }
        }
      }

      navigate('/report/success', {
        state: {
          caseNumber: response.case_number,
          passphrase: response.passphrase,
          hasPassword: !!form.password,
          channel: form.channel,
        },
      });
    } catch (err) {
      captchaRef.current?.resetCaptcha();
      updateField('captcha_token', '');
      if (err instanceof Error) {
        setSubmitError(err.message);
      } else {
        setSubmitError(t('submit.error_generic', 'Ein Fehler ist aufgetreten. Bitte versuchen Sie es erneut.'));
      }
    }
  }, [form, createReport, navigate, t, updateField]);

  // ── Computed values ─────────────────────────────────────────

  const isLksg = form.channel === 'lksg';
  const isSubmitting = createReport.isPending;

  const reviewFields = useMemo(() => {
    const fields: Array<{ label: string; value: string }> = [
      { label: t('review.channel', 'Kanal'), value: isLksg ? 'LkSG' : 'HinSchG' },
      { label: t('fields.subject', 'Betreff'), value: form.subject },
      { label: t('fields.description', 'Beschreibung'), value: form.description },
    ];

    if (form.category || form.lksg_category) {
      fields.push({
        label: t('fields.category', 'Kategorie'),
        value: form.channel === 'lksg' ? form.lksg_category : form.category,
      });
    }

    if (isLksg) {
      if (form.country) fields.push({ label: t('fields.country', 'Land'), value: form.country });
      if (form.organization) fields.push({ label: t('fields.organization', 'Organisation'), value: form.organization });
      if (form.supply_chain_tier) fields.push({ label: t('fields.supply_chain_tier', 'Lieferkettenstufe'), value: form.supply_chain_tier });
      if (form.reporter_relationship) fields.push({ label: t('fields.reporter_relationship', 'Beziehung zum Unternehmen'), value: form.reporter_relationship });
    }

    if (!form.is_anonymous) {
      if (form.reporter_name) fields.push({ label: t('fields.reporter_name', 'Name'), value: form.reporter_name });
      if (form.reporter_email) fields.push({ label: t('fields.reporter_email', 'E-Mail'), value: form.reporter_email });
      if (form.reporter_phone) fields.push({ label: t('fields.reporter_phone', 'Telefon'), value: form.reporter_phone });
    }

    fields.push({
      label: t('review.anonymity', 'Anonymität'),
      value: form.is_anonymous
        ? t('review.anonymous', 'Anonym')
        : t('review.not_anonymous', 'Nicht anonym'),
    });

    if (files.length > 0) {
      fields.push({
        label: t('fields.attachments', 'Dateien'),
        value: files.map((f) => f.name).join(', '),
      });
    }

    return fields;
  }, [form, files, isLksg, t]);

  // ── Render helpers ──────────────────────────────────────────

  const renderFieldError = (field: string) => {
    const error = errors[field];
    if (!error) return null;
    return (
      <p className="mt-1.5 text-sm text-danger" role="alert">
        {t(error, error)}
      </p>
    );
  };

  const inputClasses = (field: string) =>
    `w-full rounded-lg border px-3 py-2.5 text-sm text-neutral-900 transition-colors ${
      errors[field]
        ? 'border-danger focus:border-danger focus:ring-danger'
        : 'border-neutral-300 focus:border-primary focus:ring-primary'
    } bg-white focus:ring-2 focus:ring-offset-0`;

  // ── Step 1: Category Selection ──────────────────────────────

  const renderStep1 = () => (
    <div className="space-y-6">
      {/* Channel indicator */}
      <div className="rounded-lg border border-primary/20 bg-primary/5 p-4">
        <p className="text-sm font-medium text-primary">
          {isLksg
            ? t('wizard.channel_lksg', 'Öffentlicher Beschwerdekanal (LkSG)')
            : t('wizard.channel_hinschg', 'Interner Meldekanal (HinSchG)')}
        </p>
        <p className="mt-1 text-xs text-neutral-600">
          {isLksg
            ? t(
                'wizard.channel_lksg_info',
                'Melden Sie Menschenrechtsverletzungen oder Umweltverstöße in der Lieferkette.',
              )
            : t(
                'wizard.channel_hinschg_info',
                'Melden Sie Verstöße gegen geltendes Recht innerhalb des Unternehmens.',
              )}
        </p>
      </div>

      {/* Category selection */}
      {isLksg ? (
        <CategorySelect
          channel={form.channel}
          value={form.lksg_category}
          onChange={(value) => updateField('lksg_category', value)}
          error={errors.lksg_category}
          id="lksg-category"
        />
      ) : (
        <CategorySelect
          channel={form.channel}
          value={form.category}
          onChange={(value) => updateField('category', value)}
          error={errors.category}
          id="hinschg-category"
        />
      )}
    </div>
  );

  // ── Step 2: Details ─────────────────────────────────────────

  const renderStep2 = () => (
    <div className="space-y-6">
      {/* Subject */}
      <div>
        <label
          htmlFor="subject"
          className="mb-1.5 block text-sm font-medium text-neutral-700"
        >
          {t('fields.subject', 'Betreff')}
          <span className="ml-1 text-danger" aria-hidden="true">*</span>
        </label>
        <input
          id="subject"
          type="text"
          value={form.subject}
          onChange={(e) => updateField('subject', e.target.value)}
          maxLength={500}
          aria-required="true"
          aria-invalid={!!errors.subject}
          aria-describedby={errors.subject ? 'subject-error' : undefined}
          className={inputClasses('subject')}
          placeholder={t('fields.subject_placeholder', 'Kurze Zusammenfassung des Vorfalls')}
        />
        {errors.subject && (
          <p id="subject-error" className="mt-1.5 text-sm text-danger" role="alert">
            {t(errors.subject, errors.subject)}
          </p>
        )}
      </div>

      {/* Description */}
      <div>
        <label
          htmlFor="description"
          className="mb-1.5 block text-sm font-medium text-neutral-700"
        >
          {t('fields.description', 'Beschreibung')}
          <span className="ml-1 text-danger" aria-hidden="true">*</span>
        </label>
        <textarea
          id="description"
          value={form.description}
          onChange={(e) => updateField('description', e.target.value)}
          rows={6}
          maxLength={50_000}
          aria-required="true"
          aria-invalid={!!errors.description}
          aria-describedby={errors.description ? 'description-error' : undefined}
          className={inputClasses('description')}
          placeholder={t(
            'fields.description_placeholder',
            'Beschreiben Sie den Vorfall so detailliert wie möglich...',
          )}
        />
        {errors.description && (
          <p id="description-error" className="mt-1.5 text-sm text-danger" role="alert">
            {t(errors.description, errors.description)}
          </p>
        )}
      </div>

      {/* LkSG Extended Fields */}
      {isLksg && (
        <fieldset className="space-y-4 rounded-lg border border-neutral-200 p-4">
          <legend className="px-2 text-sm font-semibold text-neutral-700">
            {t('wizard.lksg_fields', 'LkSG-spezifische Angaben')}
          </legend>

          {/* Country (ISO 3166-1 alpha-3) */}
          <div>
            <label
              htmlFor="country"
              className="mb-1.5 block text-sm font-medium text-neutral-700"
            >
              {t('fields.country', 'Land (ISO-3 Code)')}
              <span className="ml-1 text-danger" aria-hidden="true">*</span>
            </label>
            <input
              id="country"
              type="text"
              value={form.country}
              onChange={(e) => updateField('country', e.target.value.toUpperCase())}
              maxLength={3}
              aria-required="true"
              aria-invalid={!!errors.country}
              aria-describedby={errors.country ? 'country-error' : 'country-hint'}
              className={inputClasses('country')}
              placeholder="DEU"
            />
            <p id="country-hint" className="mt-1 text-xs text-neutral-500">
              {t('fields.country_hint', '3-stelliger ISO-Ländercode (z.B. DEU, CHN, BRA)')}
            </p>
            {renderFieldError('country')}
          </div>

          {/* Organization */}
          <div>
            <label
              htmlFor="organization"
              className="mb-1.5 block text-sm font-medium text-neutral-700"
            >
              {t('fields.organization', 'Betroffenes Unternehmen')}
              <span className="ml-1 text-danger" aria-hidden="true">*</span>
            </label>
            <input
              id="organization"
              type="text"
              value={form.organization}
              onChange={(e) => updateField('organization', e.target.value)}
              maxLength={255}
              aria-required="true"
              aria-invalid={!!errors.organization}
              aria-describedby={errors.organization ? 'organization-error' : undefined}
              className={inputClasses('organization')}
            />
            {renderFieldError('organization')}
          </div>

          {/* Supply Chain Tier */}
          <div>
            <label
              htmlFor="supply-chain-tier"
              className="mb-1.5 block text-sm font-medium text-neutral-700"
            >
              {t('fields.supply_chain_tier', 'Lieferkettenstufe')}
            </label>
            <select
              id="supply-chain-tier"
              value={form.supply_chain_tier}
              onChange={(e) => updateField('supply_chain_tier', e.target.value)}
              className={inputClasses('supply_chain_tier')}
            >
              <option value="">{t('fields.select_placeholder', '-- Bitte auswählen --')}</option>
              <option value="own_operations">{t('supply_chain.own_operations', 'Eigener Geschäftsbereich')}</option>
              <option value="direct_supplier">{t('supply_chain.direct_supplier', 'Unmittelbarer Zulieferer')}</option>
              <option value="indirect_supplier">{t('supply_chain.indirect_supplier', 'Mittelbarer Zulieferer')}</option>
              <option value="unknown">{t('supply_chain.unknown', 'Unbekannt')}</option>
            </select>
          </div>

          {/* Reporter Relationship */}
          <div>
            <label
              htmlFor="reporter-relationship"
              className="mb-1.5 block text-sm font-medium text-neutral-700"
            >
              {t('fields.reporter_relationship', 'Beziehung zum Unternehmen')}
            </label>
            <select
              id="reporter-relationship"
              value={form.reporter_relationship}
              onChange={(e) => updateField('reporter_relationship', e.target.value)}
              className={inputClasses('reporter_relationship')}
            >
              <option value="">{t('fields.select_placeholder', '-- Bitte auswählen --')}</option>
              <option value="employee">{t('relationship.employee', 'Mitarbeiter/in')}</option>
              <option value="supplier">{t('relationship.supplier', 'Lieferant')}</option>
              <option value="contractor">{t('relationship.contractor', 'Auftragnehmer')}</option>
              <option value="community_member">{t('relationship.community_member', 'Anwohner/in')}</option>
              <option value="ngo">{t('relationship.ngo', 'NGO / Zivilgesellschaft')}</option>
              <option value="other">{t('relationship.other', 'Sonstiges')}</option>
            </select>
          </div>
        </fieldset>
      )}

      {/* File Upload */}
      <FileUpload files={files} onChange={setFiles} />

      {/* Anonymity Toggle */}
      <fieldset className="space-y-4 rounded-lg border border-neutral-200 p-4">
        <legend className="px-2 text-sm font-semibold text-neutral-700">
          {t('wizard.identity_section', 'Identität (optional)')}
        </legend>

        <div className="flex items-center gap-3">
          <input
            id="is-anonymous"
            type="checkbox"
            checked={form.is_anonymous}
            onChange={(e) => updateField('is_anonymous', e.target.checked)}
            className="h-4 w-4 rounded border-neutral-300 text-primary focus:ring-primary"
          />
          <label htmlFor="is-anonymous" className="text-sm text-neutral-700">
            {t('fields.is_anonymous', 'Ich möchte anonym melden')}
          </label>
        </div>

        {!form.is_anonymous && (
          <div className="space-y-4 border-t border-neutral-200 pt-4">
            <div>
              <label
                htmlFor="reporter-name"
                className="mb-1.5 block text-sm font-medium text-neutral-700"
              >
                {t('fields.reporter_name', 'Name')}
                <span className="ml-1 text-danger" aria-hidden="true">*</span>
              </label>
              <input
                id="reporter-name"
                type="text"
                value={form.reporter_name}
                onChange={(e) => updateField('reporter_name', e.target.value)}
                maxLength={255}
                aria-required="true"
                aria-invalid={!!errors.reporter_name}
                aria-describedby={errors.reporter_name ? 'reporter-name-error' : undefined}
                className={inputClasses('reporter_name')}
              />
              {renderFieldError('reporter_name')}
            </div>

            <div>
              <label
                htmlFor="reporter-email"
                className="mb-1.5 block text-sm font-medium text-neutral-700"
              >
                {t('fields.reporter_email', 'E-Mail')}
                <span className="ml-1 text-danger" aria-hidden="true">*</span>
              </label>
              <input
                id="reporter-email"
                type="email"
                value={form.reporter_email}
                onChange={(e) => updateField('reporter_email', e.target.value)}
                maxLength={255}
                aria-required="true"
                aria-invalid={!!errors.reporter_email}
                aria-describedby={errors.reporter_email ? 'reporter-email-error' : undefined}
                className={inputClasses('reporter_email')}
              />
              {renderFieldError('reporter_email')}
            </div>

            <div>
              <label
                htmlFor="reporter-phone"
                className="mb-1.5 block text-sm font-medium text-neutral-700"
              >
                {t('fields.reporter_phone', 'Telefon')}
              </label>
              <input
                id="reporter-phone"
                type="tel"
                value={form.reporter_phone}
                onChange={(e) => updateField('reporter_phone', e.target.value)}
                maxLength={50}
                className={inputClasses('reporter_phone')}
              />
            </div>
          </div>
        )}
      </fieldset>

      {/* Optional self-chosen password */}
      <div>
        <label
          htmlFor="password"
          className="mb-1.5 block text-sm font-medium text-neutral-700"
        >
          {t('fields.password', 'Eigenes Passwort (optional)')}
        </label>
        <input
          id="password"
          type="password"
          value={form.password}
          onChange={(e) => updateField('password', e.target.value)}
          maxLength={128}
          aria-describedby={errors.password ? 'password-error' : 'password-hint'}
          aria-invalid={!!errors.password}
          className={inputClasses('password')}
        />
        <p id="password-hint" className="mt-1 text-xs text-neutral-500">
          {t(
            'fields.password_hint',
            'Mind. 10 Zeichen. Wenn leer, wird ein sicherer Passphrase generiert.',
          )}
        </p>
        {renderFieldError('password')}
      </div>
    </div>
  );

  // ── Step 3: Review + Submit ─────────────────────────────────

  const renderStep3 = () => (
    <div className="space-y-6">
      {/* Review summary */}
      <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4">
        <h3 className="mb-3 text-sm font-semibold text-neutral-900">
          {t('review.heading', 'Zusammenfassung Ihrer Meldung')}
        </h3>
        <dl className="space-y-3">
          {reviewFields.map((field) => (
            <div key={field.label}>
              <dt className="text-xs font-medium text-neutral-500">
                {field.label}
              </dt>
              <dd className="mt-0.5 whitespace-pre-wrap break-words text-sm text-neutral-900">
                {field.value || '—'}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      {/* Warning about data loss */}
      <div
        className="rounded-lg border border-warning/30 bg-warning/5 p-4"
        role="alert"
      >
        <div className="flex gap-3">
          <svg
            className="h-5 w-5 shrink-0 text-warning"
            fill="currentColor"
            viewBox="0 0 20 20"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
              clipRule="evenodd"
            />
          </svg>
          <p className="text-sm text-neutral-700">
            {t(
              'review.warning',
              'Bitte überprüfen Sie alle Angaben sorgfältig. Nach dem Absenden erhalten Sie Zugangsdaten, die Sie sicher aufbewahren müssen. Ohne diese Daten können Sie nicht auf Ihr Postfach zugreifen.',
            )}
          </p>
        </div>
      </div>

      {/* hCaptcha */}
      <CaptchaWidget
        ref={captchaRef}
        onVerify={(token) => updateField('captcha_token', token)}
        onExpire={() => updateField('captcha_token', '')}
        onError={() => updateField('captcha_token', '')}
        error={errors.captcha_token}
      />

      {/* Submit error */}
      {submitError && (
        <div className="rounded-lg border border-danger/30 bg-danger/5 p-4" role="alert">
          <p className="text-sm text-danger">{submitError}</p>
        </div>
      )}
    </div>
  );

  // ── Main render ─────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Header */}
      <header className="mb-6 flex items-start justify-between">
        <h1 className="text-xl font-bold text-neutral-900 sm:text-2xl">
          {t('wizard.title', 'Meldung erstellen')}
        </h1>
        <LanguageSelector compact />
      </header>

      {/* Step indicator */}
      <div className="mb-8">
        <StepIndicator currentStep={currentStep} steps={DEFAULT_REPORT_STEPS} />
      </div>

      {/* Step content */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (currentStep < 2) {
            handleNext();
          } else {
            handleSubmit();
          }
        }}
        noValidate
      >
        {/* Error summary for screen readers */}
        {Object.keys(errors).length > 0 && (
          <div className="sr-only" role="alert" aria-live="assertive">
            {t('wizard.errors_present', 'Bitte korrigieren Sie die markierten Felder.')}
          </div>
        )}

        {currentStep === 0 && renderStep1()}
        {currentStep === 1 && renderStep2()}
        {currentStep === 2 && renderStep3()}

        {/* Navigation buttons */}
        <div className="mt-8 flex items-center justify-between border-t border-neutral-200 pt-6">
          {currentStep > 0 ? (
            <button
              type="button"
              onClick={handleBack}
              disabled={isSubmitting}
              className="rounded-lg border border-neutral-300 bg-white px-4 py-2.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t('wizard.back', 'Zurück')}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => navigate('/')}
              className="rounded-lg border border-neutral-300 bg-white px-4 py-2.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
            >
              {t('wizard.cancel', 'Abbrechen')}
            </button>
          )}

          {currentStep < 2 ? (
            <button
              type="submit"
              className="rounded-lg bg-primary px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-dark"
            >
              {t('wizard.next', 'Weiter')}
            </button>
          ) : (
            <button
              type="submit"
              disabled={isSubmitting}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSubmitting && (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              {isSubmitting
                ? t('wizard.submitting', 'Wird gesendet...')
                : t('wizard.submit', 'Meldung absenden')}
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
