import { Routes, Route, Navigate } from 'react-router';
import { Suspense, lazy } from 'react';
import type { ReactNode } from 'react';
import AuthGuard from '@/components/AuthGuard';
import { useAuth } from '@/hooks/useAuth';
import TwoFactorChallenge from '@/components/TwoFactorChallenge';

const Dashboard = lazy(() => import('@/pages/Dashboard'));
const CaseList = lazy(() => import('@/pages/CaseList'));
const CaseDetail = lazy(() => import('@/pages/CaseDetail'));
const UserManagement = lazy(() => import('@/pages/UserManagement'));
const TenantManagement = lazy(() => import('@/pages/TenantManagement'));
const CategoryManagement = lazy(() => import('@/pages/CategoryManagement'));
const AuditLog = lazy(() => import('@/pages/AuditLog'));
const Settings = lazy(() => import('@/pages/Settings'));

function LoadingFallback() {
  return (
    <div
      className="flex min-h-screen items-center justify-center"
      role="status"
      aria-label="Laden..."
    >
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
    </div>
  );
}

/**
 * Intercepts the render tree when a TOTP 2FA challenge is pending.
 *
 * After OIDC login, if the backend signals that 2FA verification is
 * required (via a `totp_challenge_token` claim), this gate replaces
 * all route content with the TwoFactorChallenge interstitial.
 * Once the user submits a valid TOTP code, the session continues
 * normally.
 */
function TwoFactorGate({ children }: { children: ReactNode }) {
  const { isAuthenticated, twoFactorPending, challengeToken, completeTwoFactor, logout } = useAuth();

  if (isAuthenticated && twoFactorPending && challengeToken) {
    return (
      <TwoFactorChallenge
        challengeToken={challengeToken}
        onSuccess={completeTwoFactor}
        onCancel={() => void logout()}
      />
    );
  }

  return <>{children}</>;
}

export default function App() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      {/* Skip-to-main-content link for keyboard/screen reader users (WCAG 2.4.1) */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-[999] focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-white focus:shadow-lg"
      >
        Skip to main content
      </a>
      <TwoFactorGate>
      <div id="main-content">
      <Routes>
        {/* All admin routes require OIDC authentication */}
        <Route
          path="/"
          element={
            <AuthGuard>
              <Dashboard />
            </AuthGuard>
          }
        />
        <Route
          path="/cases"
          element={
            <AuthGuard>
              <CaseList />
            </AuthGuard>
          }
        />
        <Route
          path="/cases/:caseId"
          element={
            <AuthGuard>
              <CaseDetail />
            </AuthGuard>
          }
        />
        <Route
          path="/users"
          element={
            <AuthGuard requiredRole="tenant_admin">
              <UserManagement />
            </AuthGuard>
          }
        />
        <Route
          path="/tenants"
          element={
            <AuthGuard requiredRole="system_admin">
              <TenantManagement />
            </AuthGuard>
          }
        />
        <Route
          path="/categories"
          element={
            <AuthGuard requiredRole="tenant_admin">
              <CategoryManagement />
            </AuthGuard>
          }
        />
        <Route
          path="/audit"
          element={
            <AuthGuard requiredRole="auditor">
              <AuditLog />
            </AuthGuard>
          }
        />
        <Route
          path="/settings"
          element={
            <AuthGuard requiredRole="tenant_admin">
              <Settings />
            </AuthGuard>
          }
        />

        {/* OIDC callback — handled by react-oidc-context automatically */}
        <Route path="/callback" element={<LoadingFallback />} />

        {/* Fallback: redirect unknown routes to dashboard */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </div>
      </TwoFactorGate>
    </Suspense>
  );
}
