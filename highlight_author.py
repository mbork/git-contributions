#!/usr/bin/env python3
# * Overview
"""The whole LaTeX project in one file, with one author's surviving words highlighted.
See docs/highlight_author.md."""

# * Imports
import re
import shlex

from contrib import cli, latex, report, session
from contrib.cli import ContribError
from contrib.session import THE_AUTHOR

# * Constants
SCRIPT = 'highlight_author.py'

DESCRIPTION = """\
Write the whole LaTeX project kept in Git, at the given revision, as one flattened .tex file
in which every surviving word written by one author is highlighted: common words (like
"the", "let", "assume") lightly, other words strongly.  Moving text is not a contribution:
text keeps its writer wherever it is moved.  Compile the file with LuaLaTeX and the lua-ul
package for the best result; elsewhere (pdfLaTeX, or without lua-ul) every word gets a
plain colored box.  The command to compile it is printed when it is written.  See
docs/highlight_author.md."""

COLOR_SPEC = re.compile(r'[A-Za-z0-9!.,:\- ]+')

# ** What may be highlighted
# Macros a highlighted word may contain: they only format text.  A word with any other
# macro is left alone (definitions, spacing, references, user macros of unknown meaning).
TEXT_MACROS = {'emph', 'textbf', 'textit', 'textsl', 'textsc', 'texttt', 'textrm', 'textsf',
               'textup', 'textmd', 'underline', 'ldots', 'dots', 'TeX', 'LaTeX', 'ae', 'AE',
               'oe', 'OE', 'aa', 'AA', 'ss', 'o', 'O', 'l', 'L', 'i', 'j', 'textendash',
               'textemdash', 'textquoteleft', 'textquoteright', 'S', 'P', 'dag', 'ddag'}
# Escapes (backslash and a non-letter) that print text or adjust it in place.
SAFE_ESCAPES = set(',;!-\'"`.&%$#_{}@/')
UNSAFE_CHARACTERS = set('$&#^_[]%')     # outside escapes
# Groups whose contents must not be highlighted: moving arguments, references, code,
# definitions, boxes.
FRAGILE_COMMANDS = set(latex.SECTION_LEVELS) | {
    'subparagraph', 'caption', 'footnote', 'footnotetext', 'thanks', 'title', 'author',
    'date', 'index', 'label', 'ref', 'eqref', 'pageref', 'autoref', 'cref', 'Cref', 'cite',
    'citep', 'citet', 'nocite', 'url', 'href', 'hyperref', 'marginpar', 'begin', 'end',
    'includegraphics', 'input', 'include', 'bibliography', 'newcommand', 'renewcommand',
    'providecommand', 'def', 'newenvironment', 'renewenvironment', 'setlength', 'hspace',
    'vspace', 'tag', 'text', 'mbox', 'hbox', 'makebox', 'parbox', 'raisebox', 'definecolor',
    'colorlet', 'DeclareRobustCommand', 'NewDocumentCommand', 'lstinline', 'mintinline'}
# Environments whose contents are code or alignments, not running text.
SKIP_ENVIRONMENTS = {'tikzpicture', 'pgfpicture', 'picture', 'axis', 'tikzcd', 'forest',
                     'tabular', 'tabular*', 'tabularx', 'longtable', 'array', 'tabbing'}
# Inline code with an arbitrary delimiter, like \verb.
INLINE_CODE = re.compile(r'\\(lstinline|mintinline)(?![A-Za-z])\s*(\[[^\]]*\])?\s*'
                         r'(\{[^{}]*\})?')
ENDINPUT = re.compile(r'\\endinput(?![A-Za-z])')
# A blank TeX reads as one space: spaces and tabs, with at most one line end.  Other
# Unicode spaces (no-break, thin) and form feeds mean something else and stay as they are.
PLAIN_GAP = re.compile(r'[ \t]*(?:\r?\n)?[ \t]*')


# * Command line
def parse_args():
    parser = cli.make_parser(SCRIPT, DESCRIPTION, is_one_author=True,
                             does_offer_format=False)
    group = parser.add_argument_group('colors (xcolor expressions)')
    group.add_argument('--light-color', metavar='COLOR', default='yellow!25',
                       help='background of common words (default: %(default)s)')
    group.add_argument('--strong-color', metavar='COLOR', default='orange!55',
                       help='background of other words and formulas (default: %(default)s)')
    args = cli.parse_args(parser)
    for option, value in [('--light-color', args.light_color),
                          ('--strong-color', args.strong_color)]:
        if not COLOR_SPEC.fullmatch(value):
            parser.error(f'{option} must be an xcolor expression such as yellow!25')
    return args


