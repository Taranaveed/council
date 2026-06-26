import { useState, useCallback, useRef } from 'react';
import type { DebateState, SSEEvent, DebateMessage, JudgeVerdict } from '../types/debate';

const API_BASE = 'http://localhost:8000';

const initialState: DebateState = {
  debateId: null,
  thesis: '',
  maxRounds: 3,
  status: 'idle',
  currentRound: 0,
  currentSpeaker: null,
  proponentMessages: [],
  opponentMessages: [],
  liveText: { proponent: '', opponent: '' },
  verdict: null,
  error: null,
};

export function useDebateStream() {
  const [state, setState] = useState<DebateState>(initialState);
  const abortRef = useRef<AbortController | null>(null);

  const startDebate = useCallback(async (thesis: string, maxRounds: number = 3) => {
    setState({ ...initialState, thesis, maxRounds, status: 'initializing' });

    try {
      const initRes = await fetch(`${API_BASE}/debate/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // FORCING THE MODEL NAME HERE TO MATCH GROQ CAPABILITIES
        body: JSON.stringify({ 
          thesis, 
          max_rounds: maxRounds,
          model: "llama-3.3-70b-versatile" 
        }),
      });
      const initData = await initRes.json();
      const debateId = initData.debate_id;

      setState((prev) => ({ ...prev, debateId, status: 'running' }));

      abortRef.current = new AbortController();
      const response = await fetch(`${API_BASE}/debate/stream/${debateId}`, {
        signal: abortRef.current.signal,
        headers: {
          Accept: 'text/event-stream',
        },
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Stream failed: ${response.status} ${response.statusText} ${errorText}`);
      }

      if (!response.body) throw new Error('No response body');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6).trim();
            if (!jsonStr) continue;
            try {
              const event: SSEEvent = JSON.parse(jsonStr);
              handleSSEEvent(event, setState);
            } catch (e) {
              console.warn('Failed to parse SSE event:', jsonStr);
            }
          }
        }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        setState((prev) => ({ ...prev, status: 'idle' }));
      } else {
        setState((prev) => ({ ...prev, status: 'error', error: err.message }));
      }
    }
  }, []);

  const stopDebate = useCallback(() => {
    abortRef.current?.abort();
    setState((prev) => ({ ...prev, status: 'idle' }));
  }, []);

  const resetDebate = useCallback(() => {
    abortRef.current?.abort();
    setState(initialState);
  }, []);

  return { state, startDebate, stopDebate, resetDebate };
}

function handleSSEEvent(
  event: SSEEvent,
  setState: React.Dispatch<React.SetStateAction<DebateState>>
) {
  switch (event.type) {
    case 'turn_start':
      setState((prev) => ({
        ...prev,
        currentRound: event.round || prev.currentRound,
        currentSpeaker: event.speaker || null,
        liveText: { ...prev.liveText, [event.speaker!]: '' },
      }));
      break;

    case 'token':
      setState((prev) => ({
        ...prev,
        liveText: {
          ...prev.liveText,
          [event.speaker!]: prev.liveText[event.speaker as 'proponent' | 'opponent'] + (event.content || ''),
        },
      }));
      break;

    case 'turn_end': {
      const msg: DebateMessage = {
        round: event.round!,
        speaker: event.speaker! as 'proponent' | 'opponent' | 'judge',
        content: event.full_content || '',
        timestamp: new Date().toISOString(),
      };
      setState((prev) => {
        let newState = { ...prev, liveText: { ...prev.liveText, [event.speaker!]: '' } };
        if (event.speaker === 'proponent') {
          newState.proponentMessages = [...prev.proponentMessages, msg];
        } else if (event.speaker === 'opponent') {
          newState.opponentMessages = [...prev.opponentMessages, msg];
        }
        // Judge messages are handled separately in 'judge_verdict'
        return newState;
      });
      break;
    }

    case 'judge_verdict':
      setState((prev) => ({
        ...prev,
        verdict: event.verdict as JudgeVerdict,
        currentSpeaker: 'judge',
      }));
      break;

    case 'debate_complete':
      setState((prev) => ({ ...prev, status: 'completed', currentSpeaker: null }));
      break;

    case 'error':
      setState((prev) => ({ ...prev, status: 'error', error: event.content || 'Unknown error' }));
      break;
  }
}