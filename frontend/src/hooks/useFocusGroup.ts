import { useState } from 'react';
import type { FocusGroupInput, FocusGroupResult } from '../types/focusGroup';

const API_URL = 'http://localhost:8000/focus-group/run';

export function useFocusGroup() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FocusGroupResult | null>(null);

  const run = async (input: FocusGroupInput) => {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail ?? 'The focus group simulation failed.');
      }

      const data: FocusGroupResult = await res.json();
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'An unexpected error occurred.');
    } finally {
      setLoading(false);
    }
  };

  return { run, loading, error, result };
}
