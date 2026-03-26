import { useState, useEffect } from 'react';
import {
  Brain,
  Lightbulb,
  MessageCircleQuestion,
  Network,
  TrendingUp,
  Zap,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Sparkles,
} from 'lucide-react';
import { useKnowledge, type KnowledgeMemory } from '@/api/knowledge';
import { Badge } from '@/components/ui/Badge';
import { Modal } from '@/components/ui/Modal';
import { Spinner } from '@/components/ui/Spinner';
import { cn } from '@/utils/cn';
import { formatRelative } from '@/utils/formatDate';

const INTENT_COLORS: Record<string, string> = {
  factual: 'bg-sky-500/15 text-sky-400',
  analytical: 'bg-violet-500/15 text-violet-400',
  exploratory: 'bg-amber-500/15 text-amber-400',
  comparative: 'bg-emerald-500/15 text-emerald-400',
  strategic: 'bg-rose-500/15 text-rose-400',
};

function ConfidenceDot({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const color = pct >= 80 ? 'bg-emerald-500' : pct >= 50 ? 'bg-amber-500' : 'bg-zinc-500';
  return <span className={cn('inline-block h-2 w-2 rounded-full', color)} title={`${pct}% confidence`} />;
}

function QuestionCard({ memory }: { memory: KnowledgeMemory }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 transition-all hover:border-zinc-700">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full px-5 py-4 text-left"
      >
        <div className="flex items-start gap-3">
          <MessageCircleQuestion className="mt-0.5 h-4 w-4 shrink-0 text-teal-500" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-zinc-200">{memory.question}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <ConfidenceDot confidence={memory.confidence} />
              {memory.theme && (
                <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] text-zinc-400">
                  {memory.theme}
                </span>
              )}
              {memory.intent && (
                <span className={cn('rounded-full px-2 py-0.5 text-[10px]', INTENT_COLORS[memory.intent] ?? 'bg-zinc-800 text-zinc-400')}>
                  {memory.intent}
                </span>
              )}
              <span className="text-[10px] text-zinc-500">{memory.sources_used} sources</span>
              <span className="text-[10px] text-zinc-500">{formatRelative(memory.created_at)}</span>
              {memory.asked_by === 'auto_explore' && (
                <Badge variant="success" className="text-[10px]">auto-explored</Badge>
              )}
              {memory.led_to_analysis && (
                <Badge variant="info" className="text-[10px]">triggered analysis</Badge>
              )}
            </div>
          </div>
          {expanded ? <ChevronUp className="h-4 w-4 text-zinc-500" /> : <ChevronDown className="h-4 w-4 text-zinc-500" />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-zinc-800 px-5 py-4 space-y-4">
          {/* Answer */}
          {memory.answer && (
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Answer</p>
              <p className="text-sm text-zinc-300 leading-relaxed">{memory.answer}</p>
            </div>
          )}

          {/* Discoveries */}
          {memory.discoveries.length > 0 && (
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                <Lightbulb className="mr-1 inline h-3 w-3" />What was learned
              </p>
              <ul className="space-y-1">
                {memory.discoveries.map((d, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-zinc-300">
                    <span className="mt-0.5 text-teal-500">•</span>{d}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Follow-up questions */}
          {memory.follow_up_questions.length > 0 && (
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                <Sparkles className="mr-1 inline h-3 w-3" />System wants to explore
              </p>
              <div className="space-y-1">
                {memory.follow_up_questions.map((q, i) => (
                  <a
                    key={i}
                    href={`/search?q=${encodeURIComponent(q)}`}
                    className="flex items-center gap-2 rounded-lg bg-zinc-800/50 px-3 py-2 text-xs text-zinc-300 hover:bg-zinc-800 hover:text-teal-400 transition-colors"
                  >
                    <Sparkles className="h-3 w-3 text-teal-500/50" />
                    {q}
                    <ExternalLink className="ml-auto h-3 w-3 text-zinc-600" />
                  </a>
                ))}
              </div>
            </div>
          )}

          {/* Related questions */}
          {memory.related_questions.length > 0 && (
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                <Network className="mr-1 inline h-3 w-3" />Related past questions
              </p>
              <div className="space-y-1">
                {memory.related_questions.map((rq) => (
                  <div key={rq.id} className="flex items-center gap-2 text-xs">
                    <span className="h-1.5 w-1.5 rounded-full bg-zinc-600" />
                    <span className="text-zinc-400 flex-1">{rq.question}</span>
                    <span className="text-[10px] text-zinc-600">{(rq.similarity * 100).toFixed(0)}% similar</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Entities */}
          {memory.entities_mentioned.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {memory.entities_mentioned.map((e, i) => (
                <span key={i} className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">{e}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


function AnalysisSettingsPanel({ stats }: { stats: { total_questions: number; questions_triggering_analysis: number; total_tokens: number } | undefined }) {
  const [settings, setSettings] = useState<Record<string, { value: string; description: string }>>({});
  const [usage, setUsage] = useState<{ tokens_last_hour: number; tokens_last_24h: number } | null>(null);
  const [, setSaving] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const { apiClient } = await import('@/lib/api');
        const resp = await apiClient.get<{ data: { settings: Record<string, { value: string; description: string }>; usage: { tokens_last_hour: number; tokens_last_24h: number } } }>('/admin/settings');
        setSettings(resp.data.settings);
        setUsage(resp.data.usage);
      } catch { /* ignore */ }
    })();
  }, []);

  async function updateSetting(key: string, value: string) {
    setSaving(key);
    try {
      const { apiClient } = await import('@/lib/api');
      await apiClient.put(`/admin/settings/${key}`, null);
      // Use query params for the value since the API expects it
      await fetch(`/api/v1/admin/settings/${key}?value=${encodeURIComponent(value)}`, {
        method: 'PUT',
        headers: { 'X-API-Key': localStorage.getItem('agentlake-api-key') || 'test-admin-key' },
      });
      setSettings((prev) => ({ ...prev, [key]: { ...prev[key], value } }));
    } catch { /* ignore */ }
    setSaving(null);
  }

  const settingConfigs = [
    { key: 'auto_explore_max_tokens_per_hour', label: 'Max tokens per hour', type: 'number', color: 'amber' },
    { key: 'auto_explore_max_questions_per_run', label: 'Questions per auto-explore', type: 'number', color: 'teal' },
    { key: 'auto_explore_enabled', label: 'Auto-exploration', type: 'toggle', color: 'emerald' },
  ];

  return (
    <div className="space-y-4">
      {/* Token usage */}
      {usage && (
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
            <p className="text-[10px] text-zinc-500">Tokens last hour</p>
            <p className="text-xl font-bold text-zinc-200">{usage.tokens_last_hour.toLocaleString()}</p>
            <div className="mt-1 h-1.5 rounded-full bg-zinc-800">
              <div
                className="h-full rounded-full bg-amber-500 transition-all"
                style={{ width: `${Math.min(100, (usage.tokens_last_hour / parseInt(settings.auto_explore_max_tokens_per_hour?.value || '50000')) * 100)}%` }}
              />
            </div>
          </div>
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
            <p className="text-[10px] text-zinc-500">Tokens last 24h</p>
            <p className="text-xl font-bold text-zinc-200">{usage.tokens_last_24h.toLocaleString()}</p>
          </div>
        </div>
      )}

      {/* Settings */}
      <div className="space-y-3">
        {settingConfigs.map(({ key, label, type, color }) => {
          const current = settings[key];
          if (!current) return null;
          return (
            <div key={key} className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/50 px-4 py-3">
              <div>
                <p className="text-sm text-zinc-200">{label}</p>
                <p className="text-[10px] text-zinc-500">{current.description}</p>
              </div>
              {type === 'toggle' ? (
                <button
                  type="button"
                  onClick={() => updateSetting(key, current.value === 'true' ? 'false' : 'true')}
                  className={cn(
                    'relative h-6 w-11 rounded-full transition-colors',
                    current.value === 'true' ? 'bg-emerald-500' : 'bg-zinc-700',
                  )}
                >
                  <span className={cn(
                    'absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform',
                    current.value === 'true' ? 'left-[22px]' : 'left-0.5',
                  )} />
                </button>
              ) : (
                <input
                  type="number"
                  value={current.value}
                  onChange={(e) => setSettings((prev) => ({ ...prev, [key]: { ...prev[key], value: e.target.value } }))}
                  onBlur={(e) => updateSetting(key, e.target.value)}
                  className={cn(
                    'w-24 rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1 text-right text-sm font-mono',
                    `text-${color}-400`,
                  )}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Trigger rules */}
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">What Triggers Auto-Exploration</h4>
        <ul className="space-y-1.5 text-xs text-zinc-400">
          <li className="flex items-start gap-2"><Zap className="mt-0.5 h-3 w-3 text-teal-500" /> After every question, auto-explore is triggered autonomously</li>
          <li className="flex items-start gap-2"><Zap className="mt-0.5 h-3 w-3 text-amber-500" /> Stops if hourly token usage exceeds {parseInt(settings.auto_explore_max_tokens_per_hour?.value ?? '50000').toLocaleString()}</li>
          <li className="flex items-start gap-2"><Zap className="mt-0.5 h-3 w-3 text-violet-500" /> Explores up to {settings.auto_explore_max_questions_per_run?.value ?? '5'} follow-up questions per run</li>
          <li className="flex items-start gap-2"><Zap className="mt-0.5 h-3 w-3 text-zinc-500" /> Can be paused via the toggle or by setting token limit to 0</li>
        </ul>
      </div>

      {/* Stats */}
      <div className="rounded-lg border border-zinc-800/50 bg-zinc-950 p-4 flex justify-between text-sm">
        <span className="text-zinc-500">Analyses triggered</span>
        <span className="font-bold text-teal-400">{stats?.questions_triggering_analysis ?? 0}</span>
      </div>
    </div>
  );
}


export default function Knowledge() {
  const [selectedTheme, setSelectedTheme] = useState<string | undefined>();
  const [activeModal, setActiveModal] = useState<'questions' | 'themes' | 'analysis' | null>(null);
  const [exploring, setExploring] = useState(false);
  const { data, isLoading } = useKnowledge(50, selectedTheme);

  const memories = data?.data?.memories ?? [];
  const themes = data?.data?.themes ?? [];
  const curiosity = data?.data?.system_curiosity ?? [];
  const stats = data?.data?.stats;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-zinc-100">
          <Brain className="h-6 w-6 text-teal-500" />
          Institutional Knowledge
        </h1>
        <p className="mt-1 text-zinc-400">
          Every question grows the organization's memory. The system learns what matters and proactively explores deeper.
        </p>
      </div>

      {/* Stats row — clickable cards */}
      {stats && (
        <div className="grid grid-cols-5 gap-3">
          {[
            { label: 'Questions Asked', value: stats.total_questions, icon: MessageCircleQuestion, modal: 'questions' as const },
            { label: 'Themes', value: stats.unique_themes, icon: Network, modal: 'themes' as const },
            { label: 'Avg Confidence', value: `${Math.round(stats.avg_confidence * 100)}%`, icon: TrendingUp, modal: null },
            { label: 'Analyses Triggered', value: stats.questions_triggering_analysis, icon: Zap, modal: 'analysis' as const },
            { label: 'Tokens Invested', value: stats.total_tokens.toLocaleString(), icon: Brain, modal: null },
          ].map((stat) => (
            <button
              key={stat.label}
              type="button"
              onClick={() => stat.modal && setActiveModal(stat.modal)}
              className={cn(
                'rounded-xl border border-zinc-800 bg-zinc-900/50 p-4 text-left transition-all',
                stat.modal ? 'hover:border-teal-500/30 hover:bg-zinc-900 cursor-pointer' : 'cursor-default',
              )}
            >
              <div className="flex items-center gap-2">
                <stat.icon className="h-4 w-4 text-zinc-500" />
                <span className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">{stat.label}</span>
              </div>
              <p className="mt-2 text-2xl font-bold text-zinc-100">{stat.value}</p>
            </button>
          ))}
        </div>
      )}

      <div className="grid grid-cols-3 gap-6">
        {/* Left: Question timeline */}
        <div className="col-span-2 space-y-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-zinc-300">
            <MessageCircleQuestion className="h-4 w-4" />
            Question History
            {selectedTheme && (
              <button
                type="button"
                onClick={() => setSelectedTheme(undefined)}
                className="ml-2 rounded bg-zinc-800 px-2 py-0.5 text-[10px] text-zinc-400 hover:text-zinc-200"
              >
                {selectedTheme} ✕
              </button>
            )}
          </h2>

          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <Spinner size="lg" />
            </div>
          )}

          {!isLoading && memories.length === 0 && (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/30 p-12 text-center">
              <Brain className="mx-auto h-10 w-10 text-zinc-700" />
              <p className="mt-3 text-sm text-zinc-500">No questions asked yet.</p>
              <p className="mt-1 text-xs text-zinc-600">
                Go to Search → Ask AI and start asking questions about your data.
              </p>
            </div>
          )}

          <div className="space-y-3">
            {memories.map((m) => (
              <QuestionCard key={m.id} memory={m} />
            ))}
          </div>
        </div>

        {/* Right sidebar */}
        <div className="space-y-4">
          {/* System Curiosity */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                <Sparkles className="h-3.5 w-3.5 text-teal-500" />
                System Wants to Explore
              </h3>
              {curiosity.length > 0 && (
                <button
                  type="button"
                  onClick={async () => {
                    setExploring(true);
                    try {
                      const { apiClient } = await import('@/lib/api');
                      await apiClient.post('/admin/explore', { max_questions: 5 });
                    } catch { /* ignore */ }
                    setExploring(false);
                  }}
                  className="flex items-center gap-1 rounded-md bg-teal-500/15 px-2 py-1 text-[10px] font-medium text-teal-400 hover:bg-teal-500/25 transition-colors"
                >
                  {exploring ? <Spinner size="sm" /> : <Zap className="h-3 w-3" />}
                  {exploring ? 'Exploring...' : 'Explore Now'}
                </button>
              )}
            </div>
            {curiosity.length === 0 ? (
              <p className="text-xs text-zinc-600">
                Ask questions to seed the system's curiosity.
              </p>
            ) : (
              <div className="space-y-2">
                {curiosity.slice(0, 10).map((c, i) => (
                  <a
                    key={i}
                    href={`/search?q=${encodeURIComponent(c.question)}`}
                    className="block rounded-lg bg-zinc-800/30 px-3 py-2 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-teal-400 transition-colors"
                  >
                    <span className="text-teal-500/50">→ </span>
                    {c.question}
                    {c.from_theme && (
                      <span className="ml-1 text-[10px] text-zinc-600">({c.from_theme})</span>
                    )}
                  </a>
                ))}
              </div>
            )}
          </div>

          {/* Themes */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
            <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">
              <Network className="h-3.5 w-3.5" />
              Knowledge Themes
            </h3>
            {themes.length === 0 ? (
              <p className="text-xs text-zinc-600">Themes will emerge as questions accumulate.</p>
            ) : (
              <div className="space-y-1.5">
                {themes.map((t) => (
                  <button
                    key={t.theme}
                    type="button"
                    onClick={() => setSelectedTheme(selectedTheme === t.theme ? undefined : t.theme)}
                    className={cn(
                      'flex w-full items-center justify-between rounded-lg px-3 py-2 text-xs transition-colors',
                      selectedTheme === t.theme
                        ? 'bg-teal-500/15 text-teal-400'
                        : 'text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200',
                    )}
                  >
                    <span>{t.theme}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-zinc-600">{Math.round(t.avg_confidence * 100)}%</span>
                      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-zinc-800 text-[10px] font-bold">
                        {t.count}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* How it works */}
          <div className="rounded-xl border border-zinc-800/50 bg-zinc-950 p-4">
            <h3 className="mb-2 text-xs font-semibold text-zinc-500">How Knowledge Grows</h3>
            <div className="space-y-2 text-[10px] text-zinc-600 leading-relaxed">
              <p><span className="text-teal-500">1.</span> You ask a question via Ask AI</p>
              <p><span className="text-teal-500">2.</span> The system answers and records the question as memory</p>
              <p><span className="text-teal-500">3.</span> It classifies the theme, extracts discoveries, and generates follow-up questions</p>
              <p><span className="text-teal-500">4.</span> The AI autonomously explores follow-up questions (within token budget)</p>
              <p><span className="text-teal-500">5.</span> Each explored question generates more follow-ups — knowledge compounds</p>
              <p className="pt-1 text-zinc-500 font-medium">Question → Memory → Follow-ups → Auto-explore → Deeper Knowledge → ∞</p>
            </div>
          </div>
        </div>
      </div>

      {/* ── Modals ──────────────────────────────────────────────── */}

      {/* Questions Modal */}
      <Modal open={activeModal === 'questions'} onClose={() => setActiveModal(null)} title="All Questions Asked" size="lg">
        <div className="max-h-[60vh] overflow-y-auto space-y-2">
          {memories.map((m) => (
            <div key={m.id} className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
              <p className="text-sm text-zinc-200">{m.question}</p>
              <div className="mt-1 flex items-center gap-2 text-[10px] text-zinc-500">
                <ConfidenceDot confidence={m.confidence} />
                <span>{m.theme ?? 'unclassified'}</span>
                <span>&middot;</span>
                <span>{m.intent ?? '?'}</span>
                <span>&middot;</span>
                <span>{m.sources_used} sources</span>
                <span>&middot;</span>
                <span>{formatRelative(m.created_at)}</span>
              </div>
              {m.answer && (
                <p className="mt-1.5 text-xs text-zinc-400 line-clamp-2">{m.answer}</p>
              )}
            </div>
          ))}
        </div>
      </Modal>

      {/* Themes Modal */}
      <Modal open={activeModal === 'themes'} onClose={() => setActiveModal(null)} title="Knowledge Themes" size="md">
        <div className="space-y-3">
          <p className="text-xs text-zinc-400">
            Themes emerge automatically as questions accumulate. Click a theme to filter the question list.
          </p>
          {themes.map((t) => (
            <button
              key={t.theme}
              type="button"
              onClick={() => { setSelectedTheme(t.theme); setActiveModal(null); }}
              className="flex w-full items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/50 px-4 py-3 text-left hover:border-teal-500/30 transition-all"
            >
              <div>
                <p className="text-sm font-medium text-zinc-200">{t.theme}</p>
                <p className="mt-0.5 text-[10px] text-zinc-500">
                  {t.count} questions &middot; avg confidence {Math.round(t.avg_confidence * 100)}%
                  {t.last_asked && ` · last asked ${formatRelative(t.last_asked)}`}
                </p>
              </div>
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-teal-500/15 text-sm font-bold text-teal-400">
                {t.count}
              </span>
            </button>
          ))}
          {themes.length === 0 && (
            <p className="py-8 text-center text-xs text-zinc-500">No themes yet. Ask more questions!</p>
          )}
        </div>
      </Modal>

      {/* Analysis Trigger Modal */}
      <Modal open={activeModal === 'analysis'} onClose={() => setActiveModal(null)} title="Knowledge Discovery Settings" size="md">
        <AnalysisSettingsPanel stats={stats} />
      </Modal>
    </div>
  );
}
