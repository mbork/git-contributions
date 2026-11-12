# SPDX-License-Identifier: GPL-3.0-or-later
# * Overview
"""LaTeX source analysis: words with their source offsets, the include graph, the preamble,
and the units the reports count (sentences, formulas, paragraphs, sections, chapters).

A *word* (token) is a maximal run of non-whitespace characters outside comments.  The same
tokenizer rewrites the history (one word per line, see `rewrite_blob`), so word number i of a
rewritten file is word number i of the original file, which maps every word the history
replay tracks back to its place in the source.
"""

# * Imports
import bisect
import functools
import posixpath
import re
from dataclasses import dataclass, field

# * Scanning
VERBATIM_ENVS = ('verbatim', 'Verbatim', 'lstlisting', 'minted')
MATH_ENVS = ('equation', 'align', 'gather', 'multline', 'eqnarray', 'flalign', 'alignat',
             'displaymath', 'math')
BEGIN_ENV = re.compile(r'\\begin\s*\{([A-Za-z]+\*?)\}')
VERB = re.compile(r'\\verb\*?([^A-Za-z\s*])')


@functools.cache
def end_env(name):
    return re.compile(r'\\end\s*\{' + re.escape(name) + r'\}')


def verbatim_end(text, index):
    """End offset of the verbatim text (\\verb or a verbatim environment) at INDEX, or None.

    An unclosed verbatim environment runs to the end of TEXT; a \\verb not closed on its
    line is ordinary text, as LaTeX would reject it anyway."""
    verb = VERB.match(text, index)
    if verb:
        close = text.find(verb.group(1), verb.end())
        newline = text.find('\n', verb.end())
        if close < 0 or 0 <= newline < close:
            return None
        return close + 1
    begin = BEGIN_ENV.match(text, index)
    if begin and begin.group(1).rstrip('*') in VERBATIM_ENVS:
        close = end_env(begin.group(1)).search(text, begin.end())
        return close.end() if close else len(text)
    return None


def find_unescaped(text, needle, start):
    """Offset of the next NEEDLE at or after START that is not escaped by a backslash.

    Scans forward, skipping every backslash together with the character after it, as the
    other scanners here do."""
    index = start
    while index < len(text):
        if text.startswith(needle, index):
            return index
        index += 2 if text[index] == '\\' else 1
    return -1


# * Tokens
WORD = re.compile(r'\S+')


def blank_comments(text):
    """TEXT with every comment (an unescaped % to the end of the line) replaced by spaces.

    Offsets stay the same, so positions in the result are positions in TEXT.  A % inside
    \\verb or a verbatim environment is not a comment."""
    out = list(text)
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == '\\':
            skip = verbatim_end(text, index)
            index = skip if skip is not None else index + 2
            continue
        if char == '%':
            end = text.find('\n', index)
            if end < 0:
                end = length
            out[index:end] = ' ' * (end - index)
            index = end
            continue
        index += 1
    return ''.join(out)


def tokenize(text):
    """(clean text, word spans) of TEXT: comments blanked, (start, end) of every word."""
    clean = blank_comments(text)
    return clean, [match.span() for match in WORD.finditer(clean)]


def decode(data):
    """Bytes of a file as text; undecodable bytes survive a round trip through `encode`."""
    return data.decode('utf-8', errors='surrogateescape')


def encode(text):
    """Text from `decode` back to the original bytes."""
    return text.encode('utf-8', errors='surrogateescape')


def rewrite_blob(data):
    """The rewritten form of a .tex blob: comments dropped, one word per line."""
    text = decode(data)
    clean, spans = tokenize(text)
    if not spans:
        return b''
    return encode('\n'.join(clean[start:end] for start, end in spans) + '\n')


# * Source files
@dataclass
class SourceFile:
    path: str
    text: str
    clean: str
    spans: list
    newlines: list
    ends: list          # end offset of every word, for bisecting

    @classmethod
    def from_text(cls, path, text):
        clean, spans = tokenize(text)
        newlines = [match.start() for match in re.finditer('\n', text)]
        return cls(path, text, clean, spans, newlines, [end for _, end in spans])

    def words(self):
        return [self.text[start:end] for start, end in self.spans]

    def line_of(self, offset):
        """1-based line number of the character at OFFSET."""
        return bisect.bisect_right(self.newlines, offset - 1) + 1

    def first_word_at(self, offset):
        """Index of the first word ending after OFFSET."""
        return bisect.bisect_right(self.ends, offset)

    def word_range(self, start, end):
        """(first, stop): the words overlapping the characters START..END."""
        return self.first_word_at(start), self.first_word_at(end - 1) + 1

    @functools.cached_property
    def regions(self):
        return math_regions(self.clean)

    @functools.cached_property
    def verbatim(self):
        return [(start, end) for kind, start, end in self.regions if kind == 'verbatim']

    def is_verbatim(self, offset):
        return any(start <= offset < end for start, end in self.verbatim)


# * Regions: verbatim and math
def environment_region(clean, index, begin):
    """(kind, end) of the environment opened by BEGIN at INDEX, or None if not math or
    verbatim."""
    name = begin.group(1)
    base = name.rstrip('*')
    if base in VERBATIM_ENVS:
        return 'verbatim', verbatim_end(clean, index) or len(clean)
    if base not in MATH_ENVS:
        return None
    close = end_env(name).search(clean, begin.end())
    stop = close.end() if close else len(clean)
    return ('inline' if base == 'math' else 'display'), stop


def delimited_region(clean, index, opener, closer, kind):
    close = find_unescaped(clean, closer, index + len(opener))
    stop = close + len(closer) if close >= 0 else len(clean)
    return kind, stop


def math_regions(clean):
    """Math and verbatim regions of CLEAN, as (kind, start, end).

    Kind is 'inline', 'display' or 'verbatim'; verbatim is reported so that callers can
    leave it alone."""
    regions = []
    index = 0
    end = len(clean)
    while index < end:
        char = clean[index]
        found = None
        if char == '\\':
            begin = BEGIN_ENV.match(clean, index)
            skip = verbatim_end(clean, index)
            if begin:
                found = environment_region(clean, index, begin)
                if found is None:
                    index = begin.end()
                    continue
            elif skip is not None and VERB.match(clean, index):
                found = ('verbatim', skip)
            elif clean.startswith('\\[', index):
                found = delimited_region(clean, index, '\\[', '\\]', 'display')
            elif clean.startswith('\\(', index):
                found = delimited_region(clean, index, '\\(', '\\)', 'inline')
            else:
                index += 2
                continue
        elif clean.startswith('$$', index):
            found = delimited_region(clean, index, '$$', '$$', 'display')
        elif char == '$':
            found = delimited_region(clean, index, '$', '$', 'inline')
        else:
            index += 1
            continue
        kind, stop = found
        regions.append((kind, index, stop))
        index = max(stop, index + 1)
    return regions


# * Structure: includes, preamble, sections
INCLUDE = re.compile(r'\\(input|include)(?![A-Za-z])\s*(?:\{([^{}]*)\}|([^\s{}\\]+))')
BEGIN_DOCUMENT = re.compile(r'\\begin\s*\{document\}')
END_DOCUMENT = re.compile(r'\\end\s*\{document\}')
SECTIONING = re.compile(r'\\(part|chapter|section|subsection|subsubsection|paragraph)'
                        r'(?![A-Za-z])\s*\*?')
# Levels of the section tree; deeper headings are headings but open no section.
SECTION_LEVELS = {'part': 0, 'chapter': 1, 'section': 2, 'subsection': 3,
                  'subsubsection': 4, 'paragraph': 5}
DEEPEST_SECTION = SECTION_LEVELS['subsection']
BEFORE_FIRST_CHAPTER = '(before the first chapter)'


