export interface DebateMessage {
  round: number;
  speaker: 'proponent' | 'opponent' | 'judge';
  content: string;
  timestamp?: string;
}

export interface JudgeVerdict {
  proponent_score: { coherence: number; evidence: number; rigor: number };
  opponent_score: { precision: number; novelty: number; fairness: number };
  logical_topology: {
    central_chain: string;
    fallacies_detected: string[];
    unresolved_contradictions: string[];
  };
  verdict: {
    status: string;
    justification: string;
    key_insight: string;
  };
}

export interface SSEEvent {
  type: string;
  speaker?: string;
  round?: number;
  content?: string;
  full_content?: string;
  verdict?: JudgeVerdict;
}

export interface DebateState {
  debateId: string | null;
  thesis: string;
  maxRounds: number;
  status: string;
  currentRound: number;
  currentSpeaker: string | null;
  proponentMessages: DebateMessage[];
  opponentMessages: DebateMessage[];
  liveText: { proponent: string; opponent: string };
  verdict: JudgeVerdict | null;
  error: string | null;
}