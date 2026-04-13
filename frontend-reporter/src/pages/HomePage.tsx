/**
 * Hinweisgebersystem - HomePage Component.
 *
 * Landing page with channel selection (HinSchG internal / LkSG public),
 * informational text about the whistleblower reporting system, language
 * selector, and quick-access links to the anonymous mailbox.
 *
 * WCAG 2.1 AA compliant:
 * - Semantic heading hierarchy (h1, h2)
 * - aria-label on navigation regions
 * - Keyboard-accessible channel cards (button role)
 * - 4.5:1 contrast ratio on all text
 * - Responsive layout (320px min width)
 * - Skip link target via #main-content in App.tsx
 */

import { useCallback } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';

import LanguageSelector from '@/components/LanguageSelector';
import type { Channel } from '@/schemas/report';

// ── Channel card configuration ───────────────────────────────

interface ChannelCard {
  channel: Channel;
  titleKey: string;
  descriptionKey: string;
  icon: 'shield' | 'globe';
}

const CHANNELS: ChannelCard[] = [
  {
    channel: 'hinschg',
    titleKey: 'home.channel.hinschg.title',
    descriptionKey: 'home.channel.hinschg.description',
    icon: 'shield',
  },
  {
    channel: 'lksg',
    titleKey: 'home.channel.lksg.title',
    descriptionKey: 'home.channel.lksg.description',
    icon: 'globe',
  },
];

// ── Icons ────────────────────────────────────────────────────

function ShieldIcon() {
  return (
    <svg
      className="h-10 w-10 text-primary"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.5}
        d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
      />
    </svg>
  );
}

function GlobeIcon() {
  return (
    <svg
      className="h-10 w-10 text-primary"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.5}
        d="M12 21a9 9 0 100-18 9 9 0 000 18zM3.6 9h16.8M3.6 15h16.8M12 3a15.3 15.3 0 014 9 15.3 15.3 0 01-4 9 15.3 15.3 0 01-4-9 15.3 15.3 0 014-9z"
      />
    </svg>
  );
}

function ArrowRightIcon() {
  return (
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
        d="M9 5l7 7-7 7"
      />
    </svg>
  );
}

// ── Component ────────────────────────────────────────────────

