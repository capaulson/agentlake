import { useState, useCallback } from 'react';
import { Link } from '@tanstack/react-router';
import {
  Search,
  Sparkles,
  FileText,
  ChevronDown,
  ChevronUp,
  Clock,
  Zap,
  BookOpen,
} from 'lucide-react';
import { useAgenticSearch, type AgenticSearchCitation } from '@/api/ask';
import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/utils/cn';

function ConfidenceBar({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const color =
    pct >= 80 ? 'bg-emerald-500' : pct >= 50 ? 'bg-amber-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-zinc-800">
        <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-medium text-zinc-400">{pct}% confidence</span>
    </div>
  );
}

function CitationCard({ citation }: { citation: AgenticSearchCitation }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-teal-500/15 text-xs font-bold text-teal-400">
            {citation.index}
          </span>
          <div>
            <Link
              to="/documents/$id"
              params={{ id: citation.document_id }}
              className="text-sm font-medium text-zinc-200 hover:text-teal-400 transition-colors"
            >
              {citation.document_title}
            </Link>
            <p className="mt-0.5 text-[10px] text-zinc-500">
              Chunk {citation.chunk_index} &middot; {citation.file_id?.slice(0, 8)}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="shrink-0 text-zinc-500 hover:text-zinc-300"
        >
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
      </div>
      {expanded && (
        <div className="mt-2 rounded bg-zinc-800/50 p-2 text-xs text-zinc-400 leading-relaxed">
          {citation.quote}
        </div>
      )}
    </div>
  );
}

