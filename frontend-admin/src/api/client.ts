import axios from 'axios';
import { User } from 'oidc-client-ts';

/**
 * Axios instance for the admin API.
 *
 * Base URL is resolved from the Vite proxy in development (/api)
 * and from the VITE_API_BASE_URL env var in production.
 *
 * The OIDC token interceptor automatically attaches the Bearer token
 * from the current user session to every outgoing request.
 */
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api/v1',
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  },
  timeout: 30_000,
});

/**
 * Resolve the current OIDC access token from sessionStorage.
 *
 * react-oidc-context stores user state under a key derived from
 * the OIDC authority + client_id. We read it directly to avoid
 * coupling the axios instance to the React component tree.
 */
function getAccessToken(): string | null {
  const authority = import.meta.env.VITE_OIDC_AUTHORITY as string;
  const clientId = import.meta.env.VITE_OIDC_CLIENT_ID as string;

  const storageKey = `oidc.user:${authority}:${clientId}`;
  const raw = sessionStorage.getItem(storageKey);

  if (!raw) return null;

  try {
    const user = User.fromStorageString(raw);
    return user.expired ? null : user.access_token;
  } catch {
    return null;
  }
}

/**
 * Request interceptor: attach OIDC Bearer token.
 */
apiClient.interceptors.request.use((config) => {
  const token = getAccessToken();

  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  return config;
});

/**
 * Response interceptor: handle common error codes.
 */
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error) && error.response) {
      const { status } = error.response;

      if (status === 401) {
        // Token expired or invalid — redirect to OIDC login
        // The AuthGuard component will handle the actual redirect
      }

      if (status === 403) {
        // Insufficient permissions — let calling code display an error
      }

      if (status === 429) {
        // Rate limited — surface a user-friendly message
      }
    }

    return Promise.reject(error);
  },
);

export default apiClient;
