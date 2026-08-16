import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const queryClient = useQueryClient();

  const loginMutation = useMutation({
    mutationFn: () => api.login(email, password),
    onSuccess: (user) => {
      queryClient.setQueryData(['me'], user);
    },
  });

  return (
    <div className="flex h-screen items-center justify-center bg-page">
      <form
        className="w-80 bg-surface border border-hairline rounded-xl p-6 shadow-sm"
        onSubmit={(e) => {
          e.preventDefault();
          loginMutation.mutate();
        }}
      >
        <h1 className="text-xl font-bold tracking-tight mb-1">
          Mom<span className="text-accent">Board</span>
        </h1>
        <p className="text-muted text-sm mb-5">Sign in to continue</p>

        <label htmlFor="login-email" className="block text-xs font-semibold text-ink-2 mb-1">Email</label>
        <input
          id="login-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink text-sm mb-3 outline-none focus:border-accent"
          required
          autoFocus
        />

        <label htmlFor="login-password" className="block text-xs font-semibold text-ink-2 mb-1">Password</label>
        <input
          id="login-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink text-sm mb-4 outline-none focus:border-accent"
          required
        />

        {loginMutation.error && (
          <p className="text-crit text-xs mb-3">Invalid credentials. Try again.</p>
        )}

        <button
          type="submit"
          disabled={loginMutation.isPending}
          className="btn btn-primary w-full"
        >
          {loginMutation.isPending ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
