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
\setlength{\emergencystretch}{2em}
\newcommand{\contribbreak}{\penalty5000\hskip0pt\relax}
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


# ** Breaking long words
LONG_WORD = 20              # words this long (as printed) get break points ...
WORD_CHUNK = 10             # ... every this many printed characters
# A break TeX takes only when nothing better is left: long words in narrow cells.
TEX_BREAK = r'\contribbreak{}'


def tex_breakable(text, specials):
    """TEXT escaped with SPECIALS, with TEX_BREAK in long words and after placeholders.

    Lengths count printed characters, so a placeholder like [U+03BB] counts as eight."""
    pieces = [tex_character(char, specials) for char in one_line(text)]
    out = []
    word = []

    def flush():
        is_long = sum(len(piece) for piece in word) >= LONG_WORD
        printed = 0
        for piece in word:
            if is_long and printed >= WORD_CHUNK:
                out.append(TEX_BREAK)
                printed = 0
            out.append(piece)
            printed += len(piece)
            if piece.startswith('[U+'):
                out.append(TEX_BREAK)
                printed = 0
        word.clear()

    for piece in pieces:
        if piece == ' ':
            flush()
            out.append(piece)
        else:
            word.append(piece)
    flush()
    return ''.join(out)


def printed_length(text):
    """Characters TEXT takes when printed (a placeholder counts as eight)."""
    return sum(len(tex_character(char, LATEX_SPECIALS)) if ord(char) > 0x7e else 1
               for char in one_line(text))


def tex_code(text):
    """TEXT in typewriter type, with break points in long words."""
    specials = LATEX_SPECIALS | LATEX_CODE_SPECIALS
    return r'\texttt{' + tex_breakable(text, specials) + '}'


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
    return tex_breakable(shown, LATEX_SPECIALS)


# ** Tables
WIDE_TABLE_COLUMNS = 6      # from this many columns on, a table gets tighter spacing
SHORT_LABEL = 10            # column labels this short stay on one line
LINE_WIDTH_PT = 483         # \linewidth of the document (A4, 2 cm margins)
CHARACTER_PT = 5.8          # a generous average width of a character, in points
MIN_COLUMN_PT = 60          # no wrapped column gets narrower than this
WIDTH_MARGIN = 0.94         # the estimates are rough: use only this part of the line


def header_lines(label):
    """LABEL as one line, or as two when it has several words and is not short."""
    words = label.split()
    if len(words) < 2 or len(label) <= SHORT_LABEL:
        return [label]
    half = (len(label) + 1) // 2
    split = 1
    while split < len(words) - 1:
        head = ' '.join(words[:split + 1])
        if len(head) > half:
            break
        split += 1
    first = ' '.join(words[:split])
    second = ' '.join(words[split:])
    return [first, second]


def tex_header(label, alignment):
    """A column label, over two lines when header_lines says so."""
    lines = [tex_escape(line) for line in header_lines(label)]
    if len(lines) == 1:
        return lines[0]
    # \\ looks ahead for * or [, which the second line could start with.
    body = (r'\\' + TEX_ROW_START).join(lines)
    return rf'\begin{{tabular}}[b]{{@{{}}{alignment}@{{}}}}{body}\end{{tabular}}'


def natural_width(table, column):
    """Estimated width of COLUMN's widest cell or header line, in points."""
    lengths = [printed_length(line) for line in header_lines(column.label)]
    lengths += [printed_length(format_value(column.kind, row[column.key]))
                for row in table.rows]
    return max(lengths) * CHARACTER_PT


def wrap_width(widths, room):
    """The cap c with sum(min(width, c)) = ROOM: columns narrower than c keep their width,
    the others wrap at c (never below MIN_COLUMN_PT)."""
    remaining = room
    ordered = sorted(widths)
    for count, width in enumerate(ordered):
        others = len(ordered) - count
        if width * others >= remaining:
            return max(remaining / others, MIN_COLUMN_PT)
        remaining -= width
    return max(ordered[-1], MIN_COLUMN_PT)


def column_specs(table, separation_pt):
    """Column types: natural widths when the row fits the line; otherwise the widest text
    and code columns wrap, at a common width chosen so that the row fits."""
    widths = [natural_width(table, column) for column in table.columns]
    available = (LINE_WIDTH_PT - 2 * separation_pt * len(table.columns)) * WIDTH_MARGIN
    is_numeric = [column.kind in NUMERIC_KINDS for column in table.columns]
    if sum(widths) <= available:
        return ['r' if numeric else 'l' for numeric in is_numeric]
    numbers = sum(width for width, numeric in zip(widths, is_numeric) if numeric)
    flexible = [width for width, numeric in zip(widths, is_numeric) if not numeric]
    if not flexible:
        return ['r'] * len(widths)
    cap = wrap_width(flexible, max(available - numbers, MIN_COLUMN_PT * len(flexible)))
    specs = []
    for width, numeric in zip(widths, is_numeric):
        if numeric:
            specs.append('r')
        elif width <= cap:
            specs.append('l')
        else:
            fraction = cap / LINE_WIDTH_PT
            specs.append(rf'>{{\raggedright\arraybackslash}}p{{{fraction:.3f}\linewidth}}')
    return specs


def tex_table(table):
    is_wide = len(table.columns) >= WIDE_TABLE_COLUMNS
    specs = column_specs(table, 4 if is_wide else 6)
    lines = []
    if table.caption:
        lines.append(r'\textbf{' + tex_escape(table.caption) + r'}\par\nopagebreak')
    alignments = ['r' if c.kind in NUMERIC_KINDS else 'l' for c in table.columns]
    header = ' & '.join(tex_header(c.label, alignment)
                        for c, alignment in zip(table.columns, alignments)) + r' \\'
    if is_wide:
        lines.append(r'{\setlength{\tabcolsep}{4pt}')
    lines += [r'\begin{longtable}{' + ''.join(specs) + '}', r'\toprule', header, r'\midrule',
              r'\endhead']
    for row in table.rows:
        cells = [tex_cell(c.kind, row[c.key]) for c in table.columns]
        lines.append(TEX_ROW_START + ' & '.join(cells) + r' \\')
    lines += [r'\bottomrule', r'\end{longtable}']
    if is_wide:
        lines.append('}')
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
             r'\begin{longtable}{>{\raggedright\arraybackslash}p{0.22\linewidth}'
             r'>{\raggedright\arraybackslash}p{0.72\linewidth}}']
    for _, label, value in report.metadata:
        cells = [tex_breakable(label, LATEX_SPECIALS), tex_cell('text', value)]
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
