"""Merge completed full-replay rows into one partial report for review."""
import json
from pathlib import Path

REPORT_DIR = Path(__file__).resolve().parent
# Prefer the first successful partial (L1+L2)
src = REPORT_DIR / "uk_benchmark_full_replay_20261026T025614Z.json"
d = json.loads(src.read_text(encoding="utf-8"))
out = {
    **d,
    "note": (
        "PARTIAL: only L1 scented candles + L2 ceramic mug completed on "
        "openai/gpt-oss-120b. Remaining 6 briefs blocked by Groq TPD "
        "(fail-on-fallback refused openai/gpt-oss-20b)."
    ),
    "remaining_queries": [
        "earphones",
        "notebooks",
        "uk plug extension lead",
        "lip gloss bulk",
        "nisbets catering foil rolls",
        "asdf qwer zxcv notaproduct",
    ],
}
path = REPORT_DIR / "uk_benchmark_full_replay_PARTIAL_8.json"
path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
print(path)
