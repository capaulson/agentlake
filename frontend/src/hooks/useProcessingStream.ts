import { useState, useEffect, useRef, useCallback } from 'react';

interface ProcessingStreamState {
  stage: string;
  progress: number;
  message: string;
  isComplete: boolean;
  isError: boolean;
  error: string | null;
}

interface ProcessingEvent {
  stage: string;
  progress: number;
  message: string;
  status?: 'complete' | 'error';
  error?: string;
}

const INITIAL_STATE: ProcessingStreamState = {
  stage: '',
  progress: 0,
  message: '',
  isComplete: false,
  isError: false,
  error: null,
};

const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_RECONNECT_DELAY_MS = 1_000;

export function useProcessingStream(
  fileId: string | null,
): ProcessingStreamState {
  const [state, setState] = useState<ProcessingStreamState>(INITIAL_STATE);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectAttempts = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cleanup = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
  }, []);

  const connect = useCallback(
    (id: string) => {
      cleanup();

      const baseUrl = import.meta.env.VITE_API_URL ?? '/api/v1';
      const url = `${baseUrl}/stream/processing/${id}`;
      const es = new EventSource(url);
      eventSourceRef.current = es;

      es.onmessage = (event: MessageEvent<string>) => {
        reconnectAttempts.current = 0;

        const data = JSON.parse(event.data) as ProcessingEvent;

        setState({
          stage: data.stage,
          progress: data.progress,
          message: data.message,
          isComplete: data.status === 'complete',
          isError: data.status === 'error',
          error: data.error ?? null,
        });

        // Close connection on terminal states
        if (data.status === 'complete' || data.status === 'error') {
          es.close();
        }
      };

      es.onerror = () => {
        es.close();

        if (reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
          const delay =
            BASE_RECONNECT_DELAY_MS *
            Math.pow(2, reconnectAttempts.current);
          reconnectAttempts.current += 1;

          reconnectTimer.current = setTimeout(() => {
            connect(id);
          }, delay);
        } else {
          setState((prev) => ({
            ...prev,
            isError: true,
            error: 'Lost connection to processing stream',
          }));
        }
      };
    },
    [cleanup],
  );

  useEffect(() => {
    if (!fileId) {
      cleanup();
      setState(INITIAL_STATE);
      return;
    }

    reconnectAttempts.current = 0;
    setState(INITIAL_STATE);
    connect(fileId);

    return cleanup;
  }, [fileId, connect, cleanup]);

  return state;
}
