import { describe, expect, it } from 'vitest';
import { formatApiErrorDetail } from './apiErrors';

describe('formatApiErrorDetail', () => {
  it('surfaces object-type region_not_supported message instead of Request failed (422)', () => {
    const detail = {
      error: 'region_not_supported',
      message: "Region not supported: 'us'. Council currently supports UK and Pakistan.",
      profile_id: 'us',
      supported: ['pk', 'uk'],
    };
    expect(formatApiErrorDetail(detail, 422)).toBe(
      "Region not supported: 'us'. Council currently supports UK and Pakistan.",
    );
    expect(formatApiErrorDetail(detail, 422)).not.toMatch(/Request failed/);
  });

  it('keeps string details and groq scrubbing', () => {
    expect(formatApiErrorDetail('plain failure', 400)).toBe('plain failure');
    expect(formatApiErrorDetail('model_not_found: xyz', 500)).toMatch(/could not finish/);
  });

  it('joins validation arrays', () => {
    expect(formatApiErrorDetail([{ msg: 'a' }, { msg: 'b' }], 422)).toBe('a; b');
  });

  it('falls back when detail is empty', () => {
    expect(formatApiErrorDetail(undefined, 422)).toBe('Request failed (422)');
    expect(formatApiErrorDetail({}, 503)).toBe('Request failed (503)');
  });
});
