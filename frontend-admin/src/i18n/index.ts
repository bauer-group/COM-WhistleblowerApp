import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import deCommon from './de/common.json';
import deCases from './de/cases.json';
import deAdmin from './de/admin.json';
import enCommon from './en/common.json';
import enCases from './en/cases.json';
import enAdmin from './en/admin.json';

/**
 * i18next configuration for the admin frontend.
 *
 * - Namespace-based organization: common, cases, admin
 * - Supported languages: DE (default), EN
 * - Fallback chain: selected language -> German
 * - Translations bundled inline (no HTTP requests, avoids
 *   path-prefix issues with /admin/ routing)
 * - Language detection from navigator and localStorage
 */
i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    supportedLngs: ['de', 'en'],
    fallbackLng: 'de',
    defaultNS: 'common',
    ns: ['common', 'cases', 'admin'],

    resources: {
      de: {
        common: deCommon,
        cases: deCases,
        admin: deAdmin,
      },
      en: {
        common: enCommon,
        cases: enCases,
        admin: enAdmin,
      },
    },

    detection: {
      order: ['localStorage', 'navigator', 'htmlTag'],
      caches: ['localStorage'],
    },

    interpolation: {
      escapeValue: false, // React already escapes by default
    },

    react: {
      useSuspense: true,
    },
  });

export default i18n;
