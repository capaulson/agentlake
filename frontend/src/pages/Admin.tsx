import { useState, useEffect } from 'react';
import {
  Key,
  Plus,
  Trash2,
  Copy,
  Check,
  Activity,
  Clock,
  AlertTriangle,
  Users,
  Shield,
  Brain,
  Zap,
  Sparkles,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import {
  useApiKeys,
  useCreateApiKey,
  useDeleteApiKey,
  useQueueStatus,
  type ApiKeyResponse,
} from '@/api/admin';
import { TokenUsageChart } from '@/components/TokenUsageChart';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Spinner } from '@/components/ui/Spinner';
import { formatRelative } from '@/utils/formatDate';

export default function Admin() {
  const { data: keysData, isLoading: keysLoading } = useApiKeys();
  const { data: queueData } = useQueueStatus();
  const createKeyMutation = useCreateApiKey();
  const deleteKeyMutation = useDeleteApiKey();

  const [showCreateKey, setShowCreateKey] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyScopes, setNewKeyScopes] = useState<string[]>(['read']);
  const [newKeyExpiry, setNewKeyExpiry] = useState('');
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<ApiKeyResponse | null>(null);

  const apiKeys = keysData?.data ?? [];
  const queue = queueData?.data;

  const SCOPES = ['read', 'write', 'admin', 'upload', 'search'] as const;

  function toggleScope(scope: string) {
    setNewKeyScopes((prev) =>
      prev.includes(scope)
        ? prev.filter((s) => s !== scope)
        : [...prev, scope],
    );
  }

  async function handleCreateKey() {
    if (!newKeyName.trim() || newKeyScopes.length === 0) return;

    const result = await createKeyMutation.mutateAsync({
      name: newKeyName.trim(),
      scopes: newKeyScopes,
      expires_in_days: newKeyExpiry ? Number(newKeyExpiry) : undefined,
    });

    setCreatedKey(result.data.key);
    setNewKeyName('');
    setNewKeyScopes(['read']);
    setNewKeyExpiry('');
  }

  async function handleCopyKey() {
    if (!createdKey) return;
    await navigator.clipboard.writeText(createdKey);
    setCopiedKey(true);
    setTimeout(() => setCopiedKey(false), 2000);
  }

  async function handleDeleteKey() {
    if (!deleteConfirm) return;
    await deleteKeyMutation.mutateAsync(deleteConfirm.id);
    setDeleteConfirm(null);
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-zinc-100">Admin</h1>
        <p className="mt-1 text-surface-400">
          System configuration and administration
        </p>
      </div>

      {/* System health */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-5">
          <div className="flex items-center gap-2 text-emerald-500">
            <Activity className="h-5 w-5" />
            <span className="text-sm font-medium">Active</span>
          </div>
          <p className="mt-2 text-2xl font-bold tabular-nums text-zinc-100">
            {queue?.active ?? 0}
          </p>
          <p className="text-xs text-surface-500">processing jobs</p>
        </div>
        <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-5">
          <div className="flex items-center gap-2 text-amber-500">
            <Clock className="h-5 w-5" />
            <span className="text-sm font-medium">Pending</span>
          </div>
          <p className="mt-2 text-2xl font-bold tabular-nums text-zinc-100">
            {queue?.pending ?? 0}
          </p>
          <p className="text-xs text-surface-500">in queue</p>
        </div>
        <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-5">
          <div className="flex items-center gap-2 text-primary-500">
            <Check className="h-5 w-5" />
            <span className="text-sm font-medium">Completed</span>
          </div>
          <p className="mt-2 text-2xl font-bold tabular-nums text-zinc-100">
            {queue?.completed_today ?? 0}
          </p>
          <p className="text-xs text-surface-500">today</p>
        </div>
        <div className="rounded-xl border border-surface-700 bg-surface-800/50 p-5">
          <div className="flex items-center gap-2 text-danger-500">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm font-medium">Failed</span>
          </div>
          <p className="mt-2 text-2xl font-bold tabular-nums text-zinc-100">
            {queue?.failed_today ?? 0}
          </p>
          <p className="text-xs text-surface-500">today</p>
        </div>
      </div>

      {/* API Keys */}
      <Card
        title="API Keys"
        actions={
          <Button size="sm" onClick={() => setShowCreateKey(true)}>
            <Plus className="h-4 w-4" />
            New Key
          </Button>
        }
      >
        {keysLoading ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : apiKeys.length === 0 ? (
          <div className="py-6 text-center text-sm text-surface-400">
            No API keys created yet
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-surface-700">
                  <th className="pb-2 text-left text-xs font-medium text-surface-400">Name</th>
                  <th className="pb-2 text-left text-xs font-medium text-surface-400">Prefix</th>
                  <th className="pb-2 text-left text-xs font-medium text-surface-400">Scopes</th>
                  <th className="pb-2 text-left text-xs font-medium text-surface-400">Last Used</th>
                  <th className="pb-2 text-left text-xs font-medium text-surface-400">Expires</th>
                  <th className="pb-2 text-right text-xs font-medium text-surface-400">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-700/50">
                {apiKeys.map((key) => (
                  <tr key={key.id} className="transition-colors hover:bg-surface-800/30">
                    <td className="py-3 text-sm text-zinc-200">
                      <div className="flex items-center gap-2">
                        <Key className="h-3.5 w-3.5 text-surface-400" />
                        {key.name}
                      </div>
                    </td>
                    <td className="py-3 font-mono text-xs text-surface-400">{key.prefix ?? key.id?.slice(0, 8) ?? '???'}...</td>
                    <td className="py-3">
                      <div className="flex gap-1">
                        {(key.scopes ?? [key.role ?? 'viewer']).map((scope: string) => (
                          <Badge key={scope} variant="default" className="text-[10px]">
                            {scope}
                          </Badge>
                        ))}
                      </div>
                    </td>
                    <td className="py-3 text-xs text-surface-400">
                      {key.last_used_at ? formatRelative(key.last_used_at) : 'Never'}
                    </td>
                    <td className="py-3 text-xs text-surface-400">
                      {key.expires_at ? formatRelative(key.expires_at) : '—'}
                    </td>
                    <td className="py-3 text-right">
                      <button
                        type="button"
                        onClick={() => setDeleteConfirm(key)}
                        className="rounded p-1.5 text-surface-400 transition-colors hover:bg-danger-900/50 hover:text-danger-400"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Token Usage */}
      <Card title="LLM Token Usage">
        <TokenUsageChart />
      </Card>

      {/* Workers */}
      {queue && (
        <Card title="Workers">
          <div className="flex items-center gap-3">
            <Users className="h-5 w-5 text-surface-400" />
            <span className="text-sm text-zinc-200">{queue.workers} worker{queue.workers !== 1 ? 's' : ''} active</span>
          </div>
        </Card>
      )}

      {/* Create API Key modal */}
      <Modal
        open={showCreateKey}
        onClose={() => {
          setShowCreateKey(false);
          setCreatedKey(null);
          setCopiedKey(false);
        }}
        title={createdKey ? 'API Key Created' : 'Create API Key'}
        size="sm"
      >
        {createdKey ? (
          <div className="space-y-4">
            <div className="rounded-lg border border-amber-800 bg-amber-900/30 px-3 py-2">
              <p className="text-xs text-amber-400">
                Copy this key now. It will not be shown again.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <code className="flex-1 overflow-hidden rounded-lg bg-surface-800 px-3 py-2 font-mono text-xs text-zinc-100 select-all">
                {createdKey}
              </code>
              <button
                type="button"
                onClick={() => void handleCopyKey()}
                className="rounded-lg p-2 text-surface-400 transition-colors hover:bg-surface-700 hover:text-zinc-100"
              >
                {copiedKey ? (
                  <Check className="h-4 w-4 text-emerald-400" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </button>
            </div>
            <div className="flex justify-end">
              <Button
                size="sm"
                onClick={() => {
                  setShowCreateKey(false);
                  setCreatedKey(null);
                }}
              >
                Done
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-sm font-medium text-zinc-300">Name</label>
              <input
                type="text"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                placeholder="My API Key"
                className="w-full rounded-lg border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-zinc-100 placeholder-surface-500 outline-none focus:border-primary-500"
                autoFocus
              />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-zinc-300">Scopes</label>
              <div className="flex flex-wrap gap-2">
                {SCOPES.map((scope) => (
                  <button
                    key={scope}
                    type="button"
                    onClick={() => toggleScope(scope)}
                    className={cn(
                      'flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium transition-all',
                      newKeyScopes.includes(scope)
                        ? 'bg-primary-500/15 text-primary-400 ring-1 ring-primary-500/30'
                        : 'bg-surface-700 text-surface-400 hover:text-zinc-200',
                    )}
                  >
                    <Shield className="h-3 w-3" />
                    {scope}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-zinc-300">
                Expires in (days, optional)
              </label>
              <input
                type="number"
                value={newKeyExpiry}
                onChange={(e) => setNewKeyExpiry(e.target.value)}
                placeholder="Never"
                min={1}
                className="w-full rounded-lg border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-zinc-100 placeholder-surface-500 outline-none focus:border-primary-500"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" size="sm" onClick={() => setShowCreateKey(false)}>
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={() => void handleCreateKey()}
                disabled={!newKeyName.trim() || newKeyScopes.length === 0 || createKeyMutation.isPending}
                loading={createKeyMutation.isPending}
              >
                Create Key
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Delete confirmation */}
      <Modal
        open={deleteConfirm !== null}
        onClose={() => setDeleteConfirm(null)}
        title="Delete API Key"
        size="sm"
      >
        <div className="space-y-4">
          <p className="text-sm text-surface-300">
            Are you sure you want to delete the API key{' '}
            <strong className="text-zinc-100">{deleteConfirm?.name}</strong>?
            Any applications using this key will lose access immediately.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDeleteConfirm(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={() => void handleDeleteKey()}
              loading={deleteKeyMutation.isPending}
            >
              Delete
            </Button>
          </div>
        </div>
      </Modal>

      {/* ── Knowledge Discovery Settings ──────────────────────────── */}
      <KnowledgeDiscoverySettings />
    </div>
  );
}


function KnowledgeDiscoverySettings() {
  const [settings, setSettings] = useState<Record<string, { value: string; description: string }>>({});
  const [usage, setUsage] = useState<{ tokens_last_hour: number; tokens_last_24h: number } | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [exploring, setExploring] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const { apiClient } = await import('@/lib/api');
        const resp = await apiClient.get<{ data: { settings: Record<string, { value: string; description: string }>; usage: { tokens_last_hour: number; tokens_last_24h: number } } }>('/admin/settings');
        setSettings(resp.data.settings);
        setUsage(resp.data.usage);
        setLoaded(true);
      } catch { setLoaded(true); }
    })();
  }, []);

  async function saveSetting(key: string, value: string) {
    try {
      await fetch(`/api/v1/admin/settings/${key}?value=${encodeURIComponent(value)}`, {
        method: 'PUT',
        headers: { 'X-API-Key': localStorage.getItem('agentlake-api-key') || 'test-admin-key' },
      });
      setSettings((prev) => ({ ...prev, [key]: { ...prev[key], value } }));
    } catch { /* ignore */ }
  }

  async function triggerExplore() {
    setExploring(true);
    try {
      const { apiClient } = await import('@/lib/api');
      await apiClient.post('/admin/explore');
    } catch { /* ignore */ }
    setExploring(false);
  }

  async function triggerAnalysis() {
    setAnalyzing(true);
    try {
      const { apiClient } = await import('@/lib/api');
      await apiClient.post('/admin/analyze');
    } catch { /* ignore */ }
    setAnalyzing(false);
  }

  if (!loaded) return null;

  const isEnabled = settings.auto_explore_enabled?.value === 'true';

  return (
    <Card
      title="Knowledge Discovery"
      actions={
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => saveSetting('auto_explore_enabled', isEnabled ? 'false' : 'true')}
            className={cn(
              'relative h-6 w-11 rounded-full transition-colors',
              isEnabled ? 'bg-emerald-500' : 'bg-zinc-700',
            )}
          >
            <span className={cn(
              'absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform',
              isEnabled ? 'left-[22px]' : 'left-0.5',
            )} />
          </button>
          <span className="text-xs text-zinc-400">{isEnabled ? 'Active' : 'Paused'}</span>
        </div>
      }
    >
      <div className="space-y-4">
        {/* Token usage meters */}
        {usage && (
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
              <div className="flex items-center gap-2 mb-1">
                <Clock className="h-3 w-3 text-zinc-500" />
                <span className="text-[10px] uppercase tracking-wider text-zinc-500">Tokens / hour</span>
              </div>
              <p className="text-lg font-bold text-zinc-200">{usage.tokens_last_hour.toLocaleString()}</p>
              <div className="mt-1.5 h-2 rounded-full bg-zinc-800 overflow-hidden">
                <div
                  className={cn(
                    'h-full rounded-full transition-all',
                    usage.tokens_last_hour > parseInt(settings.auto_explore_max_tokens_per_hour?.value || '50000') * 0.8
                      ? 'bg-red-500'
                      : usage.tokens_last_hour > parseInt(settings.auto_explore_max_tokens_per_hour?.value || '50000') * 0.5
                        ? 'bg-amber-500'
                        : 'bg-teal-500',
                  )}
                  style={{ width: `${Math.min(100, (usage.tokens_last_hour / parseInt(settings.auto_explore_max_tokens_per_hour?.value || '50000')) * 100)}%` }}
                />
              </div>
              <p className="mt-1 text-[10px] text-zinc-600">
                of {parseInt(settings.auto_explore_max_tokens_per_hour?.value || '50000').toLocaleString()} limit
              </p>
            </div>
            <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
              <div className="flex items-center gap-2 mb-1">
                <Activity className="h-3 w-3 text-zinc-500" />
                <span className="text-[10px] uppercase tracking-wider text-zinc-500">Tokens / 24h</span>
              </div>
              <p className="text-lg font-bold text-zinc-200">{usage.tokens_last_24h.toLocaleString()}</p>
            </div>
          </div>
        )}

        {/* Settings grid */}
        <div className="space-y-2">
          {[
            { key: 'auto_explore_max_tokens_per_hour', label: 'Max tokens per hour', icon: Zap, color: 'text-amber-400' },
            { key: 'auto_explore_max_questions_per_run', label: 'Questions per explore run', icon: Sparkles, color: 'text-teal-400' },
          ].map(({ key, label, icon: Icon, color }) => {
            const setting = settings[key];
            if (!setting) return null;
            return (
              <div key={key} className="flex items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-950 px-4 py-2.5">
                <Icon className={cn('h-4 w-4 shrink-0', color)} />
                <div className="flex-1">
                  <p className="text-sm text-zinc-200">{label}</p>
                  <p className="text-[10px] text-zinc-600">{setting.description}</p>
                </div>
                <input
                  type="number"
                  value={setting.value}
                  onChange={(e) => setSettings((prev) => ({ ...prev, [key]: { ...prev[key], value: e.target.value } }))}
                  onBlur={(e) => saveSetting(key, e.target.value)}
                  className={cn('w-24 rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-right text-sm font-mono', color)}
                />
              </div>
            );
          })}
        </div>

        {/* Manual triggers */}
        <div className="flex gap-2 border-t border-zinc-800 pt-3">
          <Button size="sm" variant="secondary" onClick={triggerExplore} loading={exploring}>
            <Sparkles className="h-3.5 w-3.5" />
            Explore Now
          </Button>
          <Button size="sm" variant="secondary" onClick={triggerAnalysis} loading={analyzing}>
            <Brain className="h-3.5 w-3.5" />
            Run Analysis
          </Button>
        </div>
      </div>
    </Card>
  );
}
