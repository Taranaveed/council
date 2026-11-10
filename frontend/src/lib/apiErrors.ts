/** Format FastAPI / API Gateway error bodies into a user-visible string. */

export type ApiErrorDetail =
  | string
  | Array<{ msg?: string } | string>
  | { message?: string; detail?: string; error?: string; [key: string]: unknown }
  | null
  | undefined;

/**
 * Prefer structured `detail.message` (e.g. region_not_supported) over
 * generic "Request failed (422)".
 */
export function formatApiErrorDetail(detail: ApiErrorDetail, status: number): string {
  const fallback = `Request failed (${status})`;
  if (detail == null) return fallback;

  if (typeof detail === 'string') {
    if (/groq|model_not_found|invalid_request|rate_limit/i.test(detail)) {
      return 'The agents could not finish this run. Wait a moment and try again.';
    }
    return detail.trim() || fallback;
  }

  if (Array.isArray(detail)) {
    const parts = detail.map((d) =>
      typeof d === 'string' ? d : d?.msg || JSON.stringify(d),
    );
    const joined = parts.filter(Boolean).join('; ');
    return joined || fallback;
  }

  if (typeof detail === 'object') {
    const message = typeof detail.message === 'string' ? detail.message.trim() : '';
    if (message) return message;
    const nested = typeof detail.detail === 'string' ? detail.detail.trim() : '';
    if (nested) return nested;
    if (typeof detail.error === 'string' && detail.error.trim()) {
      return detail.error.trim();
    }
  }

  return fallback;
}
