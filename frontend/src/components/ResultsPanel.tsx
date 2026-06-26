import { useState, useEffect } from 'react';
import type { FocusGroupResult } from '../types/focusGroup';

interface ResultsPanelProps {
  result: FocusGroupResult | null;
  loading: boolean;
  error: string | null;
}

type Tab = 'deliberation' | 'verdict';

export function ResultsPanel({ result, loading, error }: ResultsPanelProps) {
  const [activeTab, setActiveTab] = useState<Tab>('deliberation');

  useEffect(() => {
    if (result) setActiveTab('deliberation');
  }, [result]);

  return (
    <section className="flex flex-col h-full px-8 py-10 overflow-hidden">
      {/* Header + Tabs */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-base font-semibold text-white tracking-tight">
          {result ? 'Simulation Results' : 'Results'}
        </h2>
        {result && (
          <div className="flex bg-white/5 rounded-lg p-0.5 gap-0.5">
            {(['deliberation', 'verdict'] as Tab[]).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`
                  px-4 py-1.5 rounded-md text-xs font-medium transition-all duration-200
                  ${activeTab === tab
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'}
                `}
              >
                {tab === 'deliberation' ? '💬 Live Deliberation' : '⚖️ Final Verdict'}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {loading && <LoadingState />}
        {!loading && error && <ErrorState message={error} />}
        {!loading && !error && !result && <EmptyState />}
        {!loading && !error && result && (
          activeTab === 'deliberation'
            ? <DeliberationTab transcript={result.transcript} />
            : <VerdictTab verdict={result.verdict} rawVerdict={result.raw_verdict} />
        )}
      </div>
    </section>
  );
}

/* ─── Deliberation Tab ──────────────────────────────────────────────────── */

const AGENTS = [
  {
    key: 'skeptic' as const,
    name: 'The Skeptic',
    emoji: '🔎',
    label: 'Finding flaws & risks',
    ringColor: 'ring-red-500/30',
    bgColor: 'bg-red-500/8',
    borderColor: 'border-red-500/20',
    nameColor: 'text-red-400',
    badgeColor: 'bg-red-500/15 text-red-400',
  },
  {
    key: 'bargain_hunter' as const,
    name: 'The Bargain Hunter',
    emoji: '💸',
    label: 'Evaluating price & value',
    ringColor: 'ring-amber-500/30',
    bgColor: 'bg-amber-500/8',
    borderColor: 'border-amber-500/20',
    nameColor: 'text-amber-400',
    badgeColor: 'bg-amber-500/15 text-amber-400',
  },
  {
    key: 'target_fan' as const,
    name: 'The Target Fan',
    emoji: '⭐',
    label: 'Championing the product',
    ringColor: 'ring-emerald-500/30',
    bgColor: 'bg-emerald-500/8',
    borderColor: 'border-emerald-500/20',
    nameColor: 'text-emerald-400',
    badgeColor: 'bg-emerald-500/15 text-emerald-400',
  },
] as const;

function DeliberationTab({
  transcript,
}: {
  transcript: FocusGroupResult['transcript'];
}) {
  return (
    <div className="flex flex-col gap-4">
      {AGENTS.map((agent, i) => (
        <div
          key={agent.key}
          className={`
            rounded-xl border p-5
            ${agent.bgColor} ${agent.borderColor}
            animate-fade-slide-up
          `}
          style={{ animationDelay: `${i * 120}ms` }}
        >
          <div className="flex items-start gap-3">
            <div
              className={`
                flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center
                text-lg ring-2 ${agent.ringColor} bg-black/20
              `}
            >
              {agent.emoji}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-2">
                <span className={`text-sm font-semibold ${agent.nameColor}`}>
                  {agent.name}
                </span>
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${agent.badgeColor}`}>
                  {agent.label}
                </span>
              </div>
              <p className="text-sm text-slate-300 leading-relaxed">
                {transcript[agent.key]}
              </p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ─── Verdict Tab ───────────────────────────────────────────────────────── */

function VerdictTab({
  verdict,
  rawVerdict,
}: {
  verdict: FocusGroupResult['verdict'];
  rawVerdict?: string;
}) {
  const score = verdict.launch_score;

  return (
    <div className="flex flex-col gap-5 animate-fade-slide-up">
      {/* Score + Summary row */}
      <div className="flex gap-4">
        <div className="flex-shrink-0 flex flex-col items-center justify-center bg-white/5 border border-white/10 rounded-2xl p-6 w-44">
          <ScoreRing score={score} />
          <p className="text-xs text-slate-500 mt-3 font-medium uppercase tracking-widest">
            Launch Score
          </p>
        </div>
        <div className="flex-1 bg-white/5 border border-white/10 rounded-2xl p-5 flex flex-col justify-center">
          <p className="text-[11px] font-semibold text-indigo-400 uppercase tracking-widest mb-2">
            Executive Summary
          </p>
          <p className="text-sm text-slate-300 leading-relaxed">{verdict.summary}</p>
        </div>
      </div>

      {/* Red Flag + Selling Point / Psychological Hook */}
      <div className="grid grid-cols-2 gap-4">
        <InfoCard
          emoji="🚨"
          label="Biggest Red Flag"
          content={verdict.biggest_red_flag}
          bgColor="bg-red-500/8"
          borderColor="border-red-500/20"
          labelColor="text-red-400"
        />
        {score >= 40 ? (
          <InfoCard
            emoji="🚀"
            label="Biggest Selling Point"
            content={verdict.biggest_selling_point}
            bgColor="bg-emerald-500/8"
            borderColor="border-emerald-500/20"
            labelColor="text-emerald-400"
          />
        ) : (
          <InfoCard
            emoji="⚠️"
            label="Why Buyers Might Still Click"
            content={verdict.biggest_selling_point}
            bgColor="bg-amber-500/8"
            borderColor="border-amber-500/20"
            labelColor="text-amber-400"
          />
        )}
      </div>

      {rawVerdict && (
        <details className="rounded-xl border border-white/10 bg-white/3 overflow-hidden">
          <summary className="px-4 py-3 text-xs text-slate-500 cursor-pointer hover:text-slate-400 transition-colors">
            Raw Judge Output (parse failed)
          </summary>
          <pre className="px-4 pb-4 text-xs text-slate-500 whitespace-pre-wrap break-words font-mono">
            {rawVerdict}
          </pre>
        </details>
      )}
    </div>
  );
}

function InfoCard({
  emoji,
  label,
  content,
  bgColor,
  borderColor,
  labelColor,
}: {
  emoji: string;
  label: string;
  content: string;
  bgColor: string;
  borderColor: string;
  labelColor: string;
}) {
  return (
    <div className={`rounded-2xl border p-5 ${bgColor} ${borderColor}`}>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">{emoji}</span>
        <p className={`text-[11px] font-semibold uppercase tracking-widest ${labelColor}`}>
          {label}
        </p>
      </div>
      <p className="text-sm text-slate-300 leading-relaxed">{content}</p>
    </div>
  );
}

/* ─── Score Ring ────────────────────────────────────────────────────────── */

function ScoreRing({ score }: { score: number }) {
  const [animated, setAnimated] = useState(0);
  const r = 46;
  const circ = 2 * Math.PI * r;

  useEffect(() => {
    const t = setTimeout(() => setAnimated(score), 80);
    return () => clearTimeout(t);
  }, [score]);

  const color =
    score >= 70 ? '#10B981' : score >= 40 ? '#F59E0B' : '#EF4444';
  const label =
    score >= 70 ? 'Launch Ready' : score >= 40 ? 'Needs Work' : 'High Risk';

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative">
        <svg width="110" height="110" className="-rotate-90">
          <circle
            cx="55" cy="55" r={r}
            fill="none" stroke="#1e293b" strokeWidth="8"
          />
          <circle
            cx="55" cy="55" r={r}
            fill="none"
            stroke={color}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={circ - (animated / 100) * circ}
            style={{ transition: 'stroke-dashoffset 1.2s cubic-bezier(0.4,0,0.2,1)' }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-bold text-white">{score}</span>
        </div>
      </div>
      <span className="text-[11px] font-semibold" style={{ color }}>{label}</span>
    </div>
  );
}

/* ─── States ────────────────────────────────────────────────────────────── */

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-center select-none">
      <div className="w-16 h-16 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center text-3xl">
        🧪
      </div>
      <div>
        <p className="text-sm font-medium text-slate-300">No simulation yet</p>
        <p className="text-xs text-slate-600 mt-1 max-w-xs">
          Fill in your product details and hit <strong className="text-slate-500">Run Focus Group</strong> to start the AI debate.
        </p>
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-5 text-center">
      <div className="relative w-14 h-14">
        <div className="absolute inset-0 rounded-full border-2 border-indigo-500/20" />
        <div className="absolute inset-0 rounded-full border-2 border-t-indigo-500 animate-spin" />
        <div className="absolute inset-0 flex items-center justify-center text-xl">🤖</div>
      </div>
      <div>
        <p className="text-sm font-medium text-slate-300">Assembling the panel…</p>
        <p className="text-xs text-slate-600 mt-1">
          Skeptic → Bargain Hunter → Target Fan → Judge
        </p>
      </div>
      <div className="flex gap-1.5 mt-1">
        {['Skeptic', 'Bargain Hunter', 'Target Fan', 'Judge'].map((a, i) => (
          <span
            key={a}
            className="h-1.5 w-8 rounded-full bg-indigo-500/30 animate-pulse"
            style={{ animationDelay: `${i * 200}ms` }}
          />
        ))}
      </div>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
      <div className="w-12 h-12 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center text-2xl">
        ⚠️
      </div>
      <div>
        <p className="text-sm font-medium text-red-400">Simulation Failed</p>
        <p className="text-xs text-slate-500 mt-1 max-w-sm">{message}</p>
      </div>
    </div>
  );
}
