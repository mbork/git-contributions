#!/usr/bin/env python3
# * Overview
"""One author's contribution to a LaTeX project in Git, measured in many ways, with a fair and
a maximal estimate.  See docs/author_profile.md."""

# * Imports
from dataclasses import dataclass

from contrib import cli, fair, latex, replay, session, words, workcopy
from contrib.cli import ContribError
from contrib.report import Column
from contrib.session import THE_AUTHOR

# * Texts
SCRIPT = 'author_profile.py'

DESCRIPTION = """\
Measure one author's contribution to a LaTeX project kept in Git in many ways: words (all,
and without common words), sentences, formulas and paragraphs; a fair estimate; and a
maximal estimate that no reasonable definition of the author's share can exceed.  The
report goes to a file; see docs/author_profile.md."""

INTRODUCTION = [
    'This report measures the contribution of one author, named above, to the project at the'
    ' revision given above.  It follows every word of the text (comments excluded) through'
    ' the whole history of the repository and finds out who typed it.',
    'The contribution is counted in several ways, because no single number tells the whole'
    ' story: words, words other than common ones (like "the", "let", "assume"), sentences,'
    ' formulas and paragraphs.  Then come two estimates of the author\'s share: a fair one,'
    ' which weighs writing, rewriting, moving and replaced drafts, and a maximal one, which'
    ' resolves every doubt in the author\'s favor.  The report ends with the author\'s words'
    ' per chapter and the names and e-mail addresses counted as the author\'s.',
]

GUIDE = [
    'Words: the author\'s words in the current text and their share of all words.  The same'
    ' without common words shows how much of the substance is theirs; a much lower share'
    ' there means their words are mostly small, common ones.',
    'Sentences, formulas and paragraphs are counted in four ways: written entirely by the'
    ' author; mostly (more than half of the words); with at least one word by the author;'
    ' and word-weighted, where a sentence half written by the author counts as one half.'
    ' "At least one word" is generous: one fixed typo makes a sentence count.',
    'The fair share uses the same rule as `author_shares.py`: 1 point for a word in the'
    ' text, less for a word typed in place of someone else\'s words, little for moving'
    ' someone else\'s text, half for a word someone else later removed or replaced.',
    'The maximal estimate is the largest of the candidates in its table: the shares of'
    ' words and of uncommon words, the "at least one word" shares, the fair share, the'
    ' word-based estimate and the line-based upper bound (the other shares are never'
    ' larger).  The line-based bound counts every word on every line the author ever added'
    ' or changed, in any commit, including text later removed, comments and the preamble;'
    ' in a project written one paragraph per line, a one-word fix counts the whole paragraph.'
    '  So it is at least everything the author ever typed, and their share cannot exceed it'
    ' under any reasonable definition.  The word-based estimate counts only the words the'
    ' author actually typed; it is closer to the truth, but not guaranteed on its own.',
    'The per-chapter table repeats the word counts for every chapter; the last table lists'
    ' the identities whose commits count as the author\'s.',
]

CAVEATS = [
    'Only what Git records is measured.  Text written by the author but committed by'
    ' someone else is not theirs here (except, for the maximal estimate, on branches still in'
    ' the repository with `--all-branches`); ideas, proofs worked out in discussion and'
    ' reviewing are invisible.',
    'A word is any run of non-blank characters, so `\\emph{word},` or `$x^2$` is one word.'
    ' When someone heavily rewrites a sentence, common words that stay in place keep their'
    ' original author.',
    'The maximal estimate is only as complete as the author regex: an identity it misses'
    ' is not counted.  Check the list of matched identities below.',
]

FAIR_LABELS = {'written': 'Written (in the text)',
               'rewritten': 'Rewritten (in the text, in place of others\' words)',
               'moved': 'Moved (others\' words in the text)',
               'removed': 'Removed or replaced by others'}


# * Command line
def parse_args():
    parser = cli.make_parser(SCRIPT, DESCRIPTION, is_one_author=True)
    fair.add_weight_options(parser)
    group = parser.add_argument_group('maximal estimate')
    group.add_argument('--all-branches', action='store_true',
                       help='also count the author\'s commits on every branch, not only the'
                            ' history of --commit (for work squash-merged by someone else);'
                            ' commits newer than --commit are left out')
    args = cli.parse_args(parser)
    args.weights = fair.weights_from(args, parser)
    return args


