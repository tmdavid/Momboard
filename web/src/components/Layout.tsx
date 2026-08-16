import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../App';

export function Layout() {
  const { user } = useAuth();
  const initial = (user.name || user.email)[0].toUpperCase();

  return (
    <div className="flex flex-col h-screen">
      <nav className="flex items-center gap-7 px-7 h-[52px] bg-surface border-b border-hairline flex-none">
        <div className="font-bold tracking-tight">
          Mom<span className="text-accent">Board</span>
        </div>
        <div className="flex gap-1">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              `px-3 py-1.5 rounded-lg text-ink-2 ${isActive ? 'bg-accent-soft text-accent font-semibold' : 'hover:bg-page'}`
            }
          >
            Library
          </NavLink>
          <NavLink
            to="/explore"
            className={({ isActive }) =>
              `px-3 py-1.5 rounded-lg text-ink-2 ${isActive ? 'bg-accent-soft text-accent font-semibold' : 'hover:bg-page'}`
            }
          >
            Explore
          </NavLink>
          <NavLink
            to="/insights"
            className={({ isActive }) =>
              `px-3 py-1.5 rounded-lg text-ink-2 ${isActive ? 'bg-accent-soft text-accent font-semibold' : 'hover:bg-page'}`
            }
          >
            Insights
          </NavLink>
        </div>
        <div className="flex-1" />
        <div className="w-7 h-7 rounded-full bg-accent text-white grid place-items-center text-xs font-semibold">
          {initial}
        </div>
      </nav>
      <Outlet />
    </div>
  );
}
