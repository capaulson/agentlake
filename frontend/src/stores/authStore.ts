import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AuthState {
  apiKey: string | null;
  setApiKey: (key: string) => void;
  clearApiKey: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      apiKey: localStorage.getItem('agentlake-api-key') ?? 'test-admin-key',
      setApiKey: (key: string) => {
        localStorage.setItem('agentlake-api-key', key);
        set({ apiKey: key });
      },
      clearApiKey: () => {
        localStorage.removeItem('agentlake-api-key');
        set({ apiKey: null });
      },
    }),
    {
      name: 'agentlake-auth',
    },
  ),
);
