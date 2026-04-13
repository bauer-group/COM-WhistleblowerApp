import type { ReactNode } from 'react';
import { useAuth } from '@/hooks/useAuth';

/**
 * Admin roles in descending privilege order.
 *
 * The system supports 5 roles:
 *   system_admin > tenant_admin > handler > reviewer > auditor
 *
 * Higher-privilege roles implicitly satisfy lower-privilege checks.
 */
const ROLE_HIERARCHY: Record<string, number> = {
  system_admin: 50,
  tenant_admin: 40,
  handler: 30,
  reviewer: 20,
  auditor: 10,
};

interface AuthGuardProps {
  children: ReactNode;
  /** If set, user must have at least this role level to access the route */
  requiredRole?: string;
}

/**
 * Protects admin routes by verifying OIDC authentication and optional role.
 *
 * - If the OIDC session is loading, shows a spinner.
 * - If the user is not authenticated, triggers the OIDC login redirect.
 * - If a `requiredRole` is specified and the user's role is insufficient,
 *   shows an access denied message.
 */
export default function AuthGuard({ children, requiredRole }: AuthGuardProps) {
  const { isAuthenticated, isLoading, login, userRole } = useAuth();

  if (isLoading) {
    return (
      <div
        className="flex min-h-screen items-center justify-center"
        role="status"
        aria-label="Authentifizierung wird geprüft..."
      >
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  if (!isAuthenticated) {
    // Trigger OIDC Authorization Code Flow + PKCE
    void login();

    return (
      <div
        className="flex min-h-screen items-center justify-center"
        role="status"
        aria-label="Weiterleitung zur Anmeldung..."
      >
        <p className="text-neutral-600">Weiterleitung zur Anmeldung…</p>
      </div>
    );
  }

  if (requiredRole) {
    const requiredLevel = ROLE_HIERARCHY[requiredRole] ?? 0;
    const userLevel = ROLE_HIERARCHY[userRole ?? ''] ?? 0;

    if (userLevel < requiredLevel) {
      return (
        <div className="flex min-h-screen items-center justify-center" role="alert">
          <div className="max-w-md rounded-lg border border-danger/20 bg-danger/5 p-8 text-center">
            <h1 className="mb-2 text-xl font-semibold text-danger">Zugriff verweigert</h1>
            <p className="text-neutral-600">
              Sie verfügen nicht über die erforderlichen Berechtigungen für diese Seite.
            </p>
          </div>
        </div>
      );
    }
  }

  return <>{children}</>;
}
