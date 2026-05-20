#!/usr/bin/env python3
"""Post-process pandoc markdown output into MyST Markdown.

Transforms pandoc's markdown syntax into proper MyST Markdown:
- ::: envname ... ::: → ```{prf:envname} ... ```
- pandoc cross-refs → MyST {ref}, {eq}, {prf:ref}, {numref}
- pandoc citations → MyST {cite} / {cite:t}
- $$\\begin{equation}...\\end{equation}$$ → $$ ... $$ (label)
- ![cap](path){attrs} → ```{figure} ... ```
- labels: colons → hyphens

This is the generic transform library from claude-latex-to-myst. Project-specific
data (chapter titles, TikZ resolution maps) is loaded from a YAML config and an
optional Python overrides file — never hard-coded here.

Usage:
    postprocess.py --config path/to/config.yaml [INPUT_FILE ...]

If INPUT_FILE args are given, only those files are processed. Otherwise every
chapter listed in the config is processed.
"""

import argparse
import base64
import importlib.util
import re
import sys
from pathlib import Path

# ── Environment mapping ──────────────────────────────────────────────────────

ENV_MAP = {
    # sphinx-proof environments
    'theorem':        'prf:theorem',
    'boxtheorem':     'prf:theorem',
    'lemma':          'prf:lemma',
    'proof':          'prf:proof',
    'definition':     'prf:definition',
    'boxdefinition':  'prf:definition',
    'proposition':    'prf:proposition',
    'boxproposition': 'prf:proposition',
    'corollary':      'prf:corollary',
    'boxcorollary':   'prf:corollary',
    'example':        'prf:example',
    'remark':         'prf:remark',
    'assumption':     'prf:assumption',
    'algorithm':      'prf:algorithm',
    # MyST exercise directive
    'Exercise':       'exercise',
    'Answer':         'solution',
}

# Track the last exercise label so we can associate solutions
_last_exercise_label = None

# Counter for auto-generated exercise labels (reset per file)
_exercise_counter = 0

# Chapter prefix for auto-generated labels (set per file)
_chapter_prefix = ''

# Environments to skip (remove the div wrapper, keep content)
ENV_SKIP = {'multicols', 'minipage', 'center'}

# Prose nouns that get doubled by writers in front of a {prf:ref}. Sphinx-proof
# auto-renders the noun (e.g. "Theorem 1.2"), so leaving the prose noun produces
# "Theorem Theorem 1.2" in the output. The second column is the label prefix
# that confirms the ref points to that kind of object — guards against stripping
# "Theorem ..." in front of a ref to something unrelated.
_DOUBLED_NOUN_REFS = [
    ('Algorithm',   'algo-'),
    ('Assumption',  'a-'),
    ('Chapter',     'c-'),
    ('Corollary',   'c-'),
    ('Exercise',    'ex-'),
    ('Lemma',       'l-'),
    ('Proposition', 'p-'),
    ('Remark',      'r-'),
    ('Theorem',     't-'),
]


def convert_label_colons(label: str) -> str:
    """Convert colons to hyphens in a label: 'thm:main' → 'thm-main'."""
    return label.replace(':', '-')


def convert_environment_divs(text: str) -> str:
    """Convert ::: envname ... ::: blocks to MyST directives.
    
    Handles:
    - ::: theorem ... ::: → ```{prf:theorem} ... ```
    - ::: Exercise ... ::: → ```{exercise} ... ```
    - ::: Answer ... ::: → ```{solution} ... ```
    - Nested labels []{#label label="label"} → :label: converted-label
    - *Proof.* markers inside proof blocks → removed (sphinx-proof adds its own)
    """
    lines = text.split('\n')
    result = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Match :::+ envname or :::+ {.envname} (3 or more colons)
        env_match = re.match(r'^:{3,} \{?\.?(\w+)\}?\s*$', line)
        
        # Match :::+ {#id} — generic div with just an id attribute
        id_div_match = re.match(r'^:{3,} \{#([^}\s]+)\}\s*$', line) if not env_match else None
        
        if id_div_match:
            div_id = convert_label_colons(id_div_match.group(1))
            # Emit a target label and keep the content
            result.append(f'({div_id})=')
            i += 1
            while i < len(lines) and not re.match(r'^:{3,}\s*$', lines[i]):
                result.append(lines[i])
                i += 1
            i += 1  # skip closing :::
            continue
        
        if env_match:
            env_name = env_match.group(1)
            
            if env_name in ENV_SKIP:
                # Skip the div wrapper, keep content (with nesting awareness)
                i += 1
                depth = 1
                while i < len(lines) and depth > 0:
                    if re.match(r'^:{3,}\s*$', lines[i]):
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                        # Inner closing — skip it too
                    elif re.match(r'^:{3,} \w+', lines[i]):
                        depth += 1
                    else:
                        result.append(lines[i])
                    i += 1
                continue
            
            myst_env = ENV_MAP.get(env_name)
            if myst_env is None:
                # Unknown environment — keep as-is with a comment
                result.append(f'% Unknown environment: {env_name}')
                result.append(line)
                i += 1
                continue
            
            # Collect the body of the ::: block
            i += 1
            body_lines = []
            depth = 1
            while i < len(lines):
                if re.match(r'^:{3,}\s*$', lines[i]):
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                elif re.match(r'^:{3,} \w+', lines[i]):
                    depth += 1
                body_lines.append(lines[i])
                i += 1
            
            # Extract label from body if present
            label = None
            title = None
            clean_body = []
            for bline in body_lines:
                # Match []{#label label="label"} on its own line
                lm = re.match(r'^\[\]\{#([^\s}]+)(?:\s+label="[^"]*")?\}\s*$', bline)
                if lm:
                    label = convert_label_colons(lm.group(1))
                    continue
                # Match []{#label label="label"} at START of a line with more text
                lm2 = re.match(r'^\[\]\{#([^\s}]+)(?:\s+label="[^"]*")?\}\s+(.+)$', bline)
                if lm2:
                    label = convert_label_colons(lm2.group(1))
                    rest = lm2.group(2).strip()
                    if rest:
                        clean_body.append(rest)
                    continue
                # Match []{#label label="label"} at END of a line (e.g., algorithm captions)
                lm3 = re.search(r'\[\]\{#([^\s}]+)(?:\s+label="[^"]*")?\}\s*$', bline)
                if lm3 and not lm3.start() == 0:
                    label = convert_label_colons(lm3.group(1))
                    rest = bline[:lm3.start()].strip()
                    if rest:
                        clean_body.append(rest)
                    continue
                # For proof blocks, remove *Proof.* marker
                if myst_env == 'prf:proof' and re.match(r'^\*Proof\.\*\s*', bline):
                    rest = re.sub(r'^\*Proof\.\*\s*', '', bline).strip()
                    if rest:
                        clean_body.append(rest)
                    continue
                # Remove QED symbol
                if bline.strip() == '◻':
                    continue
                clean_body.append(bline)
            
            # Strip leading/trailing blank lines from body
            while clean_body and clean_body[0].strip() == '':
                clean_body.pop(0)
            while clean_body and clean_body[-1].strip() == '':
                clean_body.pop()
            
            # Build the MyST directive
            header = f'```{{{myst_env}}}'
            
            global _last_exercise_label, _exercise_counter
            
            if myst_env == 'exercise':
                # Track exercise label for pairing with solution
                if not label:
                    # Auto-generate label for unlabeled exercises
                    _exercise_counter += 1
                    label = f'ex-{_chapter_prefix}-auto-{_exercise_counter}'
                _last_exercise_label = label
            elif myst_env == 'solution':
                # Solution needs the exercise label as argument
                if _last_exercise_label:
                    header = f'```{{solution}} {_last_exercise_label}'
                _last_exercise_label = None
            
            result.append(header)
            if label and myst_env != 'solution':
                result.append(f':label: {label}')
            if clean_body:
                result.append('')
                result.extend(clean_body)
            result.append('```')
            result.append('')
            continue
        
        result.append(line)
        i += 1
    
    return '\n'.join(result)


def fix_text_dollar(text: str) -> str:
    r"""Fix \text{...$...$...} for KaTeX compatibility.
    
    KaTeX cannot handle $ inside \text{}. Transform:
      \text{before $math$ after} → \text{before } math \text{ after}
    """
    output = []
    i = 0
    while i < len(text):
        # Look for \text{
        m = re.search(r'\\text\s*\{', text[i:])
        if not m:
            output.append(text[i:])
            break
        
        # Append everything before \text{
        output.append(text[i:i + m.start()])
        brace_start = i + m.end()
        
        # Find matching } with brace counting
        depth = 1
        j = brace_start
        while j < len(text) and depth > 0:
            if text[j] == '{' and (j == 0 or text[j-1] != '\\'):
                depth += 1
            elif text[j] == '}' and (j == 0 or text[j-1] != '\\'):
                depth -= 1
            j += 1
        
        content = text[brace_start:j-1]  # content inside \text{...}
        
        if '$' not in content:
            # No dollar signs — emit as-is
            output.append(text[i + m.start():j])
            i = j
            continue
        
        # Split content on $...$ pairs
        parts = re.split(r'\$([^$]*)\$', content)
        # parts[0], parts[2], parts[4], ... are text segments
        # parts[1], parts[3], parts[5], ... are math segments
        
        segments = []
        for k, part in enumerate(parts):
            if k % 2 == 0:
                # Text segment
                if part:
                    segments.append(r'\text{' + part + '}')
            else:
                # Math segment
                segments.append(part)
        
        output.append(' '.join(s for s in segments if s))
        i = j
    
    return ''.join(output)


def convert_equations(text: str) -> str:
    """Convert pandoc equation blocks to MyST format.
    
    Patterns:
    - $$\\begin{equation}\\label{eq:foo} ... \\end{equation}$$ 
      → $$ ... $$ (eq-foo)
    - $$\\begin{equation*} ... \\end{equation*}$$
      → $$ ... $$
    - $$\\begin{align} ... \\end{align}$$
      → $$ \\begin{aligned} ... \\end{aligned} $$ (label)
    """
    # Pattern: $$\begin{equation}\label{...} ... \end{equation}$$ (on one line)
    def replace_labeled_equation(m):
        label = convert_label_colons(m.group(1))
        content = m.group(2).strip()
        return f'$$\n{content}\n$$ ({label})'
    
    text = re.sub(
        r'\$\$\\begin\{equation\}\s*\\label\{([^}]+)\}\s*(.*?)\\end\{equation\}\$\$',
        replace_labeled_equation,
        text,
        flags=re.DOTALL
    )
    
    # Pattern: $$\begin{equation*} ... \end{equation*}$$ (unlabeled)
    def replace_unlabeled_equation(m):
        content = m.group(1).strip()
        return f'$$\n{content}\n$$'
    
    text = re.sub(
        r'\$\$\\begin\{equation\*\}\s*(.*?)\\end\{equation\*\}\$\$',
        replace_unlabeled_equation,
        text,
        flags=re.DOTALL
    )
    
    # Pattern: $$\begin{equation} ... \end{equation}$$ (unlabeled, no *)
    text = re.sub(
        r'\$\$\\begin\{equation\}\s*(.*?)\\end\{equation\}\$\$',
        replace_unlabeled_equation,
        text,
        flags=re.DOTALL
    )
    
    # Pattern: $$\begin{align}\label{...} ... \end{align}$$
    def replace_labeled_align(m):
        label = convert_label_colons(m.group(1))
        content = m.group(2).strip()
        return f'$$\n\\begin{{aligned}}\n{content}\n\\end{{aligned}}\n$$ ({label})'
    
    text = re.sub(
        r'\$\$\\begin\{align\}\s*\\label\{([^}]+)\}\s*(.*?)\\end\{align\}\$\$',
        replace_labeled_align,
        text,
        flags=re.DOTALL
    )
    
    # Pattern: $$\begin{align*} ... \end{align*}$$ (unlabeled)
    def replace_unlabeled_align(m):
        content = m.group(1).strip()
        return f'$$\n\\begin{{aligned}}\n{content}\n\\end{{aligned}}\n$$'
    
    text = re.sub(
        r'\$\$\\begin\{align\*?\}\s*(.*?)\\end\{align\*?\}\$\$',
        replace_unlabeled_align,
        text,
        flags=re.DOTALL
    )
    
    # Pattern: $$\begin{multline}\label{...} ... \end{multline}$$
    def replace_labeled_multline(m):
        label = convert_label_colons(m.group(1))
        content = m.group(2).strip()
        return f'$$\n{content}\n$$ ({label})'
    
    text = re.sub(
        r'\$\$\\begin\{multline\*?\}\s*\\label\{([^}]+)\}\s*(.*?)\\end\{multline\*?\}\$\$',
        replace_labeled_multline,
        text,
        flags=re.DOTALL
    )
    
    # Unlabeled multline
    text = re.sub(
        r'\$\$\\begin\{multline\*?\}\s*(.*?)\\end\{multline\*?\}\$\$',
        replace_unlabeled_equation,
        text,
        flags=re.DOTALL
    )
    
    # Pattern: $$\begin{gather}\label{...} ... \end{gather}$$
    text = re.sub(
        r'\$\$\\begin\{gather\*?\}\s*\\label\{([^}]+)\}\s*(.*?)\\end\{gather\*?\}\$\$',
        replace_labeled_multline,
        text,
        flags=re.DOTALL
    )
    
    text = re.sub(
        r'\$\$\\begin\{gather\*?\}\s*(.*?)\\end\{gather\*?\}\$\$',
        replace_unlabeled_equation,
        text,
        flags=re.DOTALL
    )
    
    # Handle remaining \label{} inside $$ blocks (e.g., inside align that wasn't caught)
    # Pattern: \label{eq:foo} inside a $$ block → extract to after $$
    def extract_label_from_math(m):
        before = m.group(1)
        label = convert_label_colons(m.group(2))
        after = m.group(3)
        content = before + after
        # Remove the \label line
        content = content.strip()
        return f'{content}\n$$ ({label})'
    
    # Standalone $$ blocks with \label inside
    text = re.sub(
        r'\$\$(.*?)\\label\{([^}]+)\}(.*?)\$\$',
        lambda m: f'$$\n{(m.group(1) + m.group(3)).strip()}\n$$ ({convert_label_colons(m.group(2))})',
        text,
        flags=re.DOTALL
    )
    
    # Ensure $$ (label) is on its own line — pandoc's --wrap=none can leave
    # trailing text on the same line, preventing MyST from recognizing labels.
    # Only match horizontal whitespace after the label (not newlines).
    text = re.sub(
        r'(\$\$ \([^)]+\))[ \t]+(\S)',
        r'\1\n\2',
        text
    )
    
    # Ensure bare closing $$ (no label) is separated from trailing text.
    # Match $$ at start of line, followed by space then text, but NOT a label.
    # Labels look like (identifier) — skip those with negative lookahead.
    text = re.sub(
        r'^(\$\$)[ \t]+(?!\([a-zA-Z0-9_-]+\))(\S)',
        r'\1\n\2',
        text,
        flags=re.MULTILINE
    )
    
    # Ensure opening $$ of equation blocks is separated from preceding text.
    # Match: any non-newline char, horizontal whitespace, then $$ followed by
    # newline. Allows the preceding char to be ``$`` — pandoc routinely emits
    # ``$\Xsf$ $$`` when an inline-math closer abuts a display-math opener;
    # without this, the opener sticks to the prose line and MyST treats the
    # whole thing as inline math, throwing the block state-machine downstream
    # into the wrong mode and stripping blank lines for the rest of the file.
    text = re.sub(
        r'([^\n])[ \t]+\$\$\n',
        r'\1\n\n$$\n',
        text
    )
    
    # Remove blank lines inside $$ blocks.
    # MyST treats blank lines as ending a math block, so:
    #   $$
    #   content
    #                  ← this blank line breaks the math
    #   $$
    # Fix by removing blank lines while inside a $$ block.
    lines = text.split('\n')
    result = []
    in_math = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('$$') and not in_math:
            in_math = True
            result.append(line)
        elif in_math:
            if stripped.startswith('$$'):
                # Closing $$ (possibly with label like "$$ (eq-foo)")
                in_math = False
                result.append(line)
            elif stripped == '':
                # Skip blank lines inside math blocks
                continue
            else:
                result.append(line)
        else:
            result.append(line)
    text = '\n'.join(result)
    
    return text


