from pathlib import Path

p = Path(r"d:\my personal projects\synthetic focus group\frontend\src\styles\bright-dash.css")
t = p.read_text(encoding="utf-8")

old_import = (
    "@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700"
    "&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap');"
)
new_import = (
    "@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500"
    "&family=Source+Sans+3:ital,wght@0,400;0,500;0,600;0,700;1,400"
    "&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap');"
)
t = t.replace(old_import, new_import, 1)

repls = [
    ("#e9edf2", "#1a1d21"),
    ("#8b949e", "#5c6570"),
    ("#e07060", "#c45c4a"),
    ("#5ba3d9", "#1b5f5a"),
    ("#c4a574", "#8b6914"),
    ("#7bb8e5", "#2f6f6a"),
    ("#3d7fad", "#154a46"),
    ("#101216", "#eef0f3"),
    ("#08090b", "#e8eaee"),
    ("#0c0e12", "#f3f4f6"),
    ("#151920", "#ffffff"),
    ("#0a0b0d", "#ffffff"),
    ("#0a0b0e", "#e8eaee"),
    ("#0e1014", "#f7f8fa"),
    ("#f2f3f5", "#1a1d21"),
    ("#f5f6f8", "#1a1d21"),
    ("rgba(255, 255, 255, 0.08)", "rgba(26, 29, 33, 0.1)"),
    ("rgba(255, 255, 255, 0.06)", "rgba(26, 29, 33, 0.08)"),
    ("rgba(255, 255, 255, 0.03)", "rgba(26, 29, 33, 0.04)"),
    ("rgba(255, 255, 255, 0.025)", "rgba(26, 29, 33, 0.045)"),
    ("rgba(255, 255, 255, 0.035)", "rgba(26, 29, 33, 0.05)"),
    ("rgba(255, 255, 255, 0.14)", "rgba(26, 29, 33, 0.18)"),
    ("'Fraunces', Georgia, 'Times New Roman', serif", "'Source Serif 4', Georgia, 'Times New Roman', serif"),
    ("'IBM Plex Sans', system-ui, sans-serif", "'Source Sans 3', 'Segoe UI', system-ui, sans-serif"),
    ("color-scheme: dark", "color-scheme: light"),
    ("0 16px 40px rgba(0, 0, 0, 0.45)", "0 1px 2px rgba(26, 29, 33, 0.06), 0 8px 24px rgba(26, 29, 33, 0.06)"),
    ("rgba(91, 163, 217, 0.2)", "rgba(27, 95, 90, 0.12)"),
    ("rgba(91, 163, 217, 0.07)", "rgba(27, 95, 90, 0.06)"),
    ("rgba(91, 163, 217, 0.08)", "rgba(27, 95, 90, 0.08)"),
    ("rgba(91, 163, 217, 0.28)", "rgba(27, 95, 90, 0.28)"),
    ("rgba(0, 0, 0, 0.35)", "rgba(26, 29, 33, 0.08)"),
    ("rgba(0, 0, 0, 0.45)", "rgba(26, 29, 33, 0.1)"),
]
for a, b in repls:
    t = t.replace(a, b)

# Fix root background block if still dark-ish
t = t.replace(
    """background:
    radial-gradient(ellipse 55% 40% at 0% 0%, rgba(27, 95, 90, 0.06), transparent 55%),
    radial-gradient(ellipse 45% 35% at 100% 100%, rgba(196, 165, 116, 0.04), transparent 50%),
    linear-gradient(180deg, #e8eaee 0%, #e8eaee 100%);""",
    """background:
    linear-gradient(180deg, #f3f4f6 0%, #e8eaee 48%, #e4e6eb 100%);""",
)

p.write_text(t, encoding="utf-8")
print("ok", p.stat().st_size)
