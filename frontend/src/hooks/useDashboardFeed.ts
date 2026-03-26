import { useState, useEffect, useRef, useCallback } from 'react';

export interface DashboardStats {
  total_files: number;
  total_documents: number;
  tokens_today: number;
  cost_today_usd: number;
  queue_depth: number;
  processing_active: number;
}

interface DashboardFeedState {
  stats: DashboardStats | null;
  isConnected: boolean;
}

const MAX_RECONNECT_ATTEMPTS = 10;
const BASE_RECONNECT_DELAY_MS = 1_000;

export function useDashboardFeed(): DashboardFeedState {
  const [state, setState] = useState<DashboardFeedState>({
    stats: null,
    isConnected: false,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempts = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const cleanup = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    cleanup();

    if (!mountedRef.current) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsBase =
      import.meta.env.VITE_WS_URL ??
      `${protocol}//${window.location.host}/api/v1`;
    const url = `${wsBase}/ws/dashboard`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      reconnectAttempts.current = 0;
      setState((prev) => ({ ...prev, isConnected: true }));
    };

    ws.onmessage = (event: MessageEvent<string>) => {
      if (!mountedRef.current) return;
      const data = JSON.parse(event.data) as DashboardStats;
      setState({ stats: data, isConnected: true });
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setState((prev) => ({ ...prev, isConnected: false }));

      if (reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
        const delay =
          BASE_RECONNECT_DELAY_MS *
          Math.pow(2, reconnectAttempts.current);
        reconnectAttempts.current += 1;

        reconnectTimer.current = setTimeout(() => {
          if (mountedRef.current) {
            connect();
          }
        }, delay);
      }
    };

    ws.onerror = () => {
      // onerror is always followed by onclose, so reconnect logic is there
    };
  }, [cleanup]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [connect, cleanup]);

  return state;
}
