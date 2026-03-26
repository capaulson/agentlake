import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../lib/api';

export interface KnowledgeMemory {
  id: string;
  question: string;
  answer: string;
  confidence: number;
  theme: string | null;
  intent: string | null;
  entities_mentioned: string[];
  discoveries: string[];
  follow_up_questions: string[];
  related_questions: Array<{ id: string; question: string; similarity: number }>;
  sources_used: number;
  led_to_analysis: boolean;
  asked_by: string;
  created_at: string;
}

export interface KnowledgeTheme {
  theme: string;
  count: number;
  avg_confidence: number;
  last_asked: string | null;
}

export interface SystemCuriosity {
  question: string;
  from_theme: string | null;
  generated_at: string | null;
}

export interface KnowledgeResponse {
  data: {
    memories: KnowledgeMemory[];
    themes: KnowledgeTheme[];
    system_curiosity: SystemCuriosity[];
    stats: {
      total_questions: number;
      unique_themes: number;
      avg_confidence: number;
      total_tokens: number;
      questions_triggering_analysis: number;
    };
  };
  meta: { request_id: string; timestamp: string };
}

export function useKnowledge(limit: number = 50, theme?: string) {
  return useQuery({
    queryKey: ['knowledge', limit, theme],
    queryFn: () => {
      const params: Record<string, string> = { limit: String(limit) };
      if (theme) params.theme = theme;
      return apiClient.get<KnowledgeResponse>('/query/knowledge', params);
    },
    refetchInterval: 30_000,
  });
}