def convert_cross_references(text: str) -> str:
    """Convert pandoc cross-reference syntax to MyST.
    
    Patterns:
    - [display](#target){reference-type="eqref" reference="target"} → {eq}`target`
    - [display](#target){reference-type="ref+label" reference="target"} → {ref/numref/prf:ref}`target`
    - [display](#target){reference-type="ref" reference="target"} → {ref}`target`
    """
    def make_ref(target):
        """Generate the appropriate MyST ref role for a single target."""
        target_converted = convert_label_colons(target)
        if target.startswith(('eq:', 'eq-')):
            return '{eq}`' + target_converted + '`'
        elif target.startswith(('f:', 'fig:')):
            return '{numref}`' + target_converted + '`'
        elif target.startswith(('tab:', 'tbl:')):
            return '{numref}`' + target_converted + '`'
        elif target.startswith(('t:', 'thm:', 'l:', 'lem:', 'p:', 'pr:', 'prop:',
                                 'd:', 'def:', 'c:', 'cor:', 'ex:', 'r:', 'rem:',
                                 'a:', 'as:', 'alg:')):
            return '{prf:ref}`' + target_converted + '`'
        elif target.startswith(('s:', 'ss:', 'sss:', 'sec:', 'ch:', 'c-', 'c:')):
            return '{ref}`' + target_converted + '`'
        else:
            return '{ref}`' + target_converted + '`'
    
    def replace_ref(m):
        display = m.group(1)  # not used — MyST generates its own display
        target = m.group(2)
        ref_type = m.group(3)
        
        if ref_type == 'eqref':
            target_converted = convert_label_colons(target)
            return '{eq}`' + target_converted + '`'
        
        # Handle comma-separated targets: \cref{a,b} → {role}`a` and {role}`b`
        if ',' in target:
            parts = [t.strip() for t in target.split(',')]
            return ' and '.join(make_ref(p) for p in parts)
        
        return make_ref(target)
    
    # Match [display](#target){reference-type="type" reference="ref"}
    # Pandoc escapes brackets in display text: [\[eq:firec\]] 
    # Also handle ref+Label (capital L variant)
    # IMPORTANT: Use [^\]\n$] (not [^\]]) to prevent matching across lines
    # or through math boundaries — otherwise [0,1) in math could pair with
    # a cross-ref many characters later on the same line.
    text = re.sub(
        r'\[([^\]\n$]*(?:\\\][^\]\n$]*)*)\]\(#([^)\n]+)\)\{reference-type="([^"]+)"(?:\s+reference="[^"]*")?\}',
        replace_ref,
        text
    )
    
    return text


def convert_citations(text: str) -> str:
    """Convert pandoc citation syntax to MyST.
    
    - [@key] → {cite}`key`
    - [@key1; @key2] → {cite}`key1,key2`
    - @key (inline/textual) → {cite:t}`key`
    """
    # Multi-citation: [@key1; @key2; ...]
    def replace_multi_cite(m):
        keys = re.findall(r'@(\S+?)(?:;|\])', m.group(0))
        return '{cite}`' + ','.join(keys) + '`'
    
    text = re.sub(r'\[@[^\]]+\]', replace_multi_cite, text)
    
    # Inline/textual citation: @key (not preceded by [ and not inside backticks)
    # Be careful not to match email addresses or already-converted citations
    text = re.sub(
        r'(?<![`\[@])@([a-zA-Z][a-zA-Z0-9_]+(?:\d{4}[a-zA-Z]?)?)(?=[^a-zA-Z0-9_]|$)',
        r'{cite:t}`\1`',
        text
    )
    
    return text


def convert_figures(text: str) -> str:
    """Convert pandoc image syntax to MyST figure directives.
    
    ![caption []{#label}](path){#id width="X%"} →
    ```{figure} figures/path
    :name: label
    :width: X%
    caption
    ```
    """
    def replace_figure(m):
        full_match = m.group(0)
        caption = m.group(1)
        path = m.group(2)
        attrs = m.group(3) if m.group(3) else ''
        
        # Extract label from caption: []{#label label="label"}
        label = None
        label_match = re.search(r'\[\]\{#([^\s}]+)(?:\s+label="[^"]*")?\}', caption)
        if label_match:
            label = convert_label_colons(label_match.group(1))
            caption = re.sub(r'\[\]\{#[^}]+\}\s*', '', caption).strip()
        
        # Extract label from attrs: {#id ...}
        if not label:
            id_match = re.search(r'#([^\s}]+)', attrs)
            if id_match:
                label = convert_label_colons(id_match.group(1))
        
        # Extract width from attrs
        width = None
        width_match = re.search(r'width="?([^"\s}]+)"?', attrs)
        if width_match:
            width = width_match.group(1)
        
        # Ensure path starts with figures/
        if not path.startswith('figures/'):
            path = 'figures/' + path
        
        lines = [f'```{{figure}} {path}']
        if label:
            lines.append(f':name: {label}')
        if width:
            lines.append(f':width: {width}')
        lines.append('')
        if caption:
            lines.append(caption)
        lines.append('```')
        
        return '\n'.join(lines)
    
    # Match ![caption](path){attrs} or ![caption](path)
    # Caption may contain nested brackets like []{#label label="label"}
    text = re.sub(
        r'!\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)]+)\)(?:\{([^}]*)\})?',
        replace_figure,
        text
    )
    
    return text


def convert_section_labels(text: str) -> str:
    """Convert pandoc section header IDs to MyST label syntax.
    
    # Title {#sec:label} → (sec-label)=\\n# Title
    """
    def replace_header(m):
        hashes = m.group(1)
        title = m.group(2).strip()
        label = convert_label_colons(m.group(3))
        return f'({label})=\n{hashes} {title}'
    
    text = re.sub(
        r'^(#{1,6})\s+(.+?)\s+\{#([^}]+)\}\s*$',
        replace_header,
        text,
        flags=re.MULTILINE
    )
    
    return text


def convert_standalone_labels(text: str) -> str:
    """Convert standalone []{#label ...} to MyST target syntax.
    
    []{#label label="label"} → (label)=
    But only when on its own line (not inside a directive body — those are
    handled by convert_environment_divs).
    """
    text = re.sub(
        r'^\[\]\{#([^\s}]+)(?:\s+label="[^"]*")?\}\s*$',
        lambda m: f'({convert_label_colons(m.group(1))})=',
        text,
        flags=re.MULTILINE
    )
    return text


def convert_epigraphs(text: str) -> str:
    """Convert ::: epigraph blocks to blockquotes."""
    text = re.sub(
        r'^::: epigraph\n(.*?)\n^:::',
        lambda m: '\n'.join('> ' + line if line.strip() else '>' for line in m.group(1).split('\n')),
        text,
        flags=re.MULTILINE | re.DOTALL
    )
    return text


def convert_html_figures(text: str) -> str:
    """Convert HTML figure blocks (from TikZ placeholders) to MyST admonitions.

    <figure id="..."> ... <figcaption>...</figcaption> </figure>
    → ```{figure} #placeholder
      :name: ...
      Caption text (TikZ diagram — needs manual conversion)
      ```

    Also handles the nested subfigure pattern that pandoc emits for
    ``\\begin{subfigure}`` environments:

        <figure id="parent">
          <figure id="child_a"> ... <figcaption>cap_a</figcaption> </figure>
          <figure id="child_b"> ... <figcaption>cap_b</figcaption> </figure>
          <figcaption>parent_caption</figcaption>
        </figure>

    For nested patterns the parent label becomes a section anchor and each
    labelled subfigure becomes its own admonition placeholder.
    """
    def make_admonition(label, caption):
        lines = ['```{admonition} Figure (TikZ — needs manual conversion)']
        if label:
            lines.append(f':name: {label}')
        lines.append('')
        lines.append(caption or '*(TikZ diagram — needs manual conversion)*')
        lines.append('```')
        return '\n'.join(lines)

    def extract_caption(block):
        cap_match = re.search(
            r'<figcaption>(?:<[^>]*>)*\s*(.*?)\s*</figcaption>',
            block,
            re.DOTALL,
        )
        if not cap_match:
            return ''
        return re.sub(r'<[^>]+>', '', cap_match.group(1)).strip()

    # Determine which labels are actually referenced by {numref} elsewhere in
    # the chapter so that nested-subfigure handling can choose the right
    # :name: for each emitted figure. MyST collapses adjacent
    # ``(parent)=`` anchors into the following figure's name, so we cannot
    # emit both a parent anchor *and* a child :name: — we must pick one per
    # figure based on actual cross-references.
    referenced_labels = set(re.findall(r'\{numref\}`([^`]+)`', text))

    # Pass 1: nested subfigure pattern (parent with one or more labelled inner figures).
    # Each inner figure carries its own id; the outer figure has its own id and trailing caption.
    nested_pattern = re.compile(
        r'<figure[^>]*id="(?P<outer_id>[^"]+)"[^>]*>\s*'
        r'(?P<inner>(?:<figure[^>]*>.*?</figure>\s*)+)'
        r'<figcaption>(?P<outer_cap>.*?)</figcaption>\s*'
        r'</figure>',
        re.DOTALL,
    )

    def replace_nested(m):
        outer_label = convert_label_colons(m.group('outer_id'))
        inner_blob = m.group('inner')
        inner_matches = list(
            re.finditer(r'<figure[^>]*>.*?</figure>', inner_blob, re.DOTALL)
        )
        parts = []
        outer_assigned = False
        for idx, inner_match in enumerate(inner_matches):
            inner_block = inner_match.group(0)
            id_match = re.search(r'<figure[^>]*id="([^"]+)"', inner_block)
            child_label = (
                convert_label_colons(id_match.group(1)) if id_match else None
            )
            # Pick the :name: per figure: prefer a label that is actually
            # referenced. The parent label can only attach to one figure, so
            # we give it to the first child that is itself unreferenced.
            chosen = child_label
            if (
                not outer_assigned
                and outer_label
                and outer_label in referenced_labels
                and (child_label is None or child_label not in referenced_labels)
            ):
                chosen = outer_label
                outer_assigned = True
            parts.append(make_admonition(chosen, extract_caption(inner_block)))
        return '\n'.join(parts)

    text = nested_pattern.sub(replace_nested, text)

    # Pass 2: any remaining (non-nested) figure blocks.
    def replace_html_figure(m):
        block = m.group(0)
        id_match = re.search(r'<figure[^>]*id="([^"]+)"', block)
        label = convert_label_colons(id_match.group(1)) if id_match else None
        return make_admonition(label, extract_caption(block))

    text = re.sub(
        r'<figure[^>]*>.*?</figure>',
        replace_html_figure,
        text,
        flags=re.DOTALL,
    )
    return text


# ── TikZ figure resolution ───────────────────────────────────────────────────

# Map TikZ admonition placeholder labels to actual figure paths.
#
# Populated from the project's tikz_overrides.py file at load time (see
# config.yaml: `tikz_overrides`). Keys are the `:name:` labels emitted by the
# preprocessor for `\input{tikz/...}` references; values are
# `(image_path, optional_caption_override)` tuples.
#
# Empty by default; projects without TikZ leave it empty.
TIKZ_FIGURE_MAP: dict = {}

# Inline tikzcd math blocks to replace with image directives.
# Keyed by chapter stem; each entry matches a $$ tikzcd $$ block.
# Populated from tikz_overrides.py.
TIKZCD_INLINE_MAP: dict = {}


def resolve_tikz_figures(text: str, stem: str) -> str:
    """Replace TikZ admonition placeholders with actual figure directives.

    Also handles:
    - Stray HTML remnants from subfigure environments
    - Unlabeled TikZ admonition blocks (orphaned sub-panels)
    - Inline tikzcd math blocks → {image} directives
    """
    lines = text.split('\n')
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Match TikZ admonition placeholder
        if line.strip() == '```{admonition} Figure (TikZ — needs manual conversion)':
            i += 1
            label = None
            caption_lines = []
            while i < len(lines) and lines[i].strip() != '```':
                if lines[i].startswith(':name:'):
                    label = lines[i].split(':name:')[1].strip()
                elif lines[i].strip():
                    caption_lines.append(lines[i].strip())
                i += 1
            if i < len(lines):
                i += 1  # skip closing ```

            if label and label in TIKZ_FIGURE_MAP:
                path, caption_override = TIKZ_FIGURE_MAP[label]
                caption = caption_override or ' '.join(caption_lines)
                result.append(f'```{{figure}} {path}')
                result.append(f':name: {label}')
                result.append('')
                if caption:
                    result.append(caption)
                result.append('```')
            elif label:
                # Unknown label — keep as placeholder
                result.append('```{admonition} Figure (TikZ — needs manual conversion)')
                result.append(f':name: {label}')
                result.append('')
                for cl in caption_lines:
                    result.append(cl)
                result.append('```')
            else:
                # Unlabeled — orphaned sub-panel from subfigure, skip
                pass
            continue

        # Remove stray HTML figcaption remnants from subfigure environments
        if '<figcaption>' in line:
            # Consume until closing tag (may span multiple lines)
            while i < len(lines) and '</figcaption>' not in lines[i]:
                i += 1
            i += 1
            continue
        if line.strip() == '</figure>':
            i += 1
            continue

        result.append(line)
        i += 1

    text = '\n'.join(result)

    # Handle inline tikzcd math blocks
    if stem in TIKZCD_INLINE_MAP:
        for entry in TIKZCD_INLINE_MAP[stem]:
            text = re.sub(entry['pattern'], entry['replacement'],
                          text, flags=re.DOTALL)

    return text


def join_split_inline_math(text: str) -> str:
    """Join inline math expressions split across lines where the next line
    begins with `>`.

    Pandoc preserves LaTeX source line wraps, so a snippet like

        ... we require that $r
        > 0$ and ...

    becomes two lines in markdown. MyST then parses the leading `>` as a
    blockquote marker, breaking both the math and the surrounding paragraph.
    Detect odd-parity unescaped `$` on a line followed by a line starting
    with `>` and merge them with a single space.

    Skips fenced code blocks (```) and display math blocks ($$) so genuine
    blockquotes are left alone.
    """
    lines = text.split('\n')
    out: list[str] = []
    in_fence = False
    in_math_block = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith('```'):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if in_fence:
            out.append(line)
            i += 1
            continue
        if stripped.startswith('$$'):
            in_math_block = not in_math_block
            out.append(line)
            i += 1
            continue
        if in_math_block:
            out.append(line)
            i += 1
            continue

        clean = line.replace('\\$', '').replace('$$', '')
        if clean.count('$') % 2 == 1 and i + 1 < len(lines):
            next_stripped = lines[i + 1].lstrip()
            if next_stripped.startswith('>'):
                # The leading `>` is the math operator, not a blockquote.
                out.append(line.rstrip() + ' ' + next_stripped)
                i += 2
                continue
        out.append(line)
        i += 1
    return '\n'.join(out)


def strip_doubled_noun_refs(text: str) -> str:
    """Drop the prose noun before a {prf:ref} that auto-expands to that noun.

    Sphinx-proof renders ``{prf:ref}`t-foo``` as "Theorem 1.2", so prose like
    "Theorem {prf:ref}`t-foo`" renders as "Theorem Theorem 1.2". LaTeX writers
    ubiquitously prefix the noun before ``\\cref{...}`` because LaTeX's cref
    doesn't always auto-name; in MyST it always does, so the noun must go.

    Matches either a regular space or a non-breaking space (U+00A0) between
    the noun and the ref, since pandoc emits NBSP for LaTeX ``~`` ties.
    Uses the prefix in ``_DOUBLED_NOUN_REFS`` to guard against stripping
    "Theorem ..." before a ref to a non-theorem object.
    """
    for noun, prefix in _DOUBLED_NOUN_REFS:
        # Negative lookbehind on a word char so we don't strip inside a longer
        # word (e.g. avoid touching a hypothetical "Subtheorem").
        text = re.sub(
            rf'(?<!\w){re.escape(noun)}[ \xa0]+(\{{prf:ref\}}`{re.escape(prefix)}[^`]+`)',
            r'\1',
            text,
        )
    return text


def strip_footnote_refs(text: str) -> str:
    """Remove ``{ref}`fn-...``` cross-references that MyST cannot resolve.

    MyST footnote anchors (``[^1]: ...``) live in a separate identifier
    namespace from the cross-reference system, so ``{ref}`fn-NAME``` always
    fails to resolve. Drop the unresolvable role and replace the phrase with
    "the previous footnote", preserving the original LaTeX target in an HTML
    comment for round-trip inspection.
    """
    pattern = re.compile(r'\bfootnote\s+\{ref\}`fn-([A-Za-z0-9_-]+)`')

    def repl(m: re.Match) -> str:
        name = m.group(1)
        original = name.replace('-', ':')
        return f'the previous footnote <!-- LaTeX-source: \\ref{{fn:{original}}} -->'

    return pattern.sub(repl, text)


def ensure_blank_after_display_math(text: str) -> str:
    """Ensure a blank line follows the closing ``$$`` of every display-math block.

    Pandoc emits display math followed immediately by the next prose paragraph.
    MyST renders this fine but the source is harder to read, and some renderers
    attach the next paragraph too tightly. Inserting a blank line keeps output
    identical while improving source readability.

    Skips fenced code blocks. Tracks display-math state so the rule fires only
    on the closing delimiter, not the opening one.
    """
    lines = text.split('\n')
    out: list[str] = []
    in_fence = False
    in_math_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('```'):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        # Display-math delimiter: first non-whitespace token is `$$`, optionally
        # followed by ` (label)` on the closing line.
        is_dm_delim = (
            stripped == '$$'
            or stripped.startswith('$$ ')
            or stripped.startswith('$$(')
        )
        if is_dm_delim:
            was_open = in_math_block
            in_math_block = not in_math_block
            out.append(line)
            # If this was the closing delimiter, ensure next line is blank.
            if was_open and i + 1 < len(lines) and lines[i + 1].strip() != '':
                out.append('')
            continue
        out.append(line)
    return '\n'.join(out)


def cleanup_typography(text: str) -> str:
    """Clean up remaining TeX artifacts."""
    # Remove standalone % comment lines (LaTeX comments that KaTeX can't handle)
    text = re.sub(r'^\s*%\s*$\n?', '', text, flags=re.MULTILINE)
    
    # Remove leftover \textbf from \navy conversion — keep bold
    # (pandoc should have converted these, but verify)

    # Remove TIKZ placeholder comments (leave a note)
    text = re.sub(
        r'^% TIKZ: (.+?) \(needs manual conversion\)$',
        r'% TODO: TikZ diagram "\1" needs manual conversion',
        text,
        flags=re.MULTILINE
    )
    
    # Remove \qedhere (LaTeX proof ending marker; sphinx-proof adds its own)
    text = text.replace('\\qedhere', '')
    
    # Fix pandoc-escaped brackets \[ and \] outside math blocks.
    # MyST interprets \[...\] as display math, so unescape to plain [ and ].
    # Only unescape when \[ is followed by text (not a math expression).
    text = re.sub(r'\\(\[)(?=[A-Z])', r'\1', text)
    text = re.sub(r'(?<=[.!?])\\(\])', r'\1', text)
    
    # Fix \l| → \lvert and \r| → \rvert (garbled LaTeX delimiters)
    text = re.sub(r'\\l\|', r'\\lvert ', text)
    text = re.sub(r'\\r\|', r'\\rvert ', text)
    
    # Clean up multiple blank lines (max 2)
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    
    return text


# ── minted listings → {code-block} ───────────────────────────────────────────
#
# Listing bodies are intercepted before pandoc by
# scripts/_apply_listing_markers.py, which emits an HTML-comment marker
# carrying the language, source path, line range, label, and caption.
# Here we decode the marker, read the referenced source file, slice the
# requested line range, and emit a MyST ``code-block`` directive whose
# ``:name:`` enables ``{numref}`list-foo``` cross-references.
#
# Reference: book-dp1/mystmd/scripts/postprocess.py::resolve_listings.

# Base directory for resolving ``\inputminted`` paths. Populated by
# apply_config() from config.yaml's ``source_code_base`` (default: source_dir).
_LISTING_SOURCE_BASE: Path | None = None


def resolve_listings(text: str) -> str:
    """Replace LISTING-START..LISTING-END markers with ``{code-block}`` directives.

    Marker format (emitted by _apply_listing_markers.py):

        <!--LISTING-START name=NAME lang=LANG path=PATH first=N last=M-->
        Caption text (possibly multi-line)
        <!--LISTING-END-->

    Pandoc may escape ``<`` to ``\\<`` and ``>`` to ``\\>``; the regex
    tolerates both forms. When the referenced source file is missing the
    directive is still emitted with a TODO comment in the body so the
    build does not fail.
    """
    pattern = re.compile(
        r'\\?<!--LISTING-START\s+'
        r'name=(?P<name>\S+)\s+'
        r'lang=(?P<lang>\S+)\s+'
        r'path=(?P<path>\S+)\s+'
        r'first=(?P<first>\d*)\s+'
        r'last=(?P<last>\d*)--\\?>'
        r'\s*(?P<caption>.*?)\s*'
        r'\\?<!--LISTING-END--\\?>',
        re.DOTALL,
    )

    base = _LISTING_SOURCE_BASE

    def repl(m: re.Match) -> str:
        name = m.group('name')
        lang = m.group('lang') or 'text'
        path_raw = m.group('path')
        first = m.group('first')
        last = m.group('last')
        caption = re.sub(r'\s+', ' ', (m.group('caption') or '').strip())

        header = [f'```{{code-block}} {lang}']
        if name:
            header.append(f':name: {name}')
        if caption:
            header.append(f':caption: {caption}')
        header.append(':linenos:')
        header.append('')

        if base is None:
            # No source_code_base configured: emit the directive but mark the
            # body as needing manual insertion. Better than swallowing the
            # listing — users see the placeholder and can wire up the path.
            header.append(f'# TODO: source_code_base not configured; inline {path_raw}')
            header.append('```')
            return '\n'.join(header)

        src_path = (base / path_raw).resolve()
        if not src_path.is_file():
            header.append(f'# TODO: source not found: {path_raw}')
            header.append('```')
            return '\n'.join(header)

        try:
            lines = src_path.read_text(encoding='utf-8').splitlines()
        except UnicodeDecodeError:
            lines = src_path.read_text(encoding='latin-1').splitlines()

        f = int(first) if first else 1
        l = int(last) if last else len(lines)
        f = max(1, f)
        l = min(len(lines), l)
        snippet = '\n'.join(lines[f - 1 : l])

        header.append(snippet)
        header.append('```')
        return '\n'.join(header)

    return pattern.sub(repl, text)


# ── algorithm2e → {prf:algorithm} ────────────────────────────────────────────
#
# Algorithm bodies are intercepted before pandoc by
# scripts/_apply_algorithm_markers.py, which base64-encodes them inside an
# HTML comment marker. Here we decode the markers, parse the algorithm2e
# control commands (``\While``, ``\For``, ``\KwIn`` etc.) into nested bullet
# lists, and emit a {prf:algorithm} directive.
#
# Reference: book-dp1/mystmd/scripts/postprocess.py.

def _algo_find_balanced(s: str, start: int) -> int:
    """Given ``s[start] == '{'``, return the index of the matching ``}``
    (inclusive). Returns -1 if unbalanced.
    """
    if start >= len(s) or s[start] != '{':
        return -1
    depth = 0
    i = start
    while i < len(s):
        c = s[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _algo_convert_body(body: str) -> str:
    """Convert an algorithm2e body to a Markdown bullet list.

    Recognises:
      - ``\\DontPrintSemicolon``, ``\\SetAlgoLined``, ``\\vspace{..}``,
        ``\\index{..}`` : dropped
      - ``\\;`` : statement terminator (bullet boundary)
      - ``\\While{C}{B}``, ``\\For{C}{B}``, ``\\ForEach{C}{B}`` : control block
      - ``\\If{C}{B}``, ``\\uIf{C}{B}``, ``\\ElseIf{C}{B}`` : conditional block
      - ``\\lIf{C}{B}`` : single-line conditional (no nested bullets)
      - ``\\Repeat{B}`` : one-arg control block (header "repeat:")
      - ``\\Return{X}``, ``\\KwResult{X}``, ``\\KwIn{X}``, ``\\KwOut{X}`` :
        one-arg statement
      - ``\\navy{x}``, ``\\textbf{x}`` : bold

    Statements are emitted as bullet items; nested blocks are indented under
    their header. The parser is recursive so deeply-nested ``\\While``/``\\If``
    structures expand correctly.
    """
    s = body

    # Source-LaTeX indentation is incidental; only the structural indentation
    # produced by recursive expansion below should survive into the output.
    s = '\n'.join(line.lstrip(' \t') for line in s.split('\n'))

    # Drop noise commands.
    s = re.sub(r'\\DontPrintSemicolon', '', s)
    s = re.sub(r'\\SetAlgoLined', '', s)
    s = re.sub(r'\\vspace\{[^}]*\}', '', s)
    s = re.sub(r'\\index\{[^}]*\}', '', s)
    s = re.sub(r'\\navy\{([^}]*)\}', r'**\1**', s)
    s = re.sub(r'\\textbf\{([^}]*)\}', r'**\1**', s)

    # Repeatedly expand control blocks (innermost first via simple loop).
    def expand_one(text: str) -> tuple[str, bool]:
        # Two-arg control blocks.
        for cmd, header_fmt in (
            ('While',   'while {}:'),
            ('For',     'for {}:'),
            ('ForEach', 'for each {}:'),
            ('If',      'if {}:'),
            ('uIf',     'if {}:'),
            ('ElseIf',  'else if {}:'),
            ('lIf',     'if {}: {}'),
        ):
            pat = re.compile(r'\\' + cmd + r'\s*\{')
            m = pat.search(text)
            if not m:
                continue
            i = m.end() - 1  # position of '{'
            j = _algo_find_balanced(text, i)
            if j < 0:
                continue
            cond = text[i + 1 : j]
            # Find next '{' for body.
            k = j + 1
            while k < len(text) and text[k] in ' \t\n':
                k += 1
            if k >= len(text) or text[k] != '{':
                continue
            l = _algo_find_balanced(text, k)
            if l < 0:
                continue
            body_inner = text[k + 1 : l]
            cond = cond.strip()
            body_inner = _algo_convert_body(body_inner).strip()
            if cmd == 'lIf':
                # Single-line if: "if cond: body" (no nested bullets).
                inner_flat = re.sub(r'\s+', ' ', body_inner.lstrip('-').strip())
                replacement = f'\\NEWLINE\\if {cond}: {inner_flat}\\NEWLINE\\'
            else:
                indented = '\n'.join('  ' + ln for ln in body_inner.split('\n'))
                replacement = (
                    f'\\NEWLINE\\{header_fmt.format(cond)}\\NEWLINE\\'
                    f'{indented}\\NEWLINE\\'
                )
            return text[: m.start()] + replacement + text[l + 1 :], True

        # \Repeat{body}: one-arg control block.
        m = re.search(r'\\Repeat\s*\{', text)
        if m:
            i = m.end() - 1
            j = _algo_find_balanced(text, i)
            if j > 0:
                body_inner = text[i + 1 : j]
                body_inner = _algo_convert_body(body_inner).strip()
                indented = '\n'.join('  ' + ln for ln in body_inner.split('\n'))
                replacement = (
                    f'\\NEWLINE\\repeat:\\NEWLINE\\{indented}\\NEWLINE\\'
                )
                return text[: m.start()] + replacement + text[j + 1 :], True

        # One-arg statement commands.
        for cmd, fmt in (
            ('Return',   'return {}'),
            ('KwResult', 'result: {}'),
            ('KwIn',     'input: {}'),
            ('KwOut',    'output: {}'),
        ):
            pat = re.compile(r'\\' + cmd + r'\s*\{')
            m = pat.search(text)
            if not m:
                continue
            i = m.end() - 1
            j = _algo_find_balanced(text, i)
            if j < 0:
                continue
            arg = text[i + 1 : j].strip()
            replacement = fmt.format(arg)
            return text[: m.start()] + replacement + text[j + 1 :], True

        return text, False

    changed = True
    while changed:
        s, changed = expand_one(s)

    # Split on statement terminators (``\;``) and ``\NEWLINE\`` placeholders
    # to produce bullet items. Indent from recursive expansion is preserved.
    s = s.replace('\\;', '\\NEWLINE\\')
    parts = re.split(r'\\NEWLINE\\', s)
    out_lines: list[str] = []
    for p in parts:
        for line in p.split('\n'):
            stripped = line.lstrip(' ')
            indent = len(line) - len(stripped)
            content = re.sub(r'\s+', ' ', stripped).strip()
            if not content:
                continue
            pad = ' ' * indent
            if content.startswith('- '):
                out_lines.append(f'{pad}{content}')
            else:
                out_lines.append(f'{pad}- {content}')

    return '\n'.join(out_lines).strip()


def resolve_algorithms(text: str) -> str:
    """Replace ALGORITHM markers with ``{prf:algorithm}`` directives.

    Marker format (emitted by _apply_algorithm_markers.py):
        <!--ALGORITHM name=NAME title=TITLE TEXT body=BASE64-->

    The body is base64-encoded so pandoc passes it through verbatim
    (otherwise pandoc would strip ``\\;`` and reformat ``\\While`` etc.).
    Pandoc may escape ``<`` to ``\\<``; the regex tolerates both forms.
    """
    pattern = re.compile(
        r'\\?<!--ALGORITHM\s+'
        r'name=(?P<name>\S+)\s+'
        r'title=(?P<title>.*?)\s+'
        r'body=(?P<body>[A-Za-z0-9+/=]+)--\\?>',
        re.DOTALL,
    )

    def repl(m: re.Match) -> str:
        name = m.group('name').strip()
        title = (m.group('title') or '').strip()
        body_b64 = m.group('body').strip()
        try:
            body = base64.b64decode(body_b64).decode('utf-8')
        except Exception:
            body = ''
        converted = _algo_convert_body(body)
        out = []
        if title:
            out.append(f'```{{prf:algorithm}} {title}')
        else:
            out.append('```{prf:algorithm}')
        out.append(f':label: {name}')
        out.append('')
        out.append(converted)
        out.append('```')
        return '\n'.join(out)

    return pattern.sub(repl, text)


def add_frontmatter(text: str, title: str) -> str:
    """Add YAML frontmatter to the file, removing any existing frontmatter
    and absorbing the (label)= / # Title heading into the frontmatter.

    Idempotent: when a previously-processed file is re-processed, the
    ``label:`` from the existing frontmatter is preserved so chapter
    cross-references like ``{prf:ref}`c-egs``` keep resolving.
    """
    # Strip any existing YAML frontmatter blocks, capturing label: if present
    existing_label = None
    while text.startswith('---\n'):
        end = text.find('\n---\n', 4)
        if end == -1:
            break
        block = text[4:end]
        if existing_label is None:
            lm = re.search(r'^label:\s*(\S+)\s*$', block, re.MULTILINE)
            if lm:
                existing_label = lm.group(1)
        text = text[end + 5:].lstrip('\n')
    # Extract (label)= target and remove the # Title heading if it matches
    label = existing_label
    m = re.match(r'\(([^)]+)\)=\s*\n# .+\n', text)
    if m:
        label = m.group(1)
        text = text[m.end():]
    frontmatter = f'---\ntitle: "{title}"\n'
    if label:
        frontmatter += f'label: {label}\n'
    frontmatter += '---\n\n'
    return frontmatter + text


# Chapter titles mapping — populated from config.yaml at runtime.
CHAPTER_TITLES: dict = {}


# ── Config loading ───────────────────────────────────────────────────────────

def load_config(config_path: Path) -> dict:
    """Load YAML config. Uses PyYAML if available, else a minimal fallback."""
    text = config_path.read_text(encoding='utf-8')
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        # Minimal YAML fallback for the subset we use (no anchors, no flow style).
        # Recommend installing PyYAML for production use.
        raise SystemExit(
            "PyYAML is required to load config. Install with: pip install pyyaml"
        )


def load_overrides(overrides_path: Path) -> None:
    """Load TIKZ_FIGURE_MAP and TIKZCD_INLINE_MAP from a project .py file."""
    global TIKZ_FIGURE_MAP, TIKZCD_INLINE_MAP
    spec = importlib.util.spec_from_file_location("project_overrides", overrides_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot load overrides file: {overrides_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    TIKZ_FIGURE_MAP = getattr(mod, 'TIKZ_FIGURE_MAP', {})
    TIKZCD_INLINE_MAP = getattr(mod, 'TIKZCD_INLINE_MAP', {})


def apply_config(config: dict, base_dir: Path | None = None) -> None:
    """Populate module-level state from a loaded config dict.

    ``base_dir`` is the directory containing config.yaml; relative paths in
    config (``source_dir``, ``source_code_base``) are resolved against it.
    Tests that call ``apply_config`` without a base_dir won't get listing
    resolution, which is fine — listings are an opt-in feature.
    """
    global CHAPTER_TITLES, _LISTING_SOURCE_BASE
    CHAPTER_TITLES = {
        entry['stem']: entry.get('title', entry['stem'])
        for entry in (config.get('chapters') or []) + (config.get('extra_files') or [])
    }

    if base_dir is not None:
        # source_code_base anchors paths inside \inputminted{lang}{path}.
        # Defaults to source_dir so dp1-style layouts (``\inputminted{julia}
        # {../source_code_jl/foo.jl}`` from a tex file in ``book/``) work
        # without extra config.
        src_base = config.get('source_code_base') or config.get('source_dir', '.')
        _LISTING_SOURCE_BASE = (base_dir / src_base).resolve()


def process_file(input_path: Path, output_path: Path = None):
    """Process a single pandoc markdown file into MyST."""
    global _last_exercise_label, _exercise_counter, _chapter_prefix
    _last_exercise_label = None
    _exercise_counter = 0
    # Chapter prefix for auto-generated labels: strip leading 'ch_' if present.
    stem = input_path.stem
    _chapter_prefix = stem[3:] if stem.startswith('ch_') else stem

    text = input_path.read_text(encoding='utf-8')

    # Order matters:
    #  - fix_text_dollar first (before eq conversion changes $$ structure)
    #  - epigraphs (removes ::: blocks before env conversion)
    #  - environments before labels (directive labels handled in context)
    #  - equations before cross-refs (so labels are extracted first)
    #  - cross-refs before figures (captions may contain cross-refs)
    text = fix_text_dollar(text)
    text = convert_epigraphs(text)
    text = convert_environment_divs(text)
    text = convert_equations(text)
    text = convert_cross_references(text)
    text = strip_doubled_noun_refs(text)           # needs MyST refs in place
    text = convert_figures(text)
    text = convert_html_figures(text)
    text = resolve_tikz_figures(text, stem)
    text = convert_section_labels(text)
    text = convert_citations(text)
    text = convert_standalone_labels(text)
    # Listings and algorithms run LATE so source-code bodies don't get
    # touched by the citation / cross-ref / typography transforms above
    # (Julia ``@views`` etc. would otherwise be eaten by convert_citations).
    text = resolve_listings(text)                  # decode minted markers
    text = resolve_algorithms(text)                # decode algorithm2e markers
    text = join_split_inline_math(text)
    text = ensure_blank_after_display_math(text)   # adds blank lines
    text = cleanup_typography(text)                # caps blank-line runs
    text = strip_footnote_refs(text)               # operates on cleaned text

    title = CHAPTER_TITLES.get(stem, stem)
    text = add_frontmatter(text, title)

    out = output_path or input_path
    out.write_text(text, encoding='utf-8')
    print(f'  Processed: {input_path.name} → {out.name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--config', type=Path, required=True,
                        help='Path to config.yaml')
    parser.add_argument('inputs', nargs='*', type=Path,
                        help='Specific .md files to process (default: all chapters in config)')
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = load_config(config_path)
    base_dir = config_path.parent
    apply_config(config, base_dir)
    output_dir = (base_dir / config.get('output_dir', '.')).resolve()

    # Load TikZ overrides if configured
    tikz_overrides = config.get('tikz_overrides')
    if tikz_overrides:
        overrides_path = (base_dir / tikz_overrides).resolve()
        if overrides_path.exists():
            load_overrides(overrides_path)
        else:
            print(f'  WARN: tikz_overrides file not found: {overrides_path}', file=sys.stderr)

    if args.inputs:
        for path in args.inputs:
            process_file(path)
        return

    # Process every chapter + extra file from config
    all_files = (config.get('chapters') or []) + (config.get('extra_files') or [])
    for entry in all_files:
        md = output_dir / f"{entry['stem']}.md"
        if md.exists():
            process_file(md)
        else:
            print(f'  WARN: {md} not found, skipping', file=sys.stderr)


if __name__ == '__main__':
    main()
