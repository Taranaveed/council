import { AlertTriangle, ShieldCheck } from 'lucide-react';
import type { RiskScore } from '../lib/api';

export function RiskAlertBanner({ risk }: { risk: RiskScore }) {
  if (risk.score === 3) {
    return (
      <div
        role="alert"
        className="flex items-start gap-4 px-5 py-4 border-2 border-[#ff5a5f] bg-[#ff5a5f]/15 shadow-[0_12px_40px_rgba(255,90,95,0.18)] animate-[dashEnter_0.45s_ease_both]"
      >
        <AlertTriangle className="w-8 h-8 text-[#ff5a5f] flex-shrink-0 mt-0.5" aria-hidden />
        <div>
          <p className="text-xl font-bold text-[#9a1f2e] tracking-wide font-[Space_Grotesk,system-ui,sans-serif]">
            High risk
          </p>
          <p className="text-sm text-[#3d4f6f] mt-1 font-medium">
            Concerns came up about customs, warranty, and shipping. Be very careful, or walk away.
          </p>
        </div>
      </div>
    );
  }

  if (risk.score === 1) {
    return (
      <div
        role="status"
        className="flex items-start gap-3 px-5 py-3.5 border border-[#3ddc97]/50 bg-[#3ddc97]/15"
      >
        <ShieldCheck className="w-6 h-6 text-[#0a6b45] flex-shrink-0 mt-0.5" aria-hidden />
        <div>
          <p className="text-base font-semibold text-[#0a6b45]">Looks safer</p>
          <p className="text-sm text-[#3d4f6f] mt-0.5 font-medium">
            Only a mild concern was found. Still double-check the seller before you pay.
          </p>
        </div>
      </div>
    );
  }

  return null;
}
