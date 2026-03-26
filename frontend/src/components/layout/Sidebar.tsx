import { Link, useRouterState } from '@tanstack/react-router';
import {
  LayoutDashboard,
  Search,
  Upload,
  FolderOpen,
  Tags,
  GitBranch,
  Brain,
  Settings,
  ChevronLeft,
  Database,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import { useUiStore } from '@/stores/uiStore';

interface NavItem {
  label: string;
  path: string;
  icon: typeof LayoutDashboard;
}

const navItems: NavItem[] = [
  { label: 'Dashboard', path: '/dashboard', icon: LayoutDashboard },
  { label: 'Search', path: '/search', icon: Search },
  { label: 'Upload', path: '/upload', icon: Upload },
  { label: 'Vault', path: '/vault', icon: FolderOpen },
  { label: 'Tags', path: '/tags', icon: Tags },
  { label: 'Graph', path: '/graph', icon: GitBranch },
  { label: 'Knowledge', path: '/knowledge', icon: Brain },
  { label: 'Admin', path: '/admin', icon: Settings },
];

export function Sidebar() {
  const sidebarOpen = useUiStore((s) => s.sidebarOpen);
  const toggleSidebar = useUiStore((s) => s.toggleSidebar);
  const routerState = useRouterState();
  const currentPath = routerState.location.pathname;

  return (
    <aside
      className={cn(
        'flex h-screen flex-col border-r border-surface-700 bg-surface-900 transition-all duration-200',
        sidebarOpen ? 'w-64' : 'w-16',
      )}
    >
      {/* Logo */}
      <div className="flex h-16 items-center justify-between border-b border-surface-700 px-4">
        <div className="flex items-center gap-3 overflow-hidden">
          <Database className="h-7 w-7 shrink-0 text-primary-500" />
          {sidebarOpen && (
            <span className="text-lg font-bold text-zinc-100">AgentLake</span>
          )}
        </div>
        <button
          type="button"
          onClick={toggleSidebar}
          className="rounded-md p-1 text-surface-400 transition-colors hover:bg-surface-800 hover:text-zinc-100"
        >
          <ChevronLeft
            className={cn(
              'h-5 w-5 transition-transform',
              !sidebarOpen && 'rotate-180',
            )}
          />
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 overflow-y-auto px-2 py-4">
        {navItems.map((item) => {
          const isActive =
            currentPath === item.path ||
            (item.path !== '/' && currentPath.startsWith(item.path));
          const Icon = item.icon;

          return (
            <Link
              key={item.path}
              to={item.path}
              className={cn(
                'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-primary-500/10 text-primary-400'
                  : 'text-surface-400 hover:bg-surface-800 hover:text-zinc-100',
                !sidebarOpen && 'justify-center px-0',
              )}
              title={sidebarOpen ? undefined : item.label}
            >
              <Icon className="h-5 w-5 shrink-0" />
              {sidebarOpen && <span>{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      {sidebarOpen && (
        <div className="border-t border-surface-700 px-4 py-3">
          <p className="text-xs text-surface-500">AgentLake v0.1.0</p>
        </div>
      )}
    </aside>
  );
}
