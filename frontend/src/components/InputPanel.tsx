import { useState, type FormEvent } from 'react';
import type { FocusGroupInput } from '../types/focusGroup';
import { CURRENCIES } from '../lib/currencies';

interface InputPanelProps {
  onSubmit: (data: FocusGroupInput) => void;
  loading: boolean;
}

const EMPTY: FocusGroupInput = {
  product_name: '',
  price: '',
  currency: 'USD',
  target_audience: '',
  description: '',
};

export function InputPanel({ onSubmit, loading }: InputPanelProps) {
  const [form, setForm] = useState<FocusGroupInput>(EMPTY);

  const set = (key: keyof FocusGroupInput) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>
  ) => setForm(prev => ({ ...prev, [key]: e.target.value }));

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!loading) onSubmit(form);
  };

  const textFields = ['product_name', 'price', 'target_audience', 'description'] as const;
  const isValid = textFields.every(k => form[k].trim().length > 0);

  return (
    <aside className="flex flex-col h-full px-8 py-10 border-r border-white/5">
      {/* Brand */}
      <div className="mb-10">
        <div className="flex items-center gap-2.5 mb-3">
          <span className="text-2xl">🧪</span>
          <span className="text-lg font-semibold tracking-tight text-white">
            Council
          </span>
        </div>
        <p className="text-sm text-slate-400 leading-relaxed">
          Instant AI-powered market validation — without burning ad spend.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-5 flex-1">
        <Field label="Product Name" required>
          <input
            type="text"
            placeholder="e.g. ErgoDesk Pro Standing Mat"
            value={form.product_name}
            onChange={set('product_name')}
            disabled={loading}
            className={inputCls}
          />
        </Field>

        {/* Price + Currency on the same row */}
        <Field label="Price & Currency" required>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="e.g. 79.99"
              value={form.price}
              onChange={set('price')}
              disabled={loading}
              className={`${inputCls} flex-1`}
            />
            <select
              value={form.currency}
              onChange={set('currency')}
              disabled={loading}
              className={selectCls}
            >
              {CURRENCIES.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code}
                </option>
              ))}
            </select>
          </div>
        </Field>

        <Field label="Target Audience" required>
          <input
            type="text"
            placeholder="e.g. Remote workers aged 25–45"
            value={form.target_audience}
            onChange={set('target_audience')}
            disabled={loading}
            className={inputCls}
          />
        </Field>

        <Field label="Product Description" required>
          <textarea
            rows={5}
            placeholder="Key features, materials, unique selling points…"
            value={form.description}
            onChange={set('description')}
            disabled={loading}
            className={`${inputCls} resize-none`}
          />
        </Field>

        <div className="mt-auto pt-4">
          <button
            type="submit"
            disabled={loading || !isValid}
            className="
              w-full py-3.5 px-6 rounded-xl font-semibold text-sm text-white
              bg-gradient-to-r from-indigo-600 to-violet-600
              hover:from-indigo-500 hover:to-violet-500
              disabled:opacity-40 disabled:cursor-not-allowed
              transition-all duration-200 shadow-lg shadow-indigo-900/40
              flex items-center justify-center gap-2.5
            "
          >
            {loading ? (
              <>
                <Spinner />
                Running Simulation…
              </>
            ) : (
              <>
                <span>▶</span>
                Run Council
              </>
            )}
          </button>
          <p className="text-center text-xs text-slate-600 mt-4">
            Powered by Groq · llama-3.3-70b-versatile
          </p>
        </div>
      </form>
    </aside>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium text-slate-400 uppercase tracking-wider">
        {label}
        {required && <span className="text-indigo-400 ml-0.5">*</span>}
      </label>
      {children}
    </div>
  );
}

function Spinner() {
  return (
    <svg
      className="animate-spin h-4 w-4 text-white"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        className="opacity-25"
        cx="12" cy="12" r="10"
        stroke="currentColor" strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}

const inputCls = `
  w-full bg-white/5 border border-white/10 rounded-lg px-4 py-2.5
  text-sm text-slate-200 placeholder-slate-600
  focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/50
  disabled:opacity-40 transition-colors duration-150
`;

const selectCls = `
  bg-white/5 border border-white/10 rounded-lg px-3 py-2.5
  text-sm text-slate-200
  focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/50
  disabled:opacity-40 transition-colors duration-150
  cursor-pointer appearance-none pr-7
  bg-[url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E")]
  bg-no-repeat bg-[center_right_0.5rem]
`;
