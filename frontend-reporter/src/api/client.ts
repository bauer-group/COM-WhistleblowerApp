import axios from 'axios';

/**
 * Axios instance for the reporter API.
 *
 * Base URL is resolved from the Vite proxy in development (/api)
 * and from the VITE_API_BASE_URL env var in production.
 *
 * NOTE: No cookies or localStorage are used in anonymous mode.
 * Authentication for the mailbox uses short-lived tokens passed
 * via Authorization header, managed per-request by the API layer.
 */
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api/v1',
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  },
  timeout: 30_000,
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error) && error.response) {
      const { status } = error.response;

      if (status === 401) {
        // Token expired or invalid — let the calling code handle re-auth
      }

      if (status === 429) {
        // Rate limited — surface a user-friendly message
      }
    }

    return Promise.reject(error);
  },
);

export default apiClient;
