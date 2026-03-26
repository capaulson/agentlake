import { useState, useEffect, useRef, useCallback } from 'react';
import type { SearchParams, SearchResult } from '../api/query';

interface SearchStreamState {
  results: SearchResult[];
  isStreaming: boolean;
  totalCount: number | null;
  searchTime: number | null;
}

interface SearchResultEvent {
  type: 'result';
  result: SearchResult;
}

interface SearchMetaEvent {
  type: 'meta';
  total_count: number;
  search_time_ms: number;
}

interface SearchDoneEvent {
  type: 'done';
}

type SearchEvent = SearchResultEvent | SearchMetaEvent | SearchDoneEvent;

const INITIAL_STATE: SearchStreamState = {
  results: [],
  isStreaming: false,
  totalCount: null,
  searchTime: null,
};

export function useSearchStream(
  params: SearchParams | null,
): SearchStreamState {
  const [state, setState] = useState<SearchStreamState>(INITIAL_STATE);
  const eventSourceRef = useRef<EventSource | null>(null);

  const cleanup = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!params || !params.q) {
      cleanup();
      setState(INITIAL_STATE);
      return;
    }

    cleanup();

    const baseUrl = import.meta.env.VITE_API_URL ?? '/api/v1';
    const url = new URL(`${baseUrl}/stream/search`, window.location.origin);
    url.searchParams.set('q', params.q);
    if (params.search_type) url.searchParams.set('search_type', params.search_type);
    if (params.category) url.searchParams.set('category', params.category);
    if (params.tags && params.tags.length > 0)
      url.searchParams.set('tags', params.tags.join(','));
    if (params.limit !== undefined)
      url.searchParams.set('limit', String(params.limit));
    if (params.cursor) url.searchParams.set('cursor', params.cursor);

    setState({
      results: [],
      isStreaming: true,
      totalCount: null,
      searchTime: null,
    });

    const es = new EventSource(url.toString());
    eventSourceRef.current = es;

    es.onmessage = (event: MessageEvent<string>) => {
      const data = JSON.parse(event.data) as SearchEvent;

      switch (data.type) {
        case 'result':
          setState((prev) => ({
            ...prev,
            results: [...prev.results, data.result],
          }));
          break;
        case 'meta':
          setState((prev) => ({
            ...prev,
            totalCount: data.total_count,
            searchTime: data.search_time_ms,
          }));
          break;
        case 'done':
          setState((prev) => ({
            ...prev,
            isStreaming: false,
          }));
          es.close();
          break;
      }
    };

    es.onerror = () => {
      es.close();
      setState((prev) => ({
        ...prev,
        isStreaming: false,
      }));
    };

    return cleanup;
  }, [
    params?.q,
    params?.search_type,
    params?.category,
    params?.tags?.join(','),
    params?.limit,
    params?.cursor,
    cleanup,
  ]);

  return state;
}
