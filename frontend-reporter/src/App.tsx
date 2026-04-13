import { Routes, Route } from 'react-router';
import { Suspense, lazy, useEffect } from 'react';

const HomePage = lazy(() => import('@/pages/HomePage'));
const ReportWizard = lazy(() => import('@/pages/ReportWizard'));
const ReportSuccess = lazy(() => import('@/pages/ReportSuccess'));
const MailboxLogin = lazy(() => import('@/pages/MailboxLogin'));
const Mailbox = lazy(() => import('@/pages/Mailbox'));
const MagicLinkRequest = lazy(() => import('@/pages/MagicLinkRequest'));
const MagicLinkVerify = lazy(() => import('@/pages/MagicLinkVerify'));

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

export default function App() {
  useEffect(() => {
    const handleBeforeUnload = () => {
      /* Anti-forensics: clear sensitive data from memory on page unload */
      try {
        sessionStorage.clear();
      } catch {
        // Silently ignore if storage access fails
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, []);

  return (
    <Suspense fallback={<LoadingFallback />}>
      <a href="#main-content" className="skip-link">
        Zum Inhalt springen
      </a>
      <main id="main-content" autoComplete="off">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/report" element={<ReportWizard />} />
          <Route path="/report/success" element={<ReportSuccess />} />
          <Route path="/mailbox/login" element={<MailboxLogin />} />
          <Route path="/mailbox" element={<Mailbox />} />
          <Route path="/magic-link" element={<MagicLinkRequest />} />
          <Route path="/magic-link/verify" element={<MagicLinkVerify />} />
        </Routes>
      </main>
    </Suspense>
  );
}
