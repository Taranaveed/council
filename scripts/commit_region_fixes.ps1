# Creates 7 commits for the region/landed-cost fixes (requires git on PATH).
# Run from repo root: powershell -File scripts/commit_region_fixes.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

function Commit-Step($msg, $paths) {
  git add -- @paths
  $staged = git diff --cached --name-only
  if (-not $staged) {
    Write-Host "SKIP (nothing staged): $msg"
    return
  }
  git commit -m $msg
  Write-Host "OK: $msg"
}

Commit-Step @"
fix: reject unsupported regions instead of silent UK/PK fallback

Deal Finder and market-service return region_not_supported when the
resolved profile JSON is missing (e.g. US). No us.json added.
"@ @(
  "backend/app/core/region_profile.py",
  "backend/app/api/modes.py",
  "backend/tests/test_region_not_supported.py",
  "backend/tests/test_region_profile_phase1.py",
  "market-service/regionProfile.js",
  "market-service/index.js",
  "market-service/test/region_profile_phase1.test.js"
)

Commit-Step @"
fix: build landed-cost assumptions per listing origin

Domestic origins get duty 0 and import VAT 0, with domestic VAT as a
separate reclaimable line when the buyer is VAT-registered.
"@ @(
  "backend/app/utils/cost_assumptions.py",
  "backend/app/utils/landed_cost.py",
  "backend/app/api/modes.py",
  "backend/tests/test_phase1_gates.py"
)

Commit-Step @"
fix: use compute_landed_cost for table and brief mid display

Remove estimate_landed_mid; show needs quote when landed cannot be
computed so table, brief, and agents share one value.
"@ @(
  "backend/app/utils/supplier_table.py"
)

Commit-Step @"
fix: clear winner and BEST badge on Skip, keep row landed costs

Skip/PASS/NO_MATCH strips best_pick and winner identity while leaving
per-listing landed_cost intact for the comparison table.
"@ @(
  "backend/app/api/modes.py",
  "backend/app/utils/supplier_table.py"
)

Commit-Step @"
fix: require sourced facts for consumer-law and platform policy claims

Remove hardcoded Consumer Rights Act guidance from global/risk prompts;
gate regulatory text by region profile; scrub UK profile CRA phrasing.
"@ @(
  "backend/app/agents/deal_finder_prompts.py",
  "shared/region_profiles/uk.json"
)

Commit-Step @"
fix: label flat duty fallback as estimated, not a tariff lookup

Surface the fallback label on landed assumptions, formula, table mid,
and agent authoritative cost blocks.
"@ @(
  "backend/app/utils/cost_assumptions.py",
  "backend/app/utils/landed_cost.py",
  "backend/app/utils/supplier_table.py",
  "backend/app/api/modes.py"
)

Commit-Step @"
test: add region landed-cost and prompt regression suite

Cover unsupported US, UK domestic/CN/EU origins, table==brief mid,
Skip without BEST, and UK prompts free of Pakistan/Karachi/CRA text.
"@ @(
  "backend/tests/test_region_fixes_phase2.py",
  "scripts/commit_region_fixes.ps1"
)

git status -sb
git log -7 --oneline