# * Where highlighting is safe
# ** Words
def is_safe_word(text):
    """Whether a word can be wrapped in \\contribhl{...}{...} on its own: balanced braces,
    no alignment or math characters, only text macros and safe escapes."""
    if not latex.is_balanced(text):
        return False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '\\':
            name = latex.MACRO_NAME.match(text, index)
            if name:
                if name.group(1) not in TEXT_MACROS:
                    return False
                index = name.end()
                continue
            if index + 1 >= len(text) or text[index + 1] not in SAFE_ESCAPES:
                return False        # a control space, \\, \= and the like
            index += 2
            continue
        if char in UNSAFE_CHARACTERS:
            return False
        index += 1
    return True


# ** Ranges
def matching_pairs(clean):
    """Opening offset of every closing brace and bracket of CLEAN (unescaped)."""
    opening = {}
    stacks = {'}': [], ']': []}
    pairs = {'{': '}', '[': ']'}
    index = 0
    while index < len(clean):
        char = clean[index]
        if char == '\\':
            index += 2
            continue
        if char in pairs:
            stacks[pairs[char]].append(index)
        elif char in stacks and stacks[char]:
            opening[index] = stacks[char].pop()
        index += 1
    return opening


def command_before(clean, index, opening):
    """The macro owning the group opening at INDEX: the one before it, skipping spaces, a
    star and earlier argument groups ({...} or [...]), or None."""
    position = index - 1
    while position >= 0:
        char = clean[position]
        if char.isspace() or char == '*':
            position -= 1
        elif char in '}]' and position in opening:
            position = opening[position] - 1
        else:
            break
    end = position + 1
    while position >= 0 and (clean[position].isalpha() or clean[position] == '@'):
        position -= 1
    if position >= 0 and clean[position] == '\\' and position + 1 < end:
        return clean[position + 1:end]
    return None


def unsafe_ranges(source):
    """Character ranges of SOURCE inside which nothing may be highlighted: verbatim and
    inline code, display math, fragile groups, optional arguments, code environments."""
    clean = source.clean
    ranges = [(start, end) for kind, start, end in source.regions
              if kind in ('verbatim', 'display')]
    opening = matching_pairs(clean)
    for close, start in opening.items():
        command = command_before(clean, start, opening)
        is_option = clean[start] == '['
        if command in FRAGILE_COMMANDS or (is_option and command is not None):
            ranges.append((start, close + 1))
    for match in INLINE_CODE.finditer(clean):
        delimiter = clean[match.end():match.end() + 1]
        closer = '}' if delimiter == '{' else delimiter
        close = clean.find(closer, match.end() + 1) if delimiter else -1
        ranges.append((match.start(), close + 1 if close >= 0 else match.end()))
    for begin in latex.BEGIN_ENV.finditer(clean):
        name = begin.group(1)
        if name in SKIP_ENVIRONMENTS:
            end = latex.end_env(name).search(clean, begin.end())
            ranges.append((begin.start(), end.end() if end else len(clean)))
    return ranges


def is_inside(ranges, start, end):
    """Whether START..END lies within one of RANGES."""
    return any(low <= start and end <= high for low, high in ranges)