def balanced_group(clean, index, opener='{', closer='}'):
    """End offset (exclusive) of the group opening at INDEX, or -1 if there is none."""
    if index >= len(clean) or clean[index] != opener:
        return -1
    depth = 0
    position = index
    while position < len(clean):
        char = clean[position]
        if char == '\\':
            position += 2
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return position + 1
        position += 1
    return -1


def is_balanced(text):
    """Whether the unescaped braces of TEXT balance, never closing more than were opened."""
    depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == '\\':
            index += 2
            continue
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth < 0:
                return False
        index += 1
    return depth == 0


def skip_spaces(clean, index):
    while index < len(clean) and clean[index].isspace():
        index += 1
    return index


def heading_at(clean, match):
    """(end offset, title) of the sectioning command MATCH, or None if it has no title."""
    index = skip_spaces(clean, match.end())
    if index < len(clean) and clean[index] == '[':
        optional_end = balanced_group(clean, index, '[', ']')
        if optional_end < 0:
            return None
        index = skip_spaces(clean, optional_end)
    title_end = balanced_group(clean, index)
    if title_end < 0:
        return None
    title = ' '.join(clean[index + 1:title_end - 1].split())
    return title_end, title


def resolve_include(base_dir, name, command, exists):
    """Repository path of the file \\input{NAME} or \\include{NAME} reads, or None."""
    name = name.strip()
    if not name:
        return None
    path = posixpath.normpath(posixpath.join(base_dir, name))
    candidates = [path + '.tex'] if command == 'include' else [path + '.tex', path]
    for candidate in candidates:
        if exists(candidate):
            return candidate
    return None


# * Book model
@dataclass
class Token:
    path: str
    index: int          # word number within its file
    start: int          # offsets in the original file text
    end: int
    text: str
    is_preamble: bool
    chapter: int = -1   # index into Book.chapters
    section: int = -1   # index into Book.sections
    block: int = -1     # index into Book.blocks
    sentence: int = -1  # index into Book.sentences, -1 outside sentences
    formulas: tuple = ()


@dataclass
class Unit:
    kind: str           # blocks: text, heading, display, markup; formulas: inline, display
    tokens: list = field(default_factory=list)


@dataclass
class Heading:
    level: int
    command: str
    title: str
    path: str
    line: int
    parent: int = -1


@dataclass
class Include:
    start: int          # offsets of the command in the including file
    end: int
    target: str


@dataclass
class Book:
    main: str
    files: dict = field(default_factory=dict)       # path -> SourceFile
    tokens: list = field(default_factory=list)      # counted words, in reading order
    counted: dict = field(default_factory=dict)     # path -> set of counted word numbers
    preamble_files: set = field(default_factory=set)
    includes: dict = field(default_factory=dict)    # path -> [Include]
    begin_document: int = -1                        # word number in the main file
    sections: list = field(default_factory=list)    # [Heading] in reading order
    chapters: list = field(default_factory=list)    # [(title, section index or -1)]
    blocks: list = field(default_factory=list)      # [Unit]: paragraphs, headings, displays
    sentences: list = field(default_factory=list)   # [Unit]
    formulas: list = field(default_factory=list)    # [Unit]
    missing: list = field(default_factory=list)     # includes whose file was not found


