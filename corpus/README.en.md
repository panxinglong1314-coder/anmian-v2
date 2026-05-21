# Anmian English Knowledge Base (DRAFT)

This directory contains the English (`en`) parallel knowledge base for the
Anmian CBT-I AI companion. It is the first deliverable of the
"知眠 英文化" plan, step **1a — CBT-I knowledge corpus**.

> **Status: DRAFT. Not for production use without clinical review.**
> Despite being authored from public-domain English-native sources, every
> file in here describes clinical content (relaxation scripts, cognitive
> framing, crisis language). A licensed CBT-I clinician should review
> and adjust before this is exposed to real users — especially
> `safe_scripts.en.json` and `emotion_keywords.en.json` (the safety
> tier of the system).

## Files

Each English file mirrors the schema of its Chinese counterpart so
backend code can switch on `locale` without further structural changes:

| File | Size | Purpose |
|---|---:|---|
| `emotion_keywords.en.json` | 6.8 KB | Emotion / crisis / worry-domain lexicons (safety-critical) |
| `safe_scripts.en.json` | 5.3 KB | Crisis safety protocol (988, Crisis Text Line, Samaritans, Lifeline AU) |
| `cognitive_distortions.en.json` | 16 KB | 15 distortions with Socratic questions and reframes (Burns-style) |
| `breathing_scripts.en.json` | 23 KB | 4-7-8, Box, Diaphragmatic, Body Scan, Open Awareness, Loving-Kindness, Paradoxical Intention, Sleep Effort Reduction |
| `pmr_scripts.en.json` | 15 KB | Full PMR (14 regions), Express, PMR-Short (5 regions), PMR-Tiny (2 regions) |
| `closure_rituals.en.json` | 24 KB | 5 closure templates × 3 intensities = 15 variants + few-shot examples |
| `sleep_hygiene.en.json` | 6.3 KB | 7 topics (caffeine, alcohol, exercise, light, environment, schedule, routine) |
| `dCBT-I_protocol.en.json` | 15 KB | Complete dCBT-I protocol (sleep restriction, stimulus control, cognitive, hygiene, paradoxical, third-wave) |
| `worry_scenarios.en.json` | 14 KB | 8 worry domains (work, exam, relationship, health, future, financial, family, romantic) with technique routing |

## Source attribution

These files were authored from English-native, predominantly
public-domain sources rather than translated from the Chinese files:

- **VA CBT-I Therapist Manual** — US Department of Veterans Affairs, public domain.
  See https://www.med.upenn.edu/cbti/vamaterials.html
- **CBTI-M (Military) Therapist Manual** — cbtiweb.org
- **AASM CBT-I clinical practice guidelines**
- **D. Burns "Feeling Good"** — for cognitive distortion taxonomy (standard CBT)
- **Jacobson PMR (1938) / Bernstein & Borkovec abbreviated PMR** — standard, public-domain
- **MBSR / Body Scan** — Jon Kabat-Zinn tradition
- **Paradoxical Intention** — Viktor Frankl, adapted to CBT-I (Espie et al.)
- **C-SSRS / Columbia Protocol** — for crisis risk framing (Columbia Lighthouse Project)
- **988 Suicide & Crisis Lifeline** / Crisis Text Line / Samaritans / Lifeline AU — public crisis resources

Proprietary content was NOT used (Sleepio, Somryst, copyrighted manuals like Perlis et al.).

## What's intentionally NOT included

- `emollm_sleep.json` (4 MB) and `xinjing_data_raw.json` (45 MB) are the
  raw Chinese RAG corpora harvested from public materials. The English
  equivalents — additional English CBT-I educational documents to feed
  the RAG index — are a **separate workstream** (plan step 1e). When
  English documents are gathered, place them in `corpus/raw_en/` and
  rebuild the index per the plan.
- `CBT-I_MANUAL.md` and `README.md` — meta documents, unchanged for now.

## Wiring into the backend

The backend (`cbt_manager`, `rag_engine`, `emotion_analyzer`) currently
loads each file with `load_corpus("filename.json")`. To respect locale,
the loader should be made locale-aware, e.g.:

```python
def load_corpus(filename: str, locale: str = "zh") -> dict:
    base, ext = filename.rsplit(".", 1)
    candidate = CORPUS_DIR / f"{base}.{locale}.{ext}"
    if candidate.exists():
        path = candidate
    else:
        path = CORPUS_DIR / filename   # fallback to zh
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}
```

Then thread `locale` (from `ChatRequest.locale`, falling back to `"zh"`)
through `cbt_manager.process_message` and the other consumers (see plan
step 1f).

System prompts (`CBT_SYSTEM_PROMPT` in `main.py` and
`CBT_SYSTEM_PROMPT_V2` in `cbt_manager.py`) and the hardcoded user-facing
strings live in code, not corpus — they are step **1b** of the plan and
will be addressed in the follow-up commit.

## Review checklist before production

- [ ] Licensed CBT-I clinician reviews every script for clinical accuracy
- [ ] Suicide-prevention specialist reviews `safe_scripts.en.json` and
      the `level_severe` keywords in `emotion_keywords.en.json`
- [ ] Localize crisis hotlines per target country (US 988 vs UK Samaritans vs AU Lifeline)
- [ ] Red-team the crisis detection path with idiomatic English (slang,
      abbreviations, indirect phrasing)
- [ ] Verify legal / medical disclaimer copy (app-level)
- [ ] App Store / Play Store mental-health-app compliance review