export default function HomePage() {
  const { t } = useTranslation('report');
  const navigate = useNavigate();

  const handleChannelSelect = useCallback(
    (channel: Channel) => {
      navigate(`/report?channel=${channel}`);
    },
    [navigate],
  );

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Header with language selector */}
      <header className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900 sm:text-3xl">
            {t('home.title', 'Hinweisgebersystem')}
          </h1>
          <p className="mt-2 text-base text-neutral-600 sm:text-lg">
            {t(
              'home.subtitle',
              'Sicher und vertraulich Hinweise melden',
            )}
          </p>
        </div>
        <LanguageSelector />
      </header>

      {/* Informational text */}
      <section aria-labelledby="info-heading" className="mb-10">
        <h2 id="info-heading" className="sr-only">
          {t('home.info_heading', 'Informationen zum Meldesystem')}
        </h2>
        <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-6">
          <p className="text-sm leading-relaxed text-neutral-700 sm:text-base">
            {t(
              'home.info_text',
              'Dieses Meldeportal ermöglicht es Ihnen, vertraulich auf Missstände hinzuweisen. Ihre Meldung wird nach den Vorgaben des Hinweisgeberschutzgesetzes (HinSchG) und des Lieferkettensorgfaltspflichtengesetzes (LkSG) behandelt. Sie können anonym oder unter Angabe Ihrer Identität melden. Ihre Daten werden verschlüsselt gespeichert und nur von autorisierten Personen eingesehen.',
            )}
          </p>
          <ul className="mt-4 space-y-2 text-sm text-neutral-600">
            <li className="flex items-start gap-2">
              <svg
                className="mt-0.5 h-4 w-4 shrink-0 text-success"
                fill="currentColor"
                viewBox="0 0 20 20"
                aria-hidden="true"
              >
                <path
                  fillRule="evenodd"
                  d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                  clipRule="evenodd"
                />
              </svg>
              {t('home.feature_anonymous', 'Anonyme Meldung möglich')}
            </li>
            <li className="flex items-start gap-2">
              <svg
                className="mt-0.5 h-4 w-4 shrink-0 text-success"
                fill="currentColor"
                viewBox="0 0 20 20"
                aria-hidden="true"
              >
                <path
                  fillRule="evenodd"
                  d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                  clipRule="evenodd"
                />
              </svg>
              {t(
                'home.feature_encrypted',
                'Ende-zu-Ende-Verschlüsselung',
              )}
            </li>
            <li className="flex items-start gap-2">
              <svg
                className="mt-0.5 h-4 w-4 shrink-0 text-success"
                fill="currentColor"
                viewBox="0 0 20 20"
                aria-hidden="true"
              >
                <path
                  fillRule="evenodd"
                  d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                  clipRule="evenodd"
                />
              </svg>
              {t(
                'home.feature_mailbox',
                'Sicheres Postfach für Rückmeldungen',
              )}
            </li>
          </ul>
        </div>
      </section>

      {/* Channel selection */}
      <section aria-labelledby="channel-heading" className="mb-10">
        <h2
          id="channel-heading"
          className="mb-4 text-lg font-semibold text-neutral-900 sm:text-xl"
        >
          {t('home.channel_heading', 'Meldekanal auswählen')}
        </h2>

        <div className="grid gap-4 sm:grid-cols-2">
          {CHANNELS.map((card) => (
            <button
              key={card.channel}
              type="button"
              onClick={() => handleChannelSelect(card.channel)}
              className="group flex flex-col items-start rounded-xl border-2 border-neutral-200 bg-white p-6 text-left transition-all hover:border-primary hover:shadow-md focus:border-primary focus:ring-2 focus:ring-primary focus:ring-offset-2"
              aria-label={t(card.titleKey)}
            >
              <div className="mb-4">
                {card.icon === 'shield' ? <ShieldIcon /> : <GlobeIcon />}
              </div>
              <h3 className="mb-2 text-lg font-semibold text-neutral-900">
                {t(card.titleKey, card.channel === 'hinschg'
                  ? 'Interner Meldekanal (HinSchG)'
                  : 'Öffentlicher Beschwerdekanal (LkSG)')}
              </h3>
              <p className="mb-4 flex-1 text-sm text-neutral-600">
                {t(card.descriptionKey, card.channel === 'hinschg'
                  ? 'Melden Sie Verstöße gegen geltendes Recht innerhalb des Unternehmens. Geschützt durch das Hinweisgeberschutzgesetz.'
                  : 'Melden Sie Menschenrechtsverletzungen oder Umweltverstöße in der Lieferkette. Öffentlich zugänglich gemäß LkSG.')}
              </p>
              <span className="inline-flex items-center gap-1 text-sm font-medium text-primary transition-colors group-hover:text-primary-dark">
                {t('home.start_report', 'Meldung starten')}
                <ArrowRightIcon />
              </span>
            </button>
          ))}
        </div>
      </section>

      {/* Mailbox access section */}
      <section aria-labelledby="mailbox-heading">
        <h2
          id="mailbox-heading"
          className="mb-4 text-lg font-semibold text-neutral-900 sm:text-xl"
        >
          {t('home.mailbox_heading', 'Bereits eine Meldung abgegeben?')}
        </h2>

        <div className="rounded-xl border border-neutral-200 bg-white p-6">
          <p className="mb-4 text-sm text-neutral-600">
            {t(
              'home.mailbox_text',
              'Greifen Sie auf Ihr sicheres Postfach zu, um Nachrichten zu lesen, den Status Ihrer Meldung zu prüfen oder neue Informationen hinzuzufügen.',
            )}
          </p>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => navigate('/mailbox/login')}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-dark"
            >
              {t('home.mailbox_login', 'Zum Postfach')}
            </button>
            <button
              type="button"
              onClick={() => navigate('/magic-link')}
              className="inline-flex items-center gap-2 rounded-lg border border-neutral-300 bg-white px-4 py-2.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
            >
              {t('home.magic_link', 'Login per E-Mail-Link')}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
