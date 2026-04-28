# Style Polish Skill

Use this skill when asked to improve writing style, readability, or flow across sections or chapters. Unlike `rewrite.md` (single-paragraph, 3 options), this skill polishes prose in place — one best version per section, applied directly.

## Voice and Pronouns

- Use **"we"** for own work, contributions, and decisions ("we conducted", "we found", "we propose")
- Use **"practitioners"** when referring to the broader audience or users of the work
- Never use "I", "the author", or passive constructions that hide agency ("it was found" → "we found")

## Sentence Structure

- **Break dense sentences**: if a sentence has 3+ clauses or exceeds ~40 words, split it. Two clear sentences beat one overloaded one
- **Vary sentence length**: alternate between short punchy sentences and longer explanatory ones
- **Avoid robotic enumeration**: never chain "First, ... Second, ... Third, ... Fourth, ... Finally, ..." across more than 3 items. Instead, use varied openers:
  - Acceptable for 2-3 items: "First, ... Second, ... Lastly, ..."
  - For 4+ items: group logically, use different connectors, or restructure as prose
- **Front-load the point**: lead with the insight or claim, then provide evidence — not the other way around

## Connectors and Transitions

- Use varied connector words between sentences. Rotate from this pool based on meaning:
  - **Addition**: furthermore, in addition, moreover, similarly, likewise, also, beyond this
  - **Contrast**: however, in contrast, conversely, nevertheless, yet, on the other hand, whereas
  - **Consequence**: consequently, as a result, therefore, thus, accordingly, in turn, hence
  - **Emphasis**: notably, in particular, specifically, importantly, significantly, crucially
  - **Sequence**: subsequently, next, then, following this, building on this, in parallel
  - **Example**: for instance, as seen in, as demonstrated by, consider
- **Never repeat the same connector** within the same paragraph
- **Do not overuse "However"** — limit to once per section; use alternatives

## Vocabulary

- **Avoid repeating key phrases** across sections. Track and rotate:
  - "significant gap stays" → "a notable gap persists", "this remains underexplored", "an open challenge endures"
  - "reveals" → "shows", "demonstrates", "indicates", "confirms", "highlights"
  - "focuses on" → "centres on", "targets", "addresses", "concentrates on"
- Use British English spelling (behaviour, analyse, modelling, organisation, colour)

## Formatting Rules

- No em dashes — use commas, semicolons, or restructure the sentence
- No colons as connectors between sentences
- Do not introduce formatting symbols (e.g., ---) unless explicitly requested
- Keep references in brackets [XX]
- Preserve all citations, cross-references, and technical terms exactly

## What NOT to Change

- **Do not regroup or reorder** PS studies, references, or numbered items — keep them in their original sequence
- **Do not add new content** or claims not present in the source
- **Do not remove content** — all information must be preserved
- **Do not change section structure** (headings, labels, subsection order)
- **Do not merge or split sections** unless explicitly asked
- Preserve the user's voice — improve flow without over-formalising

## Process

1. Read the target section(s) in both tgt notes and LaTeX
2. Identify specific style issues (robotic enumeration, dense sentences, repeated vocabulary, weak connectors)
3. **Present a change plan to the user BEFORE editing** using this table format:

   | # | Line | Issue | Current | Proposed | Why |
   |---|------|-------|---------|----------|-----|
   | 1 | 14 | Grammar | "rarely distinguishing" | "rarely distinguish" | Parallel structure |
   | 2 | 83 | Repetition | "perspective that provides" | "perspective that delivers" | "provide/provides" echo |

   - For longer rewrites where the full text does not fit in a table cell, show the table summary first, then the full before/after below the table
   - Number each change so the user can approve/reject individually (e.g., "1, 2 yes; 3 show options")
4. **Wait for user approval** before applying any edits
5. Once approved, apply the rewrite to **both** the LaTeX file and the corresponding tgt notes file — always keep them in sync
6. If the tgt notes file does not exist or the section is not present in it, skip the tgt update and note it to the user

**Never apply style changes without user approval.** The user must see and authorise every rewrite before it touches the file.
**Always update both files.** LaTeX and tgt notes must stay consistent — never update one without the other.

## Scope

- **Small scope** (1-2 paragraphs): present change inline, wait for approval, apply
- **Medium scope** (full section): present all changes for the section, wait for approval, apply
- **Large scope** (full chapter): work section by section — present changes per section, wait for approval per section, then move to next
