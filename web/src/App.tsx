import { Routes, Route, Navigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, User } from './api';
import { createContext, useContext, useEffect } from 'react';
import { LoginPage } from './pages/LoginPage';
import { LibraryPage } from './pages/LibraryPage';
import { ConversationPage } from './pages/ConversationPage';
import { ExplorePage } from './pages/ExplorePage';
import { SummariesPage } from './pages/SummariesPage';
import { InsightsPage } from './pages/InsightsPage';
import { HypothesesPage } from './pages/HypothesesPage';
import { ContactPage } from './pages/ContactPage';
import { CompanyPage } from './pages/CompanyPage';
import { DigestPage } from './pages/DigestPage';
import { SimulatorPage } from './pages/SimulatorPage';
import { DecisionsPage } from './pages/DecisionsPage';
import { MeetingsPage } from './pages/MeetingsPage';
import { SettingsPage } from './pages/SettingsPage';
import { Layout } from './components/Layout';

// ─── Auth context ───

interface AuthContextValue {
  user: User;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthGate');
  return ctx;
}

export function useAuthOptional(): AuthContextValue | null {
  return useContext(AuthContext);
}

// ─── Global 401 interceptor ───

function useGlobal401Handler() {
  const queryClient = useQueryClient();

  useEffect(() => {
    const unsubQuery = queryClient.getQueryCache().subscribe((event) => {
      if (event.type === 'updated' && event.query.state.status === 'error') {
        const err = event.query.state.error;
        if (err instanceof ApiError && err.status === 401) {
          queryClient.setQueryData(['me'], null);
        }
      }
    });

    const unsubMutation = queryClient.getMutationCache().subscribe((event) => {
      if (event.type === 'updated' && event.mutation?.state.status === 'error') {
        const err = event.mutation.state.error;
        if (err instanceof ApiError && err.status === 401) {
          queryClient.setQueryData(['me'], null);
        }
      }
    });

    const handleFocus = () => {
      queryClient.invalidateQueries({ queryKey: ['me'] });
    };
    window.addEventListener('focus', handleFocus);

    return () => {
      unsubQuery();
      unsubMutation();
      window.removeEventListener('focus', handleFocus);
    };
  }, [queryClient]);
}

// ─── AuthGate ───

function AuthGate({ children }: { children: React.ReactNode }) {
  const { data: user, isLoading, error } = useQuery({
    queryKey: ['me'],
    queryFn: () => api.me(),
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="w-3 h-3 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" />
      </div>
    );
  }

  if (error || !user) {
    return <LoginPage />;
  }

  return <AuthContext.Provider value={{ user }}>{children}</AuthContext.Provider>;
}

// ─── App ───

export function App() {
  useGlobal401Handler();

  return (
    <Routes>
      {/* AuthGate wraps Layout so the whole shell (incl. the top-bar avatar/menu)
          is inside AuthContext. The gate runs once; pages render via <Outlet/>. */}
      <Route
        element={
          <AuthGate>
            <Layout />
          </AuthGate>
        }
      >
        <Route path="/" element={<LibraryPage />} />
        <Route path="/inbox" element={<Navigate to="/?tab=inbox" replace />} />
        <Route path="/conversations/:id" element={<ConversationPage />} />
        <Route path="/contacts/:id" element={<ContactPage />} />
        <Route path="/companies/:id" element={<CompanyPage />} />
        <Route path="/explore" element={<ExplorePage />} />
        <Route path="/summaries" element={<SummariesPage />} />
        <Route path="/hypotheses" element={<HypothesesPage />} />
        <Route path="/insights" element={<InsightsPage />} />
        <Route path="/digest" element={<DigestPage />} />
        <Route path="/simulator" element={<SimulatorPage />} />
        <Route path="/decisions" element={<DecisionsPage />} />
        <Route path="/meetings" element={<MeetingsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
