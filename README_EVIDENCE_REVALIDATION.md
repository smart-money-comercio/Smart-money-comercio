# Rules 25 evidence revalidation hotfix

This fixes a reproduced cause of `Story facts or event stage do not match the admitted original evidence` during `/quality` and repeated news builds. An admitted plain-text excerpt could contain literal entity or angle-bracket wording. Re-parsing that excerpt as HTML changed its bytes during validation. The same defect occurred in editorial-priority evidence review.

Raw source input still passes through the original normalizer on admission. Validation now reconstructs the expected facts and stage from the exact admitted plain text. It retains full comparison of schema, scope, source URL, publication and observation clocks, source text, SHA-256 and fact fields. Priority evidence also retains its expected profile schema. Invalid original candidates are held before selection and their rejected profiles are removed from the candidate log; they cannot fall back to a selected headline.

The hotfix retains **Editorial rules: 25** and the existing reader/evidence schemas. It does not rewrite an edition, delete caches, change ranking scores or activate the premarket desk. Previously valid saved reports, scripts and schema-2 exports retain their hashes. The supplied text brief does not contain the raw failing candidate, so the exact production excerpt cannot be identified from that attachment alone. The regression uses clearly synthetic text that reproduces the reported exception and exercises the actual `/quality` command. New mismatch errors include the source ID and mismatched field names to support further diagnosis.

## Check

```bash
.venv/bin/python scripts/check_evidence_revalidation.py
.venv/bin/python scripts/check_evidence_revalidation.py --windows-socketpair
```

The suite covers raw HTML admission, nested entities, literal angle brackets, repeated validation, strict tampering rejection, complete news builds, priority checks, cache changes, invalid-candidate isolation, the actual quality card/command and saved-edition hashes. No networking, Telegram channel delivery or paid generation runs during these checks.

After installation, run `/rundailyagent`, `/quality`, `/editorstatus` and `/voiceover`. Require a fresh runtime quality PASS before proceeding to rules 26. The updated rules 26 package includes this same fix. Ordinary source-coverage limits remain visible.
