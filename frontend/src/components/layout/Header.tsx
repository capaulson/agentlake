import { useState } from 'react';
import { useRouterState } from '@tanstack/react-router';
import { Moon, Sun, Key, ChevronRight } from 'lucide-react';
import { useUiStore } from '@/stores/uiStore';
import { useAuthStore } from '@/stores/authStore';
import { cn } from '@/utils/cn';

const routeLabels: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/search': 'Search',
  '/upload': 'Upload',
  '/vault': 'Vault',
  '/tags': 'Tags',
  '/graph': 'Entity Graph',
  '/admin': 'Admin',
  '/documents': 'Document Viewer',
};

function getBreadcrumbs(pathname: string): { label: string; path: string }[] {
  const crumbs: { label: string; path: string }[] = [];

  // Find matching route label
  for (const [path, label] of Object.entries(routeLabels)) {
    if (pathname.startsWith(path)) {
      crumbs.push({ label, path });
      break;
    }
  }

  // Add document ID if on a document page
  if (pathname.startsWith('/documents/')) {
    const id = pathname.split('/')[2];
    if (id) {
      crumbs.push({ label: id.substring(0, 8) + '...', path: pathname });
    }
  }

  return crumbs;
}

export function Header() {
  const darkMode = useUiStore((s) => s.darkMode);
  const toggleDarkMode = useUiStore((s) => s.toggleDarkMode);
  const apiKey = useAuthStore((s) => s.apiKey);
  const setApiKey = useAuthStore((s) => s.setApiKey);
  const clearApiKey = useAuthStore((s) => s.clearApiKey);
  const routerState = useRouterState();
  const [showKeyInput, setShowKeyInput] = useState(false);
  const [keyValue, setKeyValue] = useState('');

  const breadcrumbs = getBreadcrumbs(routerState.location.pathname);

  const handleKeySubmit = () => {
    if (keyValue.trim()) {
      setApiKey(keyValue.trim());
      setKeyValue('');
      setShowKeyInput(false);
    }
  };

  return (
    <header className="flex h-16 items-center justify-between border-b border-surface-700 bg-surface-900/50 px-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-2 text-sm">
        <span className="text-surface-500">AgentLake</span>
        {breadcrumbs.map((crumb) => (
          <span key={crumb.path} className="flex items-center gap-2">
            <ChevronRight className="h-4 w-4 text-surface-600" />
            <span className="font-medium text-zinc-100">{crumb.label}</span>
          </span>
        ))}
      </nav>

      {/* Actions */}
      <div className="flex items-center gap-3">
        {/* API Key */}
        {showKeyInput ? (
          <div className="flex items-center gap-2">
            <input
              type="password"
              value={keyValue}
              onChange={(e) => setKeyValue(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleKeySubmit()}
              placeholder="Enter API key..."
              className="w-48 rounded-md border border-surface-600 bg-surface-800 px-3 py-1.5 text-xs text-zinc-100 placeholder-surface-500 outline-none focus:border-primary-500"
            />
            <button
              type="button"
              onClick={handleKeySubmit}
              className="rounded-md bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700"
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => setShowKeyInput(false)}
              className="rounded-md px-2 py-1.5 text-xs text-surface-400 hover:text-zinc-100"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => {
              if (apiKey) {
                clearApiKey();
              } else {
                setShowKeyInput(true);
              }
            }}
            className={cn(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              apiKey
                ? 'text-primary-400 hover:text-primary-300'
                : 'text-surface-400 hover:text-zinc-100',
            )}
            title={apiKey ? 'API key set (click to clear)' : 'Set API key'}
          >
            <Key className="h-3.5 w-3.5" />
            {apiKey ? 'Key Set' : 'Set Key'}
          </button>
        )}

        {/* Dark mode toggle */}
        <button
          type="button"
          onClick={toggleDarkMode}
          className="rounded-md p-2 text-surface-400 transition-colors hover:bg-surface-800 hover:text-zinc-100"
          title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {darkMode ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
        </button>
      </div>
    </header>
  );
}
