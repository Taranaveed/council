import React from 'react';
import { useDebateStream } from '../hooks/useDebateStream';
import type { DebateMessage } from '../types/debate';

export default function DebateStage() {
  const { state, startDebate, stopDebate, resetDebate } = useDebateStream();
  const [thesisInput, setThesisInput] = React.useState('');
  const [roundsInput, setRoundsInput] = React.useState(3);

  const proponentScrollRef = React.useRef<HTMLDivElement>(null);
  const opponentScrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    proponentScrollRef.current?.scrollTo({ top: proponentScrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [state.liveText.proponent, state.proponentMessages]);

  React.useEffect(() => {
    opponentScrollRef.current?.scrollTo({ top: opponentScrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [state.liveText.opponent, state.opponentMessages]);

  const handleStart = () => {
    if (!thesisInput.trim()) return;
    startDebate(thesisInput.trim(), roundsInput);
  };

  const isRunning = state.status === 'running' || state.status === 'initializing';

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-mono">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-3 h-3 rounded-full bg-emerald-500 animate-pulse" />
            <h1 className="text-xl font-bold tracking-tight text-emerald-400">DIALECTIC NODE</h1>
            <span className="text-xs text-slate-500 uppercase tracking-widest">Multi-Agent Debate</span>
          </div>
          {state.status !== 'idle' && (
            <div className="flex gap-2 text-xs text-slate-400">
              <span className="px-2 py-1 rounded bg-slate-800 border border-slate-700">
                Round {state.currentRound} / {state.maxRounds}
              </span>
              <span className="px-2 py-1 rounded bg-slate-800 border border-slate-700 capitalize">
                {state.currentSpeaker || '—'}
              </span>
            </div>
          )}
        </div>
      </header>

      {state.error && (
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-rose-200">
            <strong>Error:</strong> {state.error}
          </div>
        </div>
      )}

      {/* Controls */}
      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="flex flex-col md:flex-row gap-4 items-end">
          <div className="flex-1 w-full">
            <label className="block text-xs text-slate-500 uppercase mb-2">Thesis Statement</label>
            <input
              type="text"
              value={thesisInput}
              onChange={(e) => setThesisInput(e.target.value)}
              placeholder="Enter a thesis to debate..."
              disabled={isRunning}
              className="w-full px-4 py-3 bg-slate-900 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-600 focus:outline-none focus:border-emerald-500 disabled:opacity-50"
            />
          </div>
          <div className="w-24">
            <label className="block text-xs text-slate-500 uppercase mb-2">Rounds</label>
            <input
              type="number" min={1} max={10}
              value={roundsInput}
              onChange={(e) => setRoundsInput(Number(e.target.value))}
              disabled={isRunning}
              className="w-full px-4 py-3 bg-slate-900 border border-slate-700 rounded-lg text-slate-200 text-center disabled:opacity-50"
            />
          </div>
          <div className="flex gap-2">
            {!isRunning && state.status !== 'completed' ? (
              <button onClick={handleStart} disabled={!thesisInput.trim()}
                className="px-6 py-3 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 text-white font-semibold rounded-lg">
                Start Debate
              </button>
            ) : (
              <button onClick={stopDebate} className="px-6 py-3 bg-rose-600 hover:bg-rose-500 text-white font-semibold rounded-lg">
                Stop
              </button>
            )}
            {state.status === 'completed' && (
              <button onClick={resetDebate} className="px-6 py-3 bg-slate-700 hover:bg-slate-600 text-white font-semibold rounded-lg">
                Reset
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Dual Terminals */}
      <div className="max-w-7xl mx-auto px-6 pb-12">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <TerminalPanel
            title="PROPONENT" subtitle="Chain-of-Thought Defense" color="emerald"
            messages={state.proponentMessages} liveText={state.liveText.proponent}
            isActive={state.currentSpeaker === 'proponent'} scrollRef={proponentScrollRef}
          />
          <TerminalPanel
            title="OPPONENT" subtitle="Red Team Critique" color="rose"
            messages={state.opponentMessages} liveText={state.liveText.opponent}
            isActive={state.currentSpeaker === 'opponent'} scrollRef={opponentScrollRef}
          />
        </div>

        {(state.proponentMessages.length > 0 || state.opponentMessages.length > 0) && (
          <div className="mt-8 grid grid-cols-1 xl:grid-cols-2 gap-6">
            <TranscriptPanel
              title="Proponent Transcript"
              messages={state.proponentMessages}
              color="emerald"
            />
            <TranscriptPanel
              title="Opponent Transcript"
              messages={state.opponentMessages}
              color="rose"
            />
          </div>
        )}

        {/* Verdict */}
        {state.verdict && (
          <div className="mt-8 p-6 bg-slate-900 border border-amber-500/30 rounded-xl">
            <h2 className="text-lg font-bold text-amber-400 mb-4">⚖️ Judge Verdict</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-4">
              <div>
                <h3 className="text-sm text-slate-400 uppercase mb-2">Proponent Scores</h3>
                <ScoreBar label="Coherence" value={state.verdict.proponent_score.coherence} color="emerald" />
                <ScoreBar label="Evidence" value={state.verdict.proponent_score.evidence} color="emerald" />
                <ScoreBar label="Rigor" value={state.verdict.proponent_score.rigor} color="emerald" />
              </div>
              <div>
                <h3 className="text-sm text-slate-400 uppercase mb-2">Opponent Scores</h3>
                <ScoreBar label="Precision" value={state.verdict.opponent_score.precision} color="rose" />
                <ScoreBar label="Novelty" value={state.verdict.opponent_score.novelty} color="rose" />
                <ScoreBar label="Fairness" value={state.verdict.opponent_score.fairness} color="rose" />
              </div>
            </div>
            <div className="p-4 bg-slate-950/50 rounded-lg border border-slate-800">
              <span className={`px-2 py-1 rounded text-xs font-bold ${
                state.verdict.verdict.status.includes('Strongly') ? 'bg-emerald-500/20 text-emerald-400' :
                state.verdict.verdict.status.includes('Moderately') ? 'bg-amber-500/20 text-amber-400' :
                state.verdict.verdict.status.includes('Weakly') ? 'bg-orange-500/20 text-orange-400' :
                'bg-rose-500/20 text-rose-400'
              }`}>{state.verdict.verdict.status}</span>
              <p className="mt-2 text-slate-300 text-sm">{state.verdict.verdict.justification}</p>
              <p className="mt-2 text-slate-400 text-sm italic">{state.verdict.verdict.key_insight}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

interface TerminalPanelProps {
  title: string;
  subtitle: string;
  color: 'emerald' | 'rose';
  messages: DebateMessage[];
  liveText: string;
  isActive: boolean;
  scrollRef: React.RefObject<HTMLDivElement | null>;
}

const colorStyles = {
  emerald: {
    border: 'border-emerald-500/30',
    bg: 'bg-emerald-500/5',
    headerBg: 'bg-emerald-500/10',
    text: 'text-emerald-400',
    badge: 'bg-emerald-500/20 text-emerald-400',
    cursor: 'bg-emerald-500',
  },
  rose: {
    border: 'border-rose-500/30',
    bg: 'bg-rose-500/5',
    headerBg: 'bg-rose-500/10',
    text: 'text-rose-400',
    badge: 'bg-rose-500/20 text-rose-400',
    cursor: 'bg-rose-500',
  },
};

function TerminalPanel({ title, subtitle, color, messages, liveText, isActive, scrollRef }: TerminalPanelProps) {
  const c = colorStyles[color];

  return (
    <div className={`rounded-xl border ${c.border} ${c.bg} overflow-hidden flex flex-col h-[500px]`}>
      <div className={`${c.headerBg} px-4 py-3 border-b ${c.border} flex items-center justify-between`}>
        <div className="flex items-center gap-3">
          <div className={`w-2 h-2 rounded-full ${isActive ? c.cursor + ' animate-pulse' : 'bg-slate-600'}`} />
          <div>
            <h3 className={`text-sm font-bold ${c.text} uppercase`}>{title}</h3>
            <p className="text-xs text-slate-500">{subtitle}</p>
          </div>
        </div>
        {isActive && <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${c.badge} animate-pulse`}>LIVE</span>}
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((msg, idx) => (
          <div key={idx} className={`p-3 rounded-lg border ${color === 'emerald' ? 'border-emerald-500/20 bg-emerald-500/5' : 'border-rose-500/20 bg-rose-500/5'}`}>
            <span className={`text-[10px] font-bold uppercase ${color === 'emerald' ? 'text-emerald-400' : 'text-rose-400'}`}>Round {msg.round}</span>
            <p className="mt-1 text-sm text-slate-300 whitespace-pre-wrap">{msg.content}</p>
          </div>
        ))}
        {liveText && (
          <div className={`p-3 rounded-lg border ${c.border} ${c.bg}`}>
            <span className="px-1.5 py-0.5 rounded bg-slate-800 text-[10px] text-slate-400">LIVE</span>
            <p className="mt-1 text-sm text-slate-300 whitespace-pre-wrap">
              {liveText}<span className={`inline-block w-2 h-4 ml-1 ${c.cursor} animate-pulse align-middle`} />
            </p>
          </div>
        )}
        {messages.length === 0 && !liveText && (
          <div className="h-full flex items-center justify-center text-slate-600 text-sm">Waiting...</div>
        )}
      </div>
    </div>
  );
}

function ScoreBar({ label, value, color }: { label: string; value: number; color: 'emerald' | 'rose' }) {
  const barColor = color === 'emerald' ? 'bg-emerald-500' : 'bg-rose-500';
  return (
    <div className="flex items-center gap-3 mb-2">
      <span className="text-xs text-slate-500 w-20">{label}</span>
      <div className="flex-1 h-2 bg-slate-800 rounded-full overflow-hidden">
        <div className={`h-full ${barColor} rounded-full transition-all`} style={{ width: `${(value / 5) * 100}%` }} />
      </div>
      <span className="text-xs text-slate-400 w-8 text-right">{value}/5</span>
    </div>
  );
}

function TranscriptPanel({ title, messages, color }: { title: string; messages: DebateMessage[]; color: 'emerald' | 'rose' }) {
  const c = colorStyles[color];
  return (
    <div className={`rounded-3xl border ${c.border} ${c.bg} p-6`}>
      <h2 className={`text-lg font-bold mb-4 ${c.text}`}>{title}</h2>
      <div className="space-y-4">
        {messages.map((msg, idx) => (
          <div key={idx} className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
            <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-slate-500 mb-2">
              <span>Round {msg.round}</span>
              <span>{msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString() : 'Live'}</span>
            </div>
            <p className="text-sm text-slate-200 whitespace-pre-wrap">{msg.content}</p>
          </div>
        ))}
        {messages.length === 0 && (
          <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/80 p-4 text-slate-500 text-sm">No messages yet.</div>
        )}
      </div>
    </div>
  );
}
