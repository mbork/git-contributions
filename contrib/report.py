# * Overview
"""One report model, rendered to JSON, Markdown or LaTeX with the same information.

A report is a title, metadata fields and a tree of sections.  A section holds blocks:
paragraphs of prose, tables and listings of source excerpts.  Prose may contain `code`
spans in backticks.  Numbers are rounded once, when stored, so that every format shows the
same values.
"""

# * Imports
import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# * Model
KINDS = ('text', 'code', 'int', 'percent', 'number')
NUMERIC_KINDS = ('int', 'percent', 'number')
DECIMALS = {'percent': 1, 'number': 2}


@dataclass
class Column:
    key: str
    label: str
    kind: str = 'text'

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f'unknown column kind {self.kind!r}')


@dataclass
class Paragraph:
    text: str


@dataclass
class Table:
    key: str
    caption: str
    columns: list
    rows: list = field(default_factory=list)

    def add(self, **values):
        """Add a row; numbers are rounded as their column's kind says."""
        row = {}
        for column in self.columns:
            value = values.pop(column.key, None)
            if value is not None and column.kind in DECIMALS:
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError(f'{value} in column {column.key!r} of {self.key!r}')
                value = round(value, DECIMALS[column.kind])
            elif value is not None and column.kind == 'int':
                value = int(value)
            row[column.key] = value
        if values:
            raise ValueError(f'unknown columns {sorted(values)} in table {self.key!r}')
        self.rows.append(row)


@dataclass
class Listing:
    """Source excerpts, one per line, each with its location (file and line)."""
    key: str
    items: list = field(default_factory=list)

    def add(self, location, text):
        self.items.append({'location': location, 'text': text})


class _HasSections:
    """Something holding a list of subsections."""

    def section(self, key, title):
        child = Section(key, title)
        self.sections.append(child)
        return child


@dataclass
class Section(_HasSections):
    key: str
    title: str
    blocks: list = field(default_factory=list)
    sections: list = field(default_factory=list)

    def paragraph(self, text):
        self.blocks.append(Paragraph(text))

    def table(self, key, caption, columns):
        table = Table(key, caption, columns)
        self.blocks.append(table)
        return table

    def listing(self, key):
        listing = Listing(key)
        self.blocks.append(listing)
        return listing


@dataclass
class Report(_HasSections):
    title: str
    metadata: list = field(default_factory=list)
    sections: list = field(default_factory=list)

    def add_field(self, key, label, value):
        if any(key == existing for existing, _, _ in self.metadata):
            raise ValueError(f'duplicate metadata key {key!r}')
        self.metadata.append((key, label, value))


# * Values
def format_value(kind, value):
    """VALUE as shown in Markdown and LaTeX tables."""
    if value is None:
        return '--'
    if kind == 'percent':
        return f'{value:.{DECIMALS[kind]}f}%'
    if kind == 'number' and float(value).is_integer():
        return str(int(value))
    if kind == 'number':
        return f'{value:.{DECIMALS[kind]}f}'
    if kind in ('int', 'text', 'code'):
        return str(value)
    raise ValueError(f'unknown column kind {kind!r}')


def one_line(text):
    """TEXT with line breaks and tabs turned into spaces, for table cells and code spans."""
    return text.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')


def split_code(text):
    """TEXT split at backticks into (is_code, piece) pairs."""
    pieces = text.split('`')
    return [(index % 2 == 1, piece) for index, piece in enumerate(pieces) if piece]


# * JSON
def section_to_json(section):
    content = []
    for block in section.blocks:
        if isinstance(block, Paragraph):
            content.append({'type': 'paragraph', 'text': block.text})
        elif isinstance(block, Table):
            columns = [{'key': c.key, 'label': c.label, 'kind': c.kind} for c in block.columns]
            content.append({'type': 'table', 'key': block.key, 'caption': block.caption,
                            'columns': columns, 'rows': block.rows})
        elif isinstance(block, Listing):
            content.append({'type': 'listing', 'key': block.key, 'items': block.items})
        else:
            raise TypeError(f'unknown block {block!r}')
    return {'key': section.key, 'title': section.title, 'content': content,
            'sections': [section_to_json(child) for child in section.sections]}