# * Segments
class Highlighter:
    """Decides, file by file, which character ranges to highlight and in which color."""

    def __init__(self, context, result):
        self.book = context.book
        is_by_author, is_uncommon = session.author_masks(context, result)
        self.tokens_of = {}     # path -> [(Token, is by author, is uncommon)], body only
        for number, token in enumerate(self.book.tokens):
            if not token.is_preamble:
                entry = (token, is_by_author[number], is_uncommon[number])
                self.tokens_of.setdefault(token.path, []).append(entry)
        self.cache = {}
        self.author_words = sum(1 for entries in self.tokens_of.values()
                                for _, is_mine, _ in entries if is_mine)
        self.highlighted_words = 0

    @property
    def missed_words(self):
        return self.author_words - self.highlighted_words

    def segments(self, path):
        """Sorted (start, end, color) of PATH, one per word or inline formula, so that a
        line can break between any two of them.  Counted once per file."""
        if path not in self.cache:
            self.cache[path] = self.compute(path)
        return self.cache[path]

    def compute(self, path):
        entries = self.tokens_of.get(path, [])
        source = self.book.files[path]
        unsafe = unsafe_ranges(source)
        by_index = {token.index: (token, is_mine) for token, is_mine, _ in entries}
        pieces = []
        in_formula = set()
        for kind, start, end in source.regions:
            if kind != 'inline':
                continue
            first, stop = source.word_range(start, end)
            inside = [by_index[i] for i in range(first, stop) if i in by_index]
            in_formula.update(token.index for token, _ in inside)
            mine = sum(1 for _, is_mine in inside if is_mine)
            if not inside or mine * 2 <= len(inside) or is_inside(unsafe, start, end):
                continue
            pieces.append((start, end, 'contribstrong'))
            self.highlighted_words += mine
        for token, is_mine, is_uncommon in entries:
            if token.index in in_formula or not is_mine:
                continue
            if self.book.blocks[token.block].kind in ('heading', 'display', 'markup'):
                continue
            if not is_safe_word(token.text) or is_inside(unsafe, token.start, token.end):
                continue
            pieces.append((token.start, token.end,
                           'contribstrong' if is_uncommon else 'contriblight'))
            self.highlighted_words += 1
        return sorted(pieces)


# * Flattening
def setup_lines(args):
    """Preamble additions: the colors, \\contribhl{color}{text} and \\contribgap{color} (the
    space between two highlighted pieces).  Under LuaLaTeX with lua-ul and luacolor they
    use lua-ul's \\highLight, so the space is colored too; otherwise a highlighted piece is
    a colored box and the space stays plain, so that lines can still break there."""
    return ['% --- added by highlight_author.py ---',
            r'\usepackage{xcolor}',
            rf'\colorlet{{contriblight}}{{{args.light_color}}}',
            rf'\colorlet{{contribstrong}}{{{args.strong_color}}}',
            r'\makeatletter',
            r'\let\contrib@hasul\relax',
            r'\ifdefined\directlua',
            r'  \IfFileExists{lua-ul.sty}{\IfFileExists{luacolor.sty}{%',
            r'    \usepackage{luacolor}\usepackage{lua-ul}\def\contrib@hasul{yes}}{}}{}',
            r'\fi',
            r'\ifx\contrib@hasul\relax',
            r'  \newcommand\contribhl[2]{{\setlength{\fboxsep}{0.4pt}\colorbox{#1}{\strut #2}}}',
            r'  \newcommand\contribgap[1]{ }',
            r'\else',
            r'  \newcommand\contribhl[2]{\highLight[#1]{#2}}',
            r'  \newcommand\contribgap[1]{\highLight[#1]{ }}',
            r'\fi',
            r'\makeatother',
            '% --- end of additions ---', '']


class Flattener:
    """Builds the flattened text, inlining includes and inserting highlights."""

    def __init__(self, book, highlighter, setup):
        self.book = book
        self.highlighter = highlighter
        self.setup = setup

    def flatten(self, path, is_suppressed=False, visiting=()):
        """The text of PATH with its includes inlined; with IS_SUPPRESSED (PATH is
        included somewhere highlighting is unsafe), nothing in it is highlighted."""
        if path in visiting:
            raise ContribError(f'{path} includes itself')
        source = self.book.files[path]
        stop = len(source.text)
        edits = []          # (start, end, replacement)
        endinput = ENDINPUT.search(source.clean) if path != self.book.main else None
        if endinput is not None:
            # TeX reads the rest of the line after \endinput, then stops reading the file.
            line_end = source.text.find('\n', endinput.end())
            stop = len(source.text) if line_end < 0 else line_end
            edits.append((endinput.start(), endinput.end(), ''))
        if not is_suppressed:
            segments = [(start, end, color)
                        for start, end, color in self.highlighter.segments(path)
                        if end <= stop]
            for start, end, color in segments:
                edits.append((start, start, rf'\contribhl{{{color}}}{{'))
                edits.append((end, end, '}'))
            edits += gap_edits(source.text, segments)
        begin = None
        if path == self.book.main:
            begin = latex.BEGIN_DOCUMENT.search(source.clean)
            if begin is None:
                raise ContribError(f'{path} has no \\begin{{document}}')
            edits.append((begin.start(), begin.start(), '\n'.join(self.setup)))
        unsafe = None
        for include in self.book.includes.get(path, []):
            if include.end > stop:
                continue
            if unsafe is None:
                unsafe = unsafe_ranges(source) + [(start, end) for _, start, end
                                                  in source.regions]
            is_in_preamble = begin is not None and include.start < begin.start()
            is_child_suppressed = (is_suppressed or is_in_preamble
                                   or is_inside(unsafe, include.start, include.end))
            child = self.flatten(include.target, is_child_suppressed, (*visiting, path))
            edits.append((include.start, include.end,
                          self.inlined(source.text[include.start:include.end],
                                       include.target, child)))
        return apply_edits(source.text[:stop], edits)

    @staticmethod
    def inlined(command, target, child):
        """The text replacing COMMAND.  The end of an input file acts as one end of line,
        so CHILD gets exactly one final newline (two would be a paragraph break)."""
        banner = f'% --- {target} ({command}) ---\n'
        body = child if child.endswith('\n') else child + '\n'
        if command.startswith('\\include'):
            return f'\\clearpage\n{banner}{body}\\clearpage\n'
        if command.startswith('\\input'):
            return f'{banner}{body}'
        raise ContribError(f'internal error: unexpected include command {command!r}')


