/**
 * Hinweisgebersystem – Admin Auth API Functions.
 *
 * All admin-facing API calls for TOTP two-factor authentication
 * management.  Supports the full 2FA lifecycle: initial setup
 * (provisioning URI + backup codes), verification to activate,
 * challenge completion during OIDC login, and disabling 2FA.
 *
 * Authentication is handled automatically by the axios interceptor
 * in ``client.ts`` which attaches the OIDC Bearer token.
 */

import apiClient from '@/api/client';

// ── Response Types ─────────────────────────────────────────────

/** Returned after initiating TOTP setup — contains everything the user needs. */
export interface TOTPSetupResponse {
  /** Base32-encoded shared secret (shown once). */
  secret: string;
  /** otpauth:// URI for QR code generation. */
  provisioning_uri: string;
  /** 10 single-use backup/recovery codes (plaintext, shown once). */
  backup_codes: string[];
}

/** Returned after successfully verifying TOTP and activating 2FA. */
export interface TOTPVerifyResponse {
  enabled: boolean;
  message: string;
}

/** Returned after successfully disabling TOTP 2FA. */
export interface TOTPDisableResponse {
  enabled: boolean;
  message: string;
}

/** Returned after an admin resets another user's TOTP. */
export interface TOTPAdminResetResponse {
  message: string;
}

// ── Request Types ──────────────────────────────────────────────

/** Verify a 6-digit TOTP code to activate 2FA. */
export interface TOTPVerifyRequest {
  /** 6-digit TOTP code from authenticator app. */
  code: string;
}

/** Disable TOTP 2FA — requires current code to confirm identity. */
export interface TOTPDisableRequest {
  /** Current 6-digit TOTP code. */
  code: string;
}

/** Complete the TOTP challenge during OIDC login. */
export interface TOTPChallengeRequest {
  /** Challenge token received from OIDC callback. */
  challenge_token: string;
  /** 6-digit TOTP code or single-use backup code. */
  code: string;
}

// ── TOTP Setup API ─────────────────────────────────────────────

/**
 * Initiate TOTP 2FA setup for the current user.
 *
 * Generates a new TOTP secret, provisioning URI (for QR code),
 * and 10 single-use backup codes.  The secret and backup codes
 * are shown only once — the user must save them before proceeding.
 *
 * Returns 409 Conflict if TOTP is already enabled.
 */
export async function setupTOTP(): Promise<TOTPSetupResponse> {
  const response = await apiClient.post<TOTPSetupResponse>(
    '/auth/totp/setup',
  );
  return response.data;
}

/**
 * Verify a TOTP code and activate 2FA on the current account.
 *
 * The user must enter a valid 6-digit code from their authenticator
 * app to confirm they have correctly configured it.  Once verified,
 * 2FA is permanently enabled until explicitly disabled.
 */
export async function verifyTOTP(
  data: TOTPVerifyRequest,
): Promise<TOTPVerifyResponse> {
  const response = await apiClient.post<TOTPVerifyResponse>(
    '/auth/totp/verify',
    data,
  );
  return response.data;
}

/**
 * Disable TOTP 2FA on the current user account.
 *
 * Requires a valid 6-digit TOTP code to confirm the user's
 * identity before removing 2FA protection.  Clears the TOTP
 * secret and all backup codes.
 */
export async function disableTOTP(
  data: TOTPDisableRequest,
): Promise<TOTPDisableResponse> {
  const response = await apiClient.post<TOTPDisableResponse>(
    '/auth/totp/disable',
    data,
  );
  return response.data;
}

// ── TOTP Challenge API ─────────────────────────────────────────

/**
 * Complete the TOTP 2FA challenge during OIDC login.
 *
 * When a user with 2FA enabled completes OIDC authentication,
 * the backend returns a short-lived challenge token instead of
 * a session.  This endpoint validates the TOTP code (or backup
 * code) and issues the full session JWT.
 *
 * The challenge token expires after 5 minutes.
 */
export async function completeTOTPChallenge(
  data: TOTPChallengeRequest,
): Promise<void> {
  await apiClient.post('/auth/totp/challenge', data);
}

// ── Admin TOTP Management ──────────────────────────────────────

/**
 * Reset TOTP 2FA for another user (admin action).
 *
 * Allows a system_admin or tenant_admin to forcibly disable
 * 2FA on a user's account (e.g. when they lose their device).
 * Creates an audit log entry for the action.
 */
export async function adminResetTOTP(
  userId: string,
): Promise<TOTPAdminResetResponse> {
  const response = await apiClient.post<TOTPAdminResetResponse>(
    `/admin/users/${userId}/totp/reset`,
  );
  return response.data;
}
