import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/AppShell';
import { Spinner } from '@/components/ui';
import { AuthProvider, useAuth } from '@/lib/auth';
import { JobsProvider } from '@/lib/jobs';
import { ToastProvider } from '@/lib/toast';
import Accounts from '@/pages/Accounts';
import CampaignDetail from '@/pages/CampaignDetail';
import Campaigns from '@/pages/Campaigns';
import Dashboard from '@/pages/Dashboard';
import Jobs from '@/pages/Jobs';
import Leads from '@/pages/Leads';
import Login from '@/pages/Login';
import NotFound from '@/pages/NotFound';
import SalesNav from '@/pages/SalesNav';
import Settings from '@/pages/Settings';
import Threads from '@/pages/Threads';

function Shell() {
  const { me, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center gap-3 bg-canvas text-muted" role="status">
        <Spinner />
        <span>Loading…</span>
      </div>
    );
  }

  if (!me) return <Login />;

  /* Admin-only screens are registered for everyone; the API enforces the
     permission, and the sidebar hides links a user cannot use. */
  return (
    <JobsProvider>
      <HashRouter>
        <AppShell>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/campaigns" element={<Campaigns />} />
            <Route path="/campaign/:id" element={<CampaignDetail />} />
            <Route path="/leads" element={<Leads />} />
            <Route path="/threads" element={<Threads />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/salesnav" element={<SalesNav />} />
            <Route path="/settings" element={<Settings />} />
            {/* Users lives inline in Settings now; keep the route as a redirect. */}
            <Route path="/users" element={<Navigate to="/settings" replace />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AppShell>
      </HashRouter>
    </JobsProvider>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <Shell />
      </AuthProvider>
    </ToastProvider>
  );
}