def gap_edits(text, segments):
    """Edits coloring the blank between two neighboring highlighted pieces: strongly
    between two strong pieces, lightly otherwise.  Only a PLAIN_GAP qualifies; a comment,
    a blank line or a special space keeps the blank as it is."""
    edits = []
    for (_, end, color), (start, _, next_color) in zip(segments, segments[1:]):
        gap = text[end:start]
        if not gap or not PLAIN_GAP.fullmatch(gap):
            continue
        is_strong = color == next_color == 'contribstrong'
        gap_color = 'contribstrong' if is_strong else 'contriblight'
        edits.append((end, start, rf'\contribgap{{{gap_color}}}'))
    return edits


def apply_edits(text, edits):
    """TEXT with every (start, end, replacement) applied; edits never overlap."""
    out = []
    position = 0
    for start, end, replacement in sorted(edits, key=lambda edit: (edit[0], edit[1])):
        out.append(text[position:start])
        out.append(replacement)
        position = max(position, end)
    out.append(text[position:])
    return ''.join(out)


# * Output
def header(context, name, highlighter, output):
    args = context.args
    work_copy = context.work_copy
    lines = [
        f'% The project at {args.commit} ({work_copy.original_hash[:12]}) of {work_copy.original},',
        f'% with the surviving words of {name} highlighted (author regex: {args.author}).',
        f'% Generated by {SCRIPT} on {session.iso_time()}.',
        f'% Words by the author in the text: {highlighter.author_words}; highlighted:'
        f' {highlighter.highlighted_words}; left unhighlighted (in headings, displayed'
        f' formulas, references, code and other places where highlighting would break the'
        f' document): {highlighter.missed_words}.',
        f'% Compile with: {compile_command(work_copy, output)}',
        '']
    # A newline in a name or regex would end the comment and leak into the document.
    return '\n'.join(line.replace('\n', ' ') for line in lines)


def compile_command(work_copy, output):
    tree = shlex.quote(f'{work_copy.tree}//:')
    return f'TEXINPUTS={tree} BIBINPUTS={tree} lualatex {shlex.quote(str(output))}'


# * Main
def main(progress):
    args = parse_args()
    context, result, _ = session.start_one_author(args, progress, SCRIPT)
    name = session.display_name(result, THE_AUTHOR)
    progress.log('highlighting the author\'s words')
    highlighter = Highlighter(context, result)
    flattener = Flattener(context.book, highlighter, setup_lines(args))
    body = flattener.flatten(context.book.main)
    output = cli.output_path(args, SCRIPT, args.commit, 'tex', name)
    text = header(context, name, highlighter, output) + body
    report.write_text(text, output, errors='surrogateescape')
    progress.log(f'{highlighter.author_words} words by {name}, {highlighter.highlighted_words}'
                 f' highlighted, {highlighter.missed_words} left unhighlighted')
    progress.log(f'compile with: {compile_command(context.work_copy, output)}')
    progress.finish(output)


if __name__ == '__main__':
    cli.run(main)
