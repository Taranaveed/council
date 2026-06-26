import { InputPanel } from './InputPanel';
import { ResultsPanel } from './ResultsPanel';
import { useFocusGroup } from '../hooks/useFocusGroup';
import type { FocusGroupInput } from '../types/focusGroup';

export function FocusGroupDashboard() {
  const { run, loading, error, result } = useFocusGroup();

  const handleSubmit = (data: FocusGroupInput) => {
    run(data);
  };

  return (
    <div className="min-h-screen bg-page flex flex-col">
      {/* Top bar */}
      <header className="flex-shrink-0 border-b border-white/5 px-8 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center justify-center w-6 h-6 rounded-md bg-indigo-600 text-xs">🧪</span>
          <span className="text-sm font-semibold text-white tracking-tight">Synthetic Focus Group</span>
          <span className="ml-2 text-[10px] font-medium px-2 py-0.5 rounded-full bg-indigo-500/15 text-indigo-400 border border-indigo-500/20">
            BETA
          </span>
        </div>
        <span className="text-xs text-slate-600">B2B Market Validation · AI-Powered</span>
      </header>

      {/* Split screen */}
      <div className="flex-1 grid grid-cols-[380px_1fr] overflow-hidden">
        <InputPanel onSubmit={handleSubmit} loading={loading} />
        <ResultsPanel result={result} loading={loading} error={error} />
      </div>
    </div>
  );
}
