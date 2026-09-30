import i18next from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en.json";
import es from "./locales/es.json";

export const SUPPORTED_LANGUAGES = ["en", "es"] as const;
export type Language = (typeof SUPPORTED_LANGUAGES)[number];

/** localStorage key for the user's language choice (WP-02 persistence contract). */
export const LANGUAGE_STORAGE_KEY = "kosmo.language";

const FALLBACK_LANGUAGE: Language = "en";

function isSupportedLanguage(value: string): value is Language {
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(value);
}

/**
 * Initial language: stored choice first, then the browser preference, then
 * the fallback. Resolving here keeps the first render already localized
 * (no language flicker after mount).
 */
function detectInitialLanguage(): Language {
  try {
    const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (stored && isSupportedLanguage(stored)) return stored;
  } catch {
    // localStorage can be unavailable (privacy modes); fall through.
  }

  const browserLanguage =
    typeof navigator !== "undefined" ? navigator.language : undefined;
  const shortCode = browserLanguage?.toLowerCase().split("-")[0] ?? "";
  if (isSupportedLanguage(shortCode)) return shortCode;

  return FALLBACK_LANGUAGE;
}

function initI18n(): void {
  if (i18next.isInitialized) return;

  void i18next.use(initReactI18next).init({
    resources: {
      en: { translation: en },
      es: { translation: es },
    },
    lng: detectInitialLanguage(),
    fallbackLng: FALLBACK_LANGUAGE,
    supportedLngs: [...SUPPORTED_LANGUAGES],
    // React escapes rendered text nodes itself.
    interpolation: { escapeValue: false },
    // Resources are bundled with the app, so initialization is synchronous;
    // no Suspense boundary is required while translating.
    react: { useSuspense: false },
  });
}

/** Switch the UI language and persist the choice for future visits. */
export function changeLanguage(next: Language): void {
  void i18next.changeLanguage(next);
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, next);
  } catch {
    // Persistence is best-effort; the UI still switches.
  }
}

initI18n();

// Typed translation keys derived from the English catalog shape.
declare module "i18next" {
  interface CustomTypeOptions {
    resources: {
      translation: typeof en;
    };
  }
}
