import { useAuth as useOidcAuth } from 'react-oidc-context';
import { useCallback, useEffect, useMemo, useState } from 'react';

/** SessionStorage key tracking whether 2FA was completed this session. */
const TWO_FACTOR_COMPLETED_KEY = 'hwgs_2fa_completed';

/**
 * Admin user roles as defined by the RBAC system.
 *
 * Roles:
 *   system_admin  – Full system access across all tenants
 *   tenant_admin  – Tenant-scoped management (users, categories, settings)
 *   handler       – Full case access within assigned tenant
 *   reviewer      – Access to assigned cases only
 *   auditor       – Read-only access to audit logs and case data
 */
export type AdminRole =
  | 'system_admin'
  | 'tenant_admin'
  | 'handler'
  | 'reviewer'
  | 'auditor';

interface AuthUser {
  /** Unique user identifier (sub claim from OIDC token) */
  id: string;
  /** User email from OIDC profile */
  email: string;
  /** Display name from OIDC profile */
  name: string;
  /** Role assigned in the backend user table, mapped from OIDC email */
  role: AdminRole | null;
  /** Tenant ID the user belongs to (null for system_admin) */
  tenantId: string | null;
  /** Whether this user is a designated custodian (4-eyes principle) */
  is_custodian: boolean;
  /** Whether TOTP two-factor authentication is enabled for this user */
  totp_enabled: boolean;
}

interface UseAuthReturn {
  /** Whether the OIDC session is still loading */
  isLoading: boolean;
  /** Whether the user has an active, valid OIDC session */
  isAuthenticated: boolean;
  /** Parsed user info from the OIDC token and profile claims */
  user: AuthUser | null;
  /** Shorthand for user.role */
  userRole: AdminRole | null;
  /** Raw OIDC access token for API calls */
  accessToken: string | null;
  /** Initiate OIDC login (Authorization Code Flow + PKCE) */
  login: () => Promise<void>;
  /** End the OIDC session and redirect to post-logout URI */
  logout: () => Promise<void>;
  /** Check if the current user has at least the given role level */
  hasRole: (role: AdminRole) => boolean;
  /** Whether the user must complete a TOTP 2FA challenge before proceeding */
  twoFactorPending: boolean;
  /** Short-lived challenge token for TOTP verification (from OIDC claims) */
  challengeToken: string | null;
  /** Mark the current 2FA challenge as completed for this session */
  completeTwoFactor: () => void;
}

const ROLE_HIERARCHY: Record<string, number> = {
  system_admin: 50,
  tenant_admin: 40,
  handler: 30,
  reviewer: 20,
  auditor: 10,
};

/**
 * Convenience hook wrapping react-oidc-context with app-specific logic.
 *
 * Provides typed user info, role checking, and login/logout actions.
 * The user's role and tenant are resolved from custom claims added
 * by the backend during token exchange, or from the ID token profile.
 */
export function useAuth(): UseAuthReturn {
  const oidc = useOidcAuth();

  const user = useMemo<AuthUser | null>(() => {
    if (!oidc.user?.profile) return null;

    const profile = oidc.user.profile;

    return {
      id: profile.sub,
      email: (profile.email as string) ?? '',
      name: (profile.name as string) ?? (profile.preferred_username as string) ?? '',
      role: (profile['app_role'] as AdminRole) ?? null,
      tenantId: (profile['tenant_id'] as string) ?? null,
      is_custodian: (profile['is_custodian'] as boolean) ?? false,
      totp_enabled: (profile['totp_enabled'] as boolean) ?? false,
    };
  }, [oidc.user?.profile]);

  /** Challenge token from sessionStorage — set by onSigninCallback in main.tsx
   *  after calling the backend's 2FA check endpoint.
   *
   *  Uses useState + useEffect + custom DOM event instead of useMemo to handle
   *  the race condition where react-oidc-context sets isAuthenticated=true
   *  before the async checkTwoFactorStatus() fetch completes. */
  const [challengeToken, setChallengeToken] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem('hwgs_totp_challenge');
    } catch {
      return null;
    }
  });

  useEffect(() => {
    if (!oidc.isAuthenticated) {
      setChallengeToken(null);
      return;
    }
    // Re-read sessionStorage (handles page refresh where token already exists)
    const readToken = () => {
      try {
        setChallengeToken(sessionStorage.getItem('hwgs_totp_challenge'));
      } catch {
        /* ignore */
      }
    };
    readToken();
    // Listen for the custom event dispatched after async 2FA check completes
    window.addEventListener('hwgs_totp_challenge_set', readToken);
    return () => window.removeEventListener('hwgs_totp_challenge_set', readToken);
  }, [oidc.isAuthenticated]);

  /** Tracks whether the user has already completed 2FA this session. */
  const [twoFactorCompleted, setTwoFactorCompleted] = useState<boolean>(() => {
    try {
      return sessionStorage.getItem(TWO_FACTOR_COMPLETED_KEY) === 'true';
    } catch {
      return false;
    }
  });

  /** True when the user is authenticated but still needs to pass the 2FA challenge. */
  const twoFactorPending = useMemo(
    () => !!challengeToken && !twoFactorCompleted,
    [challengeToken, twoFactorCompleted],
  );

  /** Persist 2FA completion for the remainder of this browser session. */
  const completeTwoFactor = useCallback(() => {
    try {
      sessionStorage.setItem(TWO_FACTOR_COMPLETED_KEY, 'true');
      sessionStorage.removeItem('hwgs_totp_challenge');
    } catch {
      // Silently ignore storage errors (e.g. private browsing quota)
    }
    setChallengeToken(null);
    setTwoFactorCompleted(true);
  }, []);

  const login = useCallback(async () => {
    await oidc.signinRedirect();
  }, [oidc]);

  const logout = useCallback(async () => {
    // Clear 2FA session flag and challenge token before redirecting
    // to prevent bypass on shared computers
    try {
      sessionStorage.removeItem(TWO_FACTOR_COMPLETED_KEY);
      sessionStorage.removeItem('hwgs_totp_challenge');
    } catch {
      // Silently ignore storage errors (e.g. private browsing quota)
    }
    await oidc.signoutRedirect();
  }, [oidc]);

  const hasRole = useCallback(
    (role: AdminRole): boolean => {
      const requiredLevel = ROLE_HIERARCHY[role] ?? 0;
      const userLevel = ROLE_HIERARCHY[user?.role ?? ''] ?? 0;
      return userLevel >= requiredLevel;
    },
    [user?.role],
  );

  return {
    isLoading: oidc.isLoading,
    isAuthenticated: oidc.isAuthenticated,
    user,
    userRole: user?.role ?? null,
    accessToken: oidc.user?.access_token ?? null,
    login,
    logout,
    hasRole,
    twoFactorPending,
    challengeToken,
    completeTwoFactor,
  };
}