# * Reading order
class _Walker:
    """Walks the include graph from the main file, collecting words in reading order."""

    def __init__(self, book, read, include_preamble):
        self.book = book
        self.read = read
        self.include_preamble = include_preamble
        self.visiting = set()
        self.walked = {}    # path -> whether it was walked only as part of the preamble
        self.pieces = []    # (path, first word, stop word, is_preamble), in reading order

    def load(self, path):
        if path not in self.book.files:
            text = self.read(path)
            if text is None:
                return None
            self.book.files[path] = SourceFile.from_text(path, text)
        return self.book.files[path]

    def exists(self, path):
        return self.load(path) is not None

    def walk(self, path, first, stop, is_preamble):
        """Words FIRST..STOP of PATH, with its includes expanded in place."""
        source = self.book.files[path]
        includes = self.book.includes.setdefault(path, [])
        base_dir = posixpath.dirname(self.book.main)
        position = first
        start_offset = source.spans[first][0] if first < len(source.spans) else len(source.text)
        stop_offset = source.spans[stop - 1][1] if stop > first else start_offset
        for match in INCLUDE.finditer(source.clean, start_offset, stop_offset):
            if source.is_verbatim(match.start()):
                continue
            name = match.group(2) if match.group(2) is not None else match.group(3)
            target = resolve_include(base_dir, name, match.group(1), self.exists)
            command_first, command_stop = source.word_range(match.start(), match.end())
            self.add_piece(path, position, command_first, is_preamble)
            position = max(position, command_stop)
            if target is None:
                self.book.missing.append(f'{path}:{source.line_of(match.start())}: {name}')
                continue
            include = Include(match.start(), match.end(), target)
            if include not in includes:     # a file walked twice records each include once
                includes.append(include)
            if target in self.visiting:
                continue
            was_preamble_only = self.walked.get(target)
            if was_preamble_only is False or (was_preamble_only and is_preamble):
                continue
            self.visit(target, is_preamble)
        self.add_piece(path, position, stop, is_preamble)

    def visit(self, path, is_preamble):
        source = self.book.files[path]
        self.visiting.add(path)
        self.walked[path] = is_preamble
        if is_preamble:
            self.book.preamble_files.add(path)
        else:
            self.book.preamble_files.discard(path)
        self.book.counted.setdefault(path, set())
        self.walk(path, 0, len(source.spans), is_preamble)
        self.visiting.discard(path)

    def add_piece(self, path, first, stop, is_preamble):
        if stop <= first:
            return
        self.pieces.append((path, first, stop, is_preamble))
        if is_preamble and not self.include_preamble:
            return
        self.book.counted[path].update(range(first, stop))

    def walk_main(self):
        main = self.load(self.book.main)
        if main is None:
            return False
        self.visiting.add(self.book.main)
        self.walked[self.book.main] = False
        self.book.counted[self.book.main] = set()
        begin = BEGIN_DOCUMENT.search(main.clean)
        end = END_DOCUMENT.search(main.clean)
        stop = main.first_word_at(end.start()) if end else len(main.spans)
        if begin is None:
            self.walk(self.book.main, 0, stop, False)
            return True
        body_first = main.first_word_at(begin.end() - 1) + 1
        self.book.begin_document = body_first - 1
        self.walk(self.book.main, 0, body_first, True)
        self.walk(self.book.main, body_first, stop, False)
        return True


# * Units
BLOCK_START = re.compile(r'\\(?:begin|end)\s*\{|\\(?:item|par)(?![A-Za-z])|\\\[|\\\]|\$\$')
BLOCK_END = re.compile(r'\\end\s*\{|\\par(?![A-Za-z])')
# Macros whose arguments are not text: a block made only of them is markup.
STRUCTURAL = {'label', 'begin', 'end', 'item', 'maketitle', 'tableofcontents', 'appendix',
              'par', 'newpage', 'clearpage', 'cleardoublepage', 'noindent', 'centering',
              'frontmatter', 'mainmatter', 'backmatter', 'vspace', 'hspace', 'bigskip',
              'medskip', 'smallskip', 'index', 'nocite', 'bibliography',
              'bibliographystyle', 'printbibliography', 'includegraphics', 'listoffigures',
              'listoftables', 'printindex', 'qed', 'qedhere'}
MACRO_WORD = re.compile(r'(?:\\([A-Za-z@]+)\*?(?:\[[^\]]*\]|\{[^{}]*\})*)+')
MACRO_NAME = re.compile(r'\\([A-Za-z@]+)')
ABBREVIATIONS = {'e.g.', 'i.e.', 'cf.', 'etc.', 'fig.', 'figs.', 'eq.', 'eqs.', 'thm.',
                 'lem.', 'prop.', 'cor.', 'def.', 'sec.', 'ch.', 'chap.', 'resp.', 'vs.',
                 'viz.', 'al.', 'no.', 'nos.', 'p.', 'pp.', 'vol.', 'ed.', 'eds.', 'dr.',
                 'prof.', 'mr.', 'mrs.', 'ms.', 'st.', 'approx.', 'ca.', 'ref.', 'refs.',
                 'w.r.t.'}
