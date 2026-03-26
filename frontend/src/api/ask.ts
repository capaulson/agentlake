import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../lib/api';

export interface AgenticSearchCitation {
  index: number;
  document_title: string;
  document_id: string;
  file_id: string;
  chunk_index: number;
  quote: string;
  url: string;
}

export interface KnowledgeFeedback {
  id: string;
  theme: string | null;
  intent: string | null;
  discoveries: string[];
  follow_up_questions: string[];
  related_questions: Array<{ id: string; question: string; similarity: number }>;
  curiosity_note: string;
  total_questions_asked: number;
  auto_explore_triggered: boolean;
}

export interface AgenticSearchResponse {
  question: string;
  answer: string;
  citations: AgenticSearchCitation[];
  confidence: number;
  topics_covered: string[];
  sources_consulted: number;
  chunks_analyzed: number;
  chunks_used: number;
  search_time_ms: number;
  llm_calls: number;
  total_tokens: number;
  had_followup: boolean;
  knowledge?: KnowledgeFeedback;
}

interface ApiEnvelope {
  data: AgenticSearchResponse;
  meta: { request_id: string; timestamp: string };
}

export function useAgenticSearch(question: string | null) {
  return useQuery({
    queryKey: ['agentic-search', question],
    queryFn: () =>
      apiClient.get<ApiEnvelope>('/query/ask', {
        q: question!,
        max_sources: '10',
      }),
    enabled: !!question && question.length > 2,
    staleTime: 60_000,
    retry: false,
  });
}
