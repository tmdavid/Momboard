import { useQuery } from '@tanstack/react-query';
import { Outlet } from 'react-router-dom';
import { AppHeader } from './AppHeader';
import { AppSidebar } from './AppSidebar';

export function Layout() {
  // Pending inbox count for the Library sidebar badge.
  const { data: inboxData } = useQuery({
    queryKey: ['inbox', 'pending_import'],
    queryFn: async () => {
      const res = await fetch('/api/inbox?status=pending_import', { credentials: 'include' });
      if (!res.ok) return { total: 0 };
      return res.json() as Promise<{ total: number }>;
    },
    staleTime: 30_000,
  });
  const pendingCount = inboxData?.total ?? 0;

  return (
    <div className="min-h-screen flex flex-col bg-page text-ink-2">
      <AppHeader />
      {/* Below ~1100px the sidebar wraps under the content (flex-wrap). */}
      <div className="flex-1 flex flex-wrap items-stretch">
        <div className="flex-[1_1_200px] max-w-[220px]">
          <AppSidebar pendingCount={pendingCount} />
        </div>
        {/* Content area. Each page still renders its own <main>; as pages are
            redesigned they adopt the shell's 24px padding directly. Kept as a
            plain div here to avoid nesting <main> elements during the migration. */}
        <div className="flex-[999_1_640px] min-w-0 flex flex-col">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
