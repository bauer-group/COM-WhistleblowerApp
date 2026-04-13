import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import deCommon from './de/common.json';
import deReport from './de/report.json';
import deMailbox from './de/mailbox.json';
import enCommon from './en/common.json';
import enReport from './en/report.json';
import enMailbox from './en/mailbox.json';

/**
 * i18next configuration for the reporter frontend.
 *
 * - Namespace-based organization: common, report, mailbox
 * - Supported languages: DE (default), EN
 * - Fallback chain: selected language -> German
 * - Translations bundled inline (no HTTP requests)
 * - Language detection from navigator (no localStorage in anonymous mode)
 */
i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    supportedLngs: ['de', 'en'],
    fallbackLng: 'de',
    defaultNS: 'common',
    ns: ['common', 'report', 'mailbox'],

    resources: {
      de: {
        common: deCommon,
        report: deReport,
        mailbox: deMailbox,
      },
      en: {
        common: enCommon,
        report: enReport,
        mailbox: enMailbox,
      },
    },

    detection: {
      // Only detect from navigator — no localStorage/cookies in anonymous mode
      order: ['navigator', 'htmlTag'],
      caches: [],
    },

    interpolation: {
      escapeValue: false, // React already escapes by default
    },

    react: {
      useSuspense: true,
    },
  });

export default i18n;