def render_json(report):
    tree = {'title': report.title,
            'metadata': {key: value for key, _, value in report.metadata},
            'metadata_labels': {key: label for key, label, _ in report.metadata},
            'sections': [section_to_json(section) for section in report.sections]}
    return json.dumps(tree, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


# * Markdown
MD_SPECIALS = set('\\`*_[]<>#|~$')


def md_escape(text):
    """Plain TEXT with Markdown punctuation backslash-escaped, on one line."""
    return ''.join('\\' + char if char in MD_SPECIALS else char for char in one_line(text))


def md_prose(text):
    """Prose with `code` spans."""
    return ''.join(md_code(piece) if is_code else md_escape(piece)
                   for is_code, piece in split_code(text))


def md_code(text):
    """TEXT as a Markdown code span, safe for any backticks inside it."""
    text = one_line(text)
    longest = 0
    run = 0
    for char in text:
        run = run + 1 if char == '`' else 0
        longest = max(longest, run)
    fence = '`' * (longest + 1)
    padding = ' ' if text.startswith('`') or text.endswith('`') else ''
    return f'{fence}{padding}{text}{padding}{fence}'


def md_cell(kind, value):
    shown = format_value(kind, value)
    if kind == 'code' and value is not None:
        return md_code(shown).replace('|', '\\|')
    return md_escape(shown)


def md_table(table):
    lines = []
    if table.caption:
        lines += [f'**{md_escape(table.caption)}**', '']
    lines.append('| ' + ' | '.join(md_escape(c.label) for c in table.columns) + ' |')
    rules = ['---:' if c.kind in NUMERIC_KINDS else '---' for c in table.columns]
    lines.append('| ' + ' | '.join(rules) + ' |')
    for row in table.rows:
        cells = [md_cell(c.kind, row[c.key]) for c in table.columns]
        lines.append('| ' + ' | '.join(cells) + ' |')
    return lines


def md_section(section, depth):
    lines = ['#' * depth + ' ' + md_escape(section.title), '']
    for block in section.blocks:
        if isinstance(block, Paragraph):
            lines += [md_prose(block.text), '']
        elif isinstance(block, Table):
            lines += md_table(block) + ['']
        elif isinstance(block, Listing):
            for item in block.items:
                lines.append(f'- {md_escape(item["location"])}: {md_code(item["text"])}')
            lines.append('')
        else:
            raise TypeError(f'unknown block {block!r}')
    for child in section.sections:
        lines += md_section(child, depth + 1)
    return lines


def render_markdown(report):
    lines = [f'# {md_escape(report.title)}', '', '| Field | Value |', '| --- | --- |']
    for _, label, value in report.metadata:
        lines.append(f'| {md_escape(label)} | {md_cell("text", value)} |')
    lines.append('')
    for section in report.sections:
        lines += md_section(section, 2)
    return '\n'.join(lines).rstrip('\n') + '\n'


# * LaTeX
LATEX_SPECIALS = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}', '$': r'\$', '&': r'\&',
                  '#': r'\#', '_': r'\_', '%': r'\%', '^': r'\textasciicircum{}',
                  '~': r'\textasciitilde{}'}
LATEX_HEADINGS = ['section', 'subsection', 'subsubsection', 'paragraph']
# \\ looks ahead for * or [, so a row whose first cell starts with one would lose it.
TEX_ROW_START = '\\relax '

LATEX_PREAMBLE = r"""\documentclass[a4paper,11pt]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage[margin=2cm]{geometry}
\usepackage{array,booktabs,longtable}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.5\baselineskip}
"""


# Characters that typewriter fonts would turn into ligatures or curly quotes.
LATEX_CODE_SPECIALS = {'-': '-{}', '`': r'\textasciigrave{}', "'": r'\textquotesingle{}',
                       '<': r'\textless{}', '>': r'\textgreater{}'}


# Beyond these, pdfLaTeX with T1 and utf8 may fail on a character, so it gets a placeholder.
LATEX_SAFE_CHARACTERS = set('\u2013\u2014\u2018\u2019\u201a\u201c\u201d\u201e\u2026')


def tex_character(char, specials):
    if char in specials:
        return specials[char]
    code = ord(char)
    if 0x20 <= code < 0x7f or 0xa0 <= code < 0x180 or char in LATEX_SAFE_CHARACTERS:
        return char
    return f'[U+{code:04X}]'


def tex_escape(text, specials=None):
    """TEXT on one line, safe in LaTeX prose and table cells."""
    if specials is None:
        specials = LATEX_SPECIALS
    return ''.join(tex_character(char, specials) for char in one_line(text))


