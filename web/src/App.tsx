import { Routes, Route, Navigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, User } from './api';
import { createContext, useContext } from 'react';
import { LoginPage } from './pages/LoginPage';
import { LibraryPage } from './pages/LibraryPage';
import { ConversationPage } from './pages/ConversationPage';
import { ExplorePage } from './pages/ExplorePage';
import { InsightsPage } from './pages/InsightsPage';
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
  return (
    <AuthGate>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<LibraryPage />} />
          <Route path="/conversations/:id" element={<ConversationPage />} />
          <Route path="/explore" element={<ExplorePage />} />
          <Route path="/insights" element={<InsightsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthGate>
  );
}
