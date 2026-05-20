---
description: Add a new lesson to the lessons/ catalogue from the current conversation
---

# /capture-lesson

You're being asked to capture a lesson learned into the project's lessons
catalogue. The user has just experienced (or solved) a non-obvious pitfall
during LaTeX → MyST conversion that should be remembered.

## Steps

1. **Gather the lesson from conversation context.** Look back at the recent
   conversation to identify:
   - What went wrong (the symptom — what the user saw)
   - Why it happened (the root cause)
   - How it was fixed, or how to work around it
   - Whether the fix lives in the pipeline (`codified`) or is still a manual
     workaround (`open`)

   If any of these are unclear, ask the user one focused question before
   writing the file. Don't ask more than two questions.

2. **Pick the next sequential ID.** Read `LESSONS.md` to find the highest
   existing `id`, then use the next zero-padded integer (e.g., `009`, `010`,
   `011`).

3. **Pick a slug.** Short, kebab-case, descriptive. Look at existing files
   in `lessons/` for the style: `NNN-short-slug.md`.

4. **Write the lesson file** at `lessons/NNN-slug.md` using this template:

   ```markdown
   ---
   id: NNN
   title: "<one-line summary>"
   category: <preprocess|pandoc|post-processing|myst|katex|regex-safety|validation|tooling>
   tags: [tag1, tag2]
   source_project: <project name where this surfaced>
   status: <open|codified>
   codified_in: <file::function — only if status=codified>
   severity: <low|medium|high>
   date: <YYYY-MM-DD — today>
   ---

   ## Symptom
   What the user observes.

   ## Cause
   The underlying mechanism.

   ## Fix
   If codified: name the function/file and show a snippet.
   If open: describe the manual workaround.

   ## How to detect
   A regex, grep, or test that surfaces the issue. Optional but valuable.
   ```

5. **Update `LESSONS.md`** by:
   - Adding a row to the main table (insert in numeric order)
   - Adding the new ID under the right category in the "By category" section

6. **Confirm with the user** — show the path of the file created and the
   one-line summary. Ask if they want to refine anything.

## Quality bar

- Title must be specific enough that grepping for the symptom would find it.
- The "Cause" section must explain *why*, not just *what*. A lesson without
  a cause is a complaint, not knowledge.
- "How to detect" is optional but very valuable. A grep/regex that surfaces
  the issue lets future conversions catch the same bug automatically.
- If the lesson is project-specific (one-off bug in one book), say so — set
  `severity: low` and note it in the body. Generic lessons are more valuable
  but specific ones still belong in the catalogue if they're non-obvious.

## Don't

- Don't capture the same lesson twice — grep `LESSONS.md` for the symptom
  before writing.
- Don't mark `status: codified` unless the fix is actually in the pipeline.
  Promote later if needed.
- Don't paraphrase the user's words into something vague. Keep the symptom
  description concrete — exact error messages, file paths, line counts.