CLOSERS = ')]}\'"$`'
OPENERS = '([{\'"`'


def sentence_end(text):
    """Offset within TEXT of the punctuation ending a sentence, or -1 if it ends none."""
    core = text.rstrip(CLOSERS)
    if not core or core[-1] not in '.!?':
        return -1
    word = core.lstrip(OPENERS).lower()
    if word in ABBREVIATIONS or re.fullmatch(r'[a-z]\.', word):
        return -1
    return len(core) - 1


def is_blank_gap(text, start, end):
    """Whether TEXT[START:END] (the gap between two words) holds an empty line.

    A line holding only a comment is not empty, as in LaTeX."""
    lines = text[start:end].split('\n')
    return any(not line.strip() for line in lines[1:-1])


def is_markup_word(text):
    """Whether TEXT is only structural macros (\\label{...}, \\end{proof}, \\maketitle)."""
    if not MACRO_WORD.fullmatch(text):
        return False
    return all(name in STRUCTURAL for name in MACRO_NAME.findall(text))


class _Units:
    """Splits the words of a project, in reading order, into blocks, sentences and formulas."""

    def __init__(self, book):
        self.book = book
        self.formula_of = {}    # (path, word number) -> formula indices
        self.math_spans = {}    # path -> sorted (start, end) of formulas
        self.heading_of = {}    # (path, word number) -> (path, offset) of its command
        self.headings = {}      # (path, offset) -> Heading not yet numbered
        self.numbers = {}       # (path, offset) -> index into book.sections
        self.display_words = set()

    def find_formulas(self):
        for path in self.book.counted:
            source = self.book.files[path]
            spans = []
            for kind, start, end in source.regions:
                if kind == 'verbatim':
                    continue
                spans.append((start, end))
                first, stop = source.word_range(start, end)
                words = [index for index in range(first, stop)
                         if index in self.book.counted[path]]
                if not words:
                    continue
                formula = len(self.book.formulas)
                self.book.formulas.append(Unit(kind, []))
                for index in words:
                    self.formula_of.setdefault((path, index), []).append(formula)
                    if kind == 'display':
                        self.display_words.add((path, index))
            self.math_spans[path] = spans

    def find_headings(self):
        """Candidate headings: counted words only, nothing inside verbatim."""
        for path in self.book.counted:
            source = self.book.files[path]
            for match in SECTIONING.finditer(source.clean):
                if source.is_verbatim(match.start()):
                    continue
                found = heading_at(source.clean, match)
                if found is None:
                    continue
                title_end, title = found
                first, stop = source.word_range(match.start(), title_end)
                if first not in self.book.counted[path]:
                    continue
                key = (path, match.start())
                command = match.group(1)
                self.headings[key] = Heading(SECTION_LEVELS[command], command, title, path,
                                             source.line_of(match.start()))
                for index in range(first, stop):
                    self.heading_of[(path, index)] = key

    def is_in_formula(self, path, offset):
        spans = self.math_spans.get(path, [])
        position = bisect.bisect_right(spans, (offset, float('inf'))) - 1
        return position >= 0 and spans[position][0] <= offset < spans[position][1]

    def ends_sentence(self, token):
        end = sentence_end(token.text)
        return end >= 0 and not self.is_in_formula(token.path, token.start + end)

    def kind_of(self, token):
        key = (token.path, token.index)
        if key in self.heading_of:
            return 'heading'
        if key in self.display_words:
            return 'display'
        return 'text'

    def starts_block(self, previous, token, kind, previous_kind):
        """Whether TOKEN (of KIND) starts a new block after PREVIOUS."""
        if previous is None or kind != previous_kind:
            return True
        if previous.path != token.path or previous.index + 1 != token.index:
            return True
        if is_blank_gap(self.book.files[token.path].text, previous.end, token.start):
            return True
        if kind == 'heading':
            previous_heading = self.heading_of[(previous.path, previous.index)]
            return previous_heading != self.heading_of[(token.path, token.index)]
        if kind == 'text':
            return bool(BLOCK_START.match(token.text) or BLOCK_END.match(previous.text))
        return False

    def open_heading(self, key, open_sections, chapter_command):
        """Number the heading KEY and update OPEN_SECTIONS (level -> section index).

        Returns the index of the chapter the heading starts, or None."""
        book = self.book
        heading = self.headings[key]
        number = len(book.sections)
        book.sections.append(heading)
        self.numbers[key] = number
        if heading.level <= DEEPEST_SECTION:
            outer_levels = [level for level in open_sections if level < heading.level]
            heading.parent = open_sections[max(outer_levels)] if outer_levels else -1
            for level in [level for level in open_sections if level >= heading.level]:
                del open_sections[level]
            open_sections[heading.level] = number
        if heading.command != chapter_command:
            return None
        book.chapters.append((heading.title, number))
        return len(book.chapters) - 1

    def split(self):
        book = self.book
        self.find_formulas()
        self.find_headings()
        uses_chapters = any(h.command == 'chapter' for h in self.headings.values())
        chapter_command = 'chapter' if uses_chapters else 'section'
        open_sections = {}
        chapter = -1
        block = Unit('text')
        sentence = None
        previous = None
        previous_kind = None
        for number, token in enumerate(book.tokens):
            kind = self.kind_of(token)
            is_new_block = self.starts_block(previous, token, kind, previous_kind)
            heading = self.heading_of.get((token.path, token.index))
            if heading is not None and is_new_block:
                opened = self.open_heading(heading, open_sections, chapter_command)
                if opened is not None:
                    chapter = opened
            if chapter < 0:
                book.chapters.append((BEFORE_FIRST_CHAPTER, -1))
                chapter = 0
            if is_new_block:
                block = Unit(kind, [])
                book.blocks.append(block)
                sentence = None
            block.tokens.append(number)
            token.block = len(book.blocks) - 1
            token.chapter = chapter
            token.section = open_sections[max(open_sections)] if open_sections else -1
            token.formulas = tuple(self.formula_of.get((token.path, token.index), ()))
            for formula in token.formulas:
                book.formulas[formula].tokens.append(number)
            if kind in ('text', 'heading'):
                if sentence is None:
                    sentence = Unit(kind, [])
                    book.sentences.append(sentence)
                sentence.tokens.append(number)
                token.sentence = len(book.sentences) - 1
                if kind == 'text' and self.ends_sentence(token):
                    sentence = None
            previous = token
            previous_kind = kind
        self.mark_markup()

    def mark_markup(self):
        """Blocks and sentences made of structural macros only are markup."""
        book = self.book
        for unit in book.blocks + book.sentences:
            texts = [book.tokens[i].text for i in unit.tokens]
            if unit.kind == 'text' and all(is_markup_word(text) for text in texts):
                unit.kind = 'markup'


# * Entry point
def analyze(read, main, include_preamble=False):
    """The Book whose main file is MAIN; READ(path) returns a file's text or None.

    Paths are relative to the repository root, with forward slashes."""
    book = Book(main=posixpath.normpath(main))
    walker = _Walker(book, read, include_preamble)
    if not walker.walk_main():
        return None
    seen = set()    # a file input in the preamble and again in the body is read twice
    for path, first, stop, is_preamble in walker.pieces:
        if is_preamble and not include_preamble:
            continue
        source = book.files[path]
        for index in range(first, stop):
            if index not in book.counted[path] or (path, index) in seen:
                continue
            seen.add((path, index))
            start, end = source.spans[index]
            book.tokens.append(Token(path, index, start, end, source.text[start:end],
                                     is_preamble))
    _Units(book).split()
    return book
