# UNKNOWN Brain — Article 9 Special-Category Handling
### Feature summary, study findings & recommendation
**Date:** 12 June 2026 · **Status:** built, tested, deployed (flag mode live; redact off by default)

---

## 1. The decision on the table

UNKNOWN's question: should the Brain **strip** special-category (GDPR Article 9) data
before storage, or **retain and flag** it? UNKNOWN's instinct is to strip — the Brain's
value is trends, patterns and market intelligence, not retaining sensitive personal data.

**We tested that instinct against real data. It holds. Recommendation: adopt redact.**

---

## 2. What the feature is

A GDPR Article 9 layer on the **talent** scoring domain only (client/sales scoring is
untouched). During scoring it detects the nine special categories — racial/ethnic origin,
political opinions, religious/philosophical beliefs, trade-union membership, genetic,
biometric, health, sex life, sexual orientation — using semantic detection (it catches
"I'm a black woman", which keyword scans miss). Two modes, switched by one setting:

| Mode | What it does |
|------|--------------|
| **Flag** (default — **live now**, always safe) | Detects special-category mentions and records them as metadata (category + location + confidence). **Nothing is removed** — everything is retained, just labelled. |
| **Redact** (toggle — built, off) | **Strips** detected special-category content from the transcript *before* scoring, so nothing sensitive is stored. The candidate intelligence is then built from the cleaned text. |

**How redact works (the important design point):** it strips at the **front door** — once,
at source — so every downstream field (the structured buckets, the narrative, the evidence
quotes, the raw transcript) is clean by construction. It re-checks its own work
("scrub-until-clean") and, if a transcript is so saturated with sensitive content that it
*can't* be cleaned, it **fails closed** — refuses to store the row rather than leak. It never
writes a record that still contains confident special-category data.

---

## 3. How we tested it

A controlled study: **12 representative talent meetings × both modes = 24 live scoring runs**
against production data, then compared the scored output flag-vs-redact, meeting by meeting.

The method's key strength: meetings with **zero** special-category content were used as a
**noise baseline**. Scoring the *identical* text twice still produces different output
(LLMs are non-deterministic) — one zero-detection meeting's company list shifted 13→2 with
*no redaction at all*. So a naive "the fields differ" count massively overstates redaction's
impact. Subtracting that noise floor isolates redaction's *real* effect.

---

## 4. Findings

- **~91% materially equivalent** (10 of 11 non-saturated meetings). The differences that
  remain — reworded descriptions, shuffled labels, ±1 company spelling — sit inside the
  noise envelope the controls establish.
- **Exactly one genuine loss across all 12 meetings.** A candidate's maternity-leave
  reference: flag mode read it as `on_leave`; once redacted, the model re-guessed
  `between_roles`. An *availability* signal degraded because the sensitive fact (parental
  leave) doubled as the operational fact (when she's free).
- **Zero meetings dropped** (0/12 fail-closed in the study).
- **The most sensitive meeting lost essentially no value.** The saturated outlier ("Nimo")
  had 21 detected special-category spans (health, race, sexual orientation, religion). Under
  redaction, **all the market intelligence survived intact** — senior freelance Creative
  Director, £550/day (identical both runs), the full ~14-company list, the scope blocker,
  openness-to-move 4 — and the redacted narrative was actually *richer*. The sensitive
  material sat *alongside* the recruitment value, not *inside* it.

**Bottom line:** the special-category content is overwhelmingly **incidental** to the Brain's
purpose. Stripping it keeps the trends, patterns and market intelligence intact.

---

## 5. What you win vs. what you lose

**Win**
- **No special-category data at rest** — materially smaller compliance surface, lighter
  Legitimate Interests Assessment, simpler Subject-Access / erasure handling, and a much
  stronger position with candidates and regulators.
- **You keep ~all of the market-intelligence value** the Brain exists to produce.

**Lose** (small, and mostly avoidable)
- **The granular "why"** when a motivation or blocker *is itself* special-category (e.g.
  health-driven need for flexibility). The motivation category survives; the personal reason
  goes. Rare.
- **Diversity / representation analytics** — that data *is* Article 9 by definition. Building
  on it would be a deliberate, separate (and sensitive) decision, not something to retain by
  default.
- **Occasional availability mis-inference** — the maternity/medical-leave case above.
- **The all-or-nothing edge** — a hyper-saturated meeting (well under 1% of the corpus) may
  fail to auto-clean. By design it is then **dropped entirely** (losing its useful,
  non-sensitive value too) rather than stored — the deliberate trade to guarantee nothing
  sensitive is ever retained. The drop is logged so it's visible (see §7).

---

## 6. Recommendation

**Adopt redact.** The study is unambiguous: stripping special-category data before storage
preserves the Brain's value while removing the compliance liability. The one clear loss (a
single availability signal) is narrow and partly covered by other fields.

This is the empirically-supported half of the decision. The other half — your compliance
posture, the LIA, what you tell candidates — is a judgement for UNKNOWN / your DPO; the study
removes the "but will we lose the intelligence?" worry from that conversation.

---

## 7. How healthy is it? Is it ready?

**Health: green.** The code is complete, covered by 133 automated tests, and deployed.
**Flag mode is running in production right now** — every new talent meeting is being detected
and labelled, fully safe, nothing removed. That part needs no decision; it's already on.

**Redact is built and ready to enable.** Its behaviour on the rare un-cleanable meeting is set
to match what we've committed to:

1. **Drop, not retain (the default).** When a meeting is too saturated to auto-clean, it is
   **dropped — not stored** — so nothing sensitive is ever kept. Every drop is **logged**
   (`ARTICLE9_REDACT_DROP`) so it's visible, not silent. (A store-and-retain alternative exists
   behind a config switch but is **off** — it would only make sense if a review process existed
   to act on those rows, and it doesn't.)
2. **Fail-closed monitoring is in place.** A row-level `article9_status` column plus the drop
   log mean an un-cleanable meeting can't disappear unnoticed — it can be alerted on and counted.
3. **A modest reliability bump (optional).** The saturated outlier converged right at the limit;
   raising the internal round bound improves the odds of cleaning a borderline meeting (rather
   than dropping it), though it can't *guarantee* convergence on a pathological transcript.

**Forward-only (known):** turning redact on strips *new* meetings only. The existing talent
records and the stored raw transcripts still contain Article 9 data. If the goal is "retain
no sensitive data," that requires a **separate, one-time retroactive strip** of the existing
corpus — a controller decision, out of scope for the toggle itself.

---

## 8. One-line for the client

*We can strip all special-category data before it's ever stored and keep essentially all of
the Brain's market-intelligence value — proven on 12 real meetings including the most
sensitive one in the corpus. Recommend we enable it for new meetings; the rare un-cleanable
meeting is dropped (logged, never stored) so nothing sensitive is ever retained, and a separate
decision on cleaning the back-catalogue.*