def tex_code(text):
    specials = LATEX_SPECIALS | LATEX_CODE_SPECIALS
    return r'\texttt{' + tex_escape(text, specials) + '}'


def tex_quotes(text):
    """Straight double quotes in escaped prose as opening and closing TeX quotes."""
    pieces = text.split('"')
    out = [pieces[0]]
    for index, piece in enumerate(pieces[1:]):
        out.append('``' if index % 2 == 0 else "''")
        out.append(piece)
    return ''.join(out)


def tex_prose(text):
    """Prose with `code` spans."""
    parts = [tex_code(piece) if is_code else tex_quotes(tex_escape(piece))
             for is_code, piece in split_code(text)]
    return ''.join(parts)


def tex_cell(kind, value):
    shown = format_value(kind, value)
    if kind == 'code' and value is not None:
        return tex_code(shown)
    return tex_escape(shown)


def tex_table(table):
    specs = []
    for column in table.columns:
        if column.kind == 'code':
            specs.append(r'>{\raggedright\arraybackslash}p{0.4\linewidth}')
        elif column.kind == 'text':
            specs.append('l')
        else:
            specs.append('r')
    lines = []
    if table.caption:
        lines.append(r'\textbf{' + tex_escape(table.caption) + r'}\par\nopagebreak')
    header = ' & '.join(tex_escape(c.label) for c in table.columns) + r' \\'
    lines += [r'\begin{longtable}{' + ''.join(specs) + '}', r'\toprule', header, r'\midrule',
              r'\endhead']
    for row in table.rows:
        cells = [tex_cell(c.kind, row[c.key]) for c in table.columns]
        lines.append(TEX_ROW_START + ' & '.join(cells) + r' \\')
    lines += [r'\bottomrule', r'\end{longtable}']
    return lines


def tex_listing(listing):
    spec = (r'>{\raggedright\arraybackslash}p{0.22\linewidth}'
            r'>{\raggedright\arraybackslash}p{0.72\linewidth}')
    lines = [r'\begin{longtable}{' + spec + '}']
    for item in listing.items:
        cells = [tex_escape(item['location']), tex_code(item['text'])]
        lines.append(TEX_ROW_START + ' & '.join(cells) + r' \\')
    lines.append(r'\end{longtable}')
    return lines


def tex_section(section, depth):
    heading = LATEX_HEADINGS[min(depth, len(LATEX_HEADINGS) - 1)]
    lines = ['\\' + heading + '*{' + tex_escape(section.title) + '}', '']
    for block in section.blocks:
        if isinstance(block, Paragraph):
            lines += [tex_prose(block.text), '']
        elif isinstance(block, Table):
            lines += tex_table(block) + ['']
        elif isinstance(block, Listing):
            lines += tex_listing(block) + ['']
        else:
            raise TypeError(f'unknown block {block!r}')
    for child in section.sections:
        lines += tex_section(child, depth + 1)
    return lines


def render_latex(report):
    lines = [LATEX_PREAMBLE, r'\begin{document}', '',
             r'{\LARGE\bfseries ' + tex_escape(report.title) + r'\par}', '',
             r'\begin{longtable}{l>{\raggedright\arraybackslash}p{0.7\linewidth}}']
    for _, label, value in report.metadata:
        cells = [tex_escape(label), tex_cell('text', value)]
        lines.append(TEX_ROW_START + ' & '.join(cells) + r' \\')
    lines += [r'\end{longtable}', '']
    for section in report.sections:
        lines += tex_section(section, 0)
    lines.append(r'\end{document}')
    return '\n'.join(lines) + '\n'


# * Writing
RENDERERS = {'json': render_json, 'markdown': render_markdown, 'latex': render_latex}


def write(report, fmt, path):
    """Render REPORT as FMT and write it to PATH, replacing it only when complete."""
    text = RENDERERS[fmt](report)
    write_text(text, path)


def write_text(text, path, errors='strict'):
    """Write TEXT to PATH (UTF-8, encoding errors handled as ERRORS), replacing the file
    only when the text is complete."""
    path = Path(path)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8', errors=errors) as stream:
            stream.write(text)
        # mkstemp creates the file private; give it the usual permissions.
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(temporary, 0o666 & ~umask)
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise
