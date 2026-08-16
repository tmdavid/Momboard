import { Routes, Route, Navigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, User } from './api';
import { createContext, useContext, useEffect } from 'react';
import { LoginPage } from './pages/LoginPage';
import { LibraryPage } from './pages/LibraryPage';
import { ConversationPage } from './pages/ConversationPage';
import { ExplorePage } from './pages/ExplorePage';
import { InsightsPage } from './pages/InsightsPage';
import { HypothesesPage } from './pages/HypothesesPage';
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
    // Subscribe to query cache — detect 401 errors from any query
    const unsubQuery = queryClient.getQueryCache().subscribe((event) => {
      if (event.type === 'updated' && event.query.state.status === 'error') {
        const err = event.query.state.error;
        if (err instanceof ApiError && err.status === 401) {
          // Force AuthGate to show login by clearing the user data
          queryClient.setQueryData(['me'], null);
        }
      }
    });

    // Subscribe to mutation cache — detect 401 errors from any mutation
    const unsubMutation = queryClient.getMutationCache().subscribe((event) => {
      if (event.type === 'updated' && event.mutation?.state.status === 'error') {
        const err = event.mutation.state.error;
        if (err instanceof ApiError && err.status === 401) {
          queryClient.setQueryData(['me'], null);
        }
      }
    });

    // Listen for window focus to re-validate session
    // TanStack Query v5 only listens to visibilitychange, so we also listen on focus
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
      <Route element={<Layout />}>
        <Route
          path="/"
          element={
            <AuthGate>
              <LibraryPage />
            </AuthGate>
          }
        />
        <Route
          path="/conversations/:id"
          element={
            <AuthGate>
              <ConversationPage />
            </AuthGate>
          }
        />
        <Route
          path="/explore"
          element={
            <AuthGate>
              <ExplorePage />
            </AuthGate>
          }
        />
        <Route
          path="/hypotheses"
          element={
            <AuthGate>
              <HypothesesPage />
            </AuthGate>
          }
        />
        <Route
          path="/insights"
          element={
            <AuthGate>
              <InsightsPage />
            </AuthGate>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