# * The line-based upper bound
def line_based_words(context, matches):
    """Words on every line the author added or changed, in all .tex files, comments and
    preamble included, in the history of the measured commit (and, with --all-branches, on
    every branch, up to the measured commit's date).  Read from the original repository."""
    work_copy = context.work_copy
    target = work_copy.original_hash
    committed = workcopy.run_git_text('log', '-1', '--format=%ct', target,
                                      cwd=work_copy.original)
    # Every option the output depends on is explicit, so that no configuration (such as
    # log.showRoot=false) can make the bound smaller.
    options = [*workcopy.mailmap_options(context.mailmap), '-c', 'log.showRoot=true',
               '-c', 'log.showSignature=false', 'log', '--root', '-p', '-M',
               '--diff-merges=remerge', '--no-ext-diff', '--no-textconv', '--text',
               '--no-color', '--format=%x00%H%x00%aN <%aE>%x00%an <%ae>']
    revisions = [[target]]
    if context.args.all_branches:
        revisions.append(['--all', f'--until=@{committed}', '--not', target])
    total = 0
    for revision in revisions:
        lines = workcopy.stream_git(*options, *revision, '--', replay.PATHSPEC,
                                    cwd=work_copy.original)
        total += count_added_words(lines, matches)
    return total


def count_added_words(lines, matches):
    """Words on the added lines of the matching commits, split as the replay splits them."""
    is_author = False
    is_header = False
    total = 0
    for line in lines:
        if line.startswith(b'\0'):
            _, _, identity, raw = line.decode('utf-8', errors='replace').split('\0')
            is_author = matches(identity, raw)
            continue
        if not is_author:
            continue
        if line.startswith(b'diff --git ') or line.startswith(b'diff --cc '):
            is_header = True
        elif line.startswith(b'@@'):
            is_header = False
        elif not is_header and line.startswith(b'+'):
            text = latex.decode(line[1:])
            total += len(latex.WORD.findall(text))
    return total


# * Figures
@dataclass
class Figures:
    name: str
    is_by_author: list      # per token of the project
    is_uncommon: list
    rows: list              # (key, label, count, total) of the measures table
    tallies: dict
    fair_share: float
    line_based: int
    typed: int


def capitalized(label):
    return label[:1].upper() + label[1:]


def capped_share(count, total):
    """A share for the maximal estimate: never above 100%."""
    return min(fair.percent(count, total), 100.0)


def unit_fractions(units, is_by_author):
    """For each unit (a list of token indices), the fraction of its words by the author."""
    fractions = []
    for unit in units:
        if not unit.tokens:
            continue
        by_author = sum(1 for index in unit.tokens if is_by_author[index])
        fractions.append(by_author / len(unit.tokens))
    return fractions


def unit_rows(name, label, fractions):
    """(key, label, count, total) rows for one kind of unit."""
    total = len(fractions)
    return [(f'{name}_entirely', f'{label} entirely by the author',
             sum(1 for f in fractions if f == 1), total),
            (f'{name}_mostly', f'{label} mostly by the author (more than half the words)',
             sum(1 for f in fractions if f > 0.5), total),
            (f'{name}_any', f'{label} with at least one word by the author',
             sum(1 for f in fractions if f > 0), total),
            (f'{name}_weighted', f'{label} word-weighted', sum(fractions), total)]


def compute(context, result, matches, weights):
    book = context.book
    is_by_author = [result.state[t.path][t.index].writer == THE_AUTHOR for t in book.tokens]
    is_uncommon = [not words.is_common(t.text, context.common) for t in book.tokens]
    uncommon_by_author = sum(1 for a, u in zip(is_by_author, is_uncommon) if a and u)
    rows = [('words', 'Words', sum(is_by_author), len(book.tokens)),
            ('uncommon_words', 'Words other than common words', uncommon_by_author,
             sum(is_uncommon))]
    units = [('sentences', 'Sentences',
              [s for s in book.sentences if s.kind in ('text', 'heading')]),
             ('formulas', 'Formulas', book.formulas),
             ('paragraphs', 'Paragraphs', [b for b in book.blocks if b.kind == 'text'])]
    for name, label, unit_list in units:
        rows += unit_rows(name, label, unit_fractions(unit_list, is_by_author))
    tallies = fair.tally(book, result)
    fair_shares = fair.shares(tallies, weights)
    context.progress.log('counting the words on every line the author touched')
    return Figures(session.display_name(result, THE_AUTHOR), is_by_author, is_uncommon, rows,
                   tallies, fair_shares.get(THE_AUTHOR, 0.0),
                   line_based_words(context, matches), result.typed.get(THE_AUTHOR, 0))


# * Report sections
def add_measures(document, figures):
    section = document.section('measures', 'Measures')
    table = section.table('measures', f'Contribution of {figures.name}', [
        Column('measure', 'Measure'), Column('count', 'By the author', 'number'),
        Column('total', 'Total', 'int'), Column('share', 'Share', 'percent')])
    for _, label, count, total in figures.rows:
        table.add(measure=label, count=count, total=total, share=fair.percent(count, total))


def add_fair(document, figures, weights):
    section = document.section('fair', 'Fair estimate')
    table = section.table('fair', 'Fair share and its parts', [
        Column('part', 'Part'), Column('words', 'Words', 'int'),
        Column('points', 'Points', 'number')])
    counts = figures.tallies.get(THE_AUTHOR, {})
    for category in fair.CATEGORIES:
        value = counts.get(category, 0)
        table.add(part=FAIR_LABELS[category], words=value,
                  points=weights.of(category) * value)
    section.paragraph(f'Fair share: {figures.fair_share:.1f}% of all points.')


