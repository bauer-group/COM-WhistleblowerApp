import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from 'react-oidc-context';
import { WebStorageStateStore, User } from 'oidc-client-ts';
import App from './App';
import './i18n';
import './main.css';

/** SessionStorage key for the TOTP challenge token issued by the backend. */
const TOTP_CHALLENGE_KEY = 'hwgs_totp_challenge';

/**
 * After OIDC login completes, call the backend's 2FA check endpoint
 * to determine whether this user must complete a TOTP challenge.
 *
 * If the user has TOTP enabled, the backend returns a short-lived
 * challenge token that is stored in sessionStorage for the
 * TwoFactorGate component to pick up.
 */
async function checkTwoFactorStatus(accessToken: string): Promise<void> {
  try {
    const apiBase = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';
    const resp = await fetch(`${apiBase}/auth/2fa-check`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${accessToken}`,
      },
    });

    if (!resp.ok) {
      console.error('2FA check request failed:', resp.status);
      return;
    }

    const data = await resp.json();
    if (data.requires_2fa && data.challenge_token) {
      sessionStorage.setItem(TOTP_CHALLENGE_KEY, data.challenge_token);
      // Signal the useAuth hook that the challenge token is available
      window.dispatchEvent(new CustomEvent('hwgs_totp_challenge_set'));
    }
  } catch (e) {
    console.error('Backend 2FA check failed:', e);
  }
}

/**
 * OIDC configuration for Microsoft Entra ID.
 *
 * Uses Authorization Code Flow with PKCE (Proof Key for Code Exchange)
 * as recommended for public (browser-based) clients.
 *
 * Environment variables are injected at build time via Vite.
 */
const oidcConfig = {
  authority: import.meta.env.VITE_OIDC_AUTHORITY as string,
  client_id: import.meta.env.VITE_OIDC_CLIENT_ID as string,
  redirect_uri: `${window.location.origin}/admin/callback`,
  post_logout_redirect_uri: `${window.location.origin}/admin/`,
  scope: 'openid profile email',
  response_type: 'code',
  automaticSilentRenew: true,
  /** Store OIDC state in sessionStorage for security (cleared on tab close) */
  userStore: new WebStorageStateStore({ store: window.sessionStorage }),

  /**
   * Called after react-oidc-context completes the OIDC code exchange.
   * We use this hook to call the backend and check if the user needs
   * to complete a TOTP 2FA challenge before proceeding.
   */
  onSigninCallback: async (user: User | void): Promise<void> => {
    if (user?.access_token) {
      await checkTwoFactorStatus(user.access_token);
    }
    // Clean up the authorization code from the URL
    window.history.replaceState({}, '', window.location.pathname);
  },
};

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      retry: 1,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 0,
    },
  },
});

const rootElement = document.getElementById('root');

if (!rootElement) {
  throw new Error('Root element not found. Ensure index.html contains <div id="root"></div>.');
}

createRoot(rootElement).render(
  <StrictMode>
    <AuthProvider {...oidcConfig}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename="/admin">
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </AuthProvider>
  </StrictMode>,
);