export function AgenticSearch({ initialQuestion }: { initialQuestion?: string } = {}) {
  const [input, setInput] = useState(initialQuestion ?? '');
  const [activeQuestion, setActiveQuestion] = useState<string | null>(initialQuestion || null);

  const { data, isLoading, isFetching, error } = useAgenticSearch(activeQuestion);
  const result = data?.data;

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (input.trim()) {
        setActiveQuestion(input.trim());
      }
    },
    [input],
  );

  const exampleQuestions = [
    'What is the status of the Kubernetes migration?',
    'Who is responsible for security at NovaTech?',
    'What are the key findings from the vector database comparison?',
    'What partnerships does NovaTech have?',
    'What were the Q4 2024 revenue numbers?',
  ];

  return (
    <div className="space-y-6">
      {/* Search input */}
      <form onSubmit={handleSubmit} className="relative">
        <div className="flex items-center gap-3 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-3 focus-within:border-teal-500/50 focus-within:ring-1 focus-within:ring-teal-500/20 transition-all">
          <Sparkles className="h-5 w-5 shrink-0 text-teal-500" />
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question about your data lake..."
            className="flex-1 bg-transparent text-sm text-zinc-100 placeholder-zinc-500 outline-none"
          />
          <Button
            type="submit"
            variant="primary"
            size="sm"
            loading={isLoading || isFetching}
            disabled={!input.trim()}
          >
            <Search className="mr-1.5 h-3.5 w-3.5" />
            Ask
          </Button>
        </div>
      </form>

      {/* Example questions (only show when no active question) */}
      {!activeQuestion && !result && (
        <div className="space-y-3">
          <p className="text-xs font-medium text-zinc-500 uppercase tracking-wider">Try asking</p>
          <div className="flex flex-wrap gap-2">
            {exampleQuestions.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => {
                  setInput(q);
                  setActiveQuestion(q);
                }}
                className="rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-2 text-xs text-zinc-400 hover:border-teal-500/30 hover:text-zinc-200 transition-all"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Loading state */}
      {(isLoading || isFetching) && (
        <div className="flex flex-col items-center gap-4 py-12">
          <Spinner size="lg" />
          <div className="text-center">
            <p className="text-sm font-medium text-zinc-300">Researching your question...</p>
            <p className="mt-1 text-xs text-zinc-500">
              Searching documents, evaluating relevance, synthesizing answer
            </p>
          </div>
        </div>
      )}

      {/* Error */}
      {error && !isLoading && (
        <div className="rounded-xl border border-red-900/50 bg-red-950/20 p-4">
          <p className="text-sm text-red-400">
            {error instanceof Error ? error.message : 'Search failed. Please try again.'}
          </p>
        </div>
      )}

      {/* Result */}
      {result && !isLoading && (
        <div className="space-y-6">
          {/* Answer card */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/80 p-6">
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-teal-500" />
                <span className="text-sm font-semibold text-zinc-200">Answer</span>
              </div>
              <ConfidenceBar confidence={result.confidence} />
            </div>

            {/* Answer text with citation highlighting */}
            <div className="prose prose-invert prose-sm max-w-none">
              <div
                className="text-sm leading-relaxed text-zinc-300 whitespace-pre-wrap"
                dangerouslySetInnerHTML={{
                  __html: result.answer
                    .replace(
                      /\[Source (\d+)\]/g,
                      '<span class="inline-flex items-center justify-center h-5 px-1.5 rounded bg-teal-500/15 text-[10px] font-bold text-teal-400 mx-0.5 cursor-help" title="Source $1">$1</span>',
                    ),
                }}
              />
            </div>

            {/* Topics */}
            {result.topics_covered.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-1.5">
                {result.topics_covered.map((topic) => (
                  <Badge key={topic} variant="default" className="text-[10px]">
                    {topic}
                  </Badge>
                ))}
              </div>
            )}
          </div>

          {/* Sources */}
          {result.citations.length > 0 && (
            <div>
              <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-zinc-300">
                <BookOpen className="h-4 w-4 text-zinc-500" />
                Sources ({result.citations.length})
              </h3>
              <div className="space-y-2">
                {result.citations.map((cit) => (
                  <CitationCard key={cit.index} citation={cit} />
                ))}
              </div>
            </div>
          )}

          {/* Knowledge Memory Card */}
          {result.knowledge && (
            <div className="rounded-xl border border-teal-900/30 bg-teal-950/10 p-4">
              <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold text-teal-400">
                <Sparkles className="h-3.5 w-3.5" />
                Knowledge Memory
              </h3>
              <div className="space-y-3">
                {result.knowledge.discoveries.length > 0 && (
                  <div>
                    <p className="mb-1 text-[10px] text-zinc-500">Learned from this question:</p>
                    <ul className="space-y-1">
                      {result.knowledge.discoveries.map((d, i) => (
                        <li key={i} className="flex items-start gap-1.5 text-xs text-zinc-300">
                          <span className="text-teal-500">•</span>{d}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {result.knowledge.follow_up_questions.length > 0 && (
                  <div>
                    <p className="mb-1 text-[10px] text-zinc-500">System wants to explore next:</p>
                    <div className="space-y-1">
                      {result.knowledge.follow_up_questions.map((q, i) => (
                        <button
                          key={i}
                          type="button"
                          onClick={() => { setInput(q); setActiveQuestion(q); }}
                          className="flex w-full items-center gap-2 rounded-lg bg-zinc-900/50 px-3 py-1.5 text-left text-xs text-zinc-400 hover:bg-zinc-800 hover:text-teal-400 transition-colors"
                        >
                          <Sparkles className="h-3 w-3 shrink-0 text-teal-500/50" />
                          {q}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {result.knowledge.curiosity_note && (
                  <p className="text-[10px] italic text-zinc-500">{result.knowledge.curiosity_note}</p>
                )}
                {result.knowledge.auto_explore_triggered && (
                  <Badge variant="success" className="text-[10px]">Auto-explore triggered</Badge>
                )}
              </div>
            </div>
          )}

          {/* Stats footer */}
          <div className="flex flex-wrap items-center gap-4 rounded-lg border border-zinc-800/50 bg-zinc-950 px-4 py-2.5 text-[10px] text-zinc-500">
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {result.search_time_ms.toFixed(0)}ms search
            </span>
            <span className="flex items-center gap-1">
              <FileText className="h-3 w-3" />
              {result.sources_consulted} docs searched
            </span>
            <span className="flex items-center gap-1">
              <BookOpen className="h-3 w-3" />
              {result.chunks_used} chunks used
            </span>
            <span className="flex items-center gap-1">
              <Zap className="h-3 w-3" />
              {result.llm_calls} LLM calls &middot; {result.total_tokens} tokens
            </span>
            {result.had_followup && (
              <Badge variant="info" className="text-[10px]">follow-up search</Badge>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