def add_maximal(document, figures, total_words):
    section = document.section('maximal', 'Maximal estimate')
    candidates = [('Line-based upper bound (every word on every line the author added or'
                   ' changed)', figures.line_based, total_words,
                   capped_share(figures.line_based, total_words)),
                  ('Word-based estimate (every word the author ever typed)', figures.typed,
                   total_words, capped_share(figures.typed, total_words)),
                  ('Fair share', None, None, min(figures.fair_share, 100.0))]
    candidates += [(label, count, total, capped_share(count, total))
                   for key, label, count, total in figures.rows
                   if key.endswith('_any') or key in ('words', 'uncommon_words')]
    best = max(range(len(candidates)), key=lambda index: candidates[index][3])
    table = section.table('maximal', 'Candidates (the largest is the maximal estimate)', [
        Column('measure', 'Measure'), Column('count', 'By the author', 'number'),
        Column('total', 'Total', 'int'), Column('share', 'Share', 'percent'),
        Column('is_max', 'Maximum')])
    for index, (label, count, total, share) in enumerate(candidates):
        table.add(measure=capitalized(label), count=count, total=total, share=share,
                  is_max='yes' if index == best else '')
    section.paragraph(f'Maximal estimate: {candidates[best][3]:.1f}% (capped at 100%).')
    section.paragraph('The word-based estimate is closer to the truth than the line-based'
                      ' bound, but not guaranteed on its own; the line-based bound is.')


def add_chapters(document, book, figures):
    section = document.section('chapters', 'Per chapter')
    table = section.table('chapters', 'The author\'s words per chapter', [
        Column('chapter', 'Chapter'), Column('words', 'Words by the author', 'int'),
        Column('total', 'Words', 'int'), Column('share', 'Share', 'percent'),
        Column('uncommon', 'Uncommon words by the author', 'int'),
        Column('uncommon_total', 'Uncommon words', 'int'),
        Column('uncommon_share', 'Share of uncommon', 'percent')])
    by_chapter = session.tokens_by_chapter(book)
    for number, (title, _) in enumerate(book.chapters):
        indices = by_chapter.get(number, [])
        if not indices:
            continue
        by_author = sum(1 for i in indices if figures.is_by_author[i])
        uncommon = sum(1 for i in indices if figures.is_uncommon[i])
        uncommon_by_author = sum(1 for i in indices
                                 if figures.is_uncommon[i] and figures.is_by_author[i])
        uncommon_share = fair.percent(uncommon_by_author, uncommon)
        table.add(chapter=title, words=by_author, total=len(indices),
                  share=fair.percent(by_author, len(indices)), uncommon=uncommon_by_author,
                  uncommon_total=uncommon, uncommon_share=uncommon_share)


def add_identities(document, result):
    section = document.section('identities', 'Identities counted as the author')
    section.paragraph('Every commit whose author (as recorded, or after `.mailmap`) matches'
                      ' the regex counts as the author\'s.')
    table = section.table('identities', '', [Column('identity', 'Identity')])
    for identity in session.identities(result).get(THE_AUTHOR, []):
        table.add(identity=identity)


def build_report(context, result, matches, weights):
    book = context.book
    figures = compute(context, result, matches, weights)
    extra = [('author', 'Author', figures.name),
             ('author_regex', 'Author regex', context.args.author),
             session.common_words_field(context), *fair.weight_fields(weights),
             ('all_branches', 'All branches in the maximal estimate',
              'yes' if context.args.all_branches else 'no'),
             ('words', 'Words in the text', str(len(book.tokens)))]
    document = session.new_report(context, result, f'Contribution of {figures.name}', extra)
    intro = document.section('introduction', 'What this report measures')
    for paragraph in INTRODUCTION:
        intro.paragraph(paragraph)
    guide = document.section('guide', 'How to read it')
    for paragraph in GUIDE:
        guide.paragraph(paragraph)
    add_measures(document, figures)
    add_fair(document, figures, weights)
    add_maximal(document, figures, len(book.tokens))
    add_chapters(document, book, figures)
    add_identities(document, result)
    caveats = document.section('caveats', 'Caveats')
    for paragraph in CAVEATS:
        caveats.paragraph(paragraph)
    return document, figures.name


# * Main
def main(progress):
    args = parse_args()
    context = session.start(args, progress, SCRIPT)
    author_key, matches = session.one_author_key(args.author)
    result = session.run_replay(context, author_key)
    if not any(commit.author == THE_AUTHOR for commit in result.commits.values()):
        raise ContribError(f'no commit in the history of {args.commit} has an author matching'
                           f' {args.author!r}')
    progress.log('computing the measures')
    document, name = build_report(context, result, matches, args.weights)
    session.write_report(context, document, name)


if __name__ == '__main__':
    cli.run(main)
