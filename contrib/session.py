# * Overview
"""What every script does around its own measure: prepare the working copy, analyze the
project, replay the history, match authors, and write the report with a common header."""

# * Imports
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from contrib import cli, latex, replay, report, words, workcopy
from contrib.cli import ContribError


# * Session
@dataclass
class Session:
    args: object
    progress: object
    work_copy: object
    mailmap: object         # Path or None
    book: object            # latex.Book
    common: set             # common words
    script: str             # file name of the running script


def start(args, progress, script):
    """Prepare everything a script needs for ARGS."""
    work_copy = workcopy.prepare(args.repo, args.commit, progress)
    if args.mailmap is not None:
        mailmap = Path(args.mailmap).expanduser().resolve()
        if not mailmap.is_file():
            raise ContribError(f'mailmap file {args.mailmap} not found')
    else:
        mailmap = work_copy.mailmap
    progress.log(f'analyzing {args.main} and the files it includes')
    book = latex.analyze(work_copy.read_original, args.main, args.include_preamble)
    if book is None:
        raise ContribError(f'{args.main} does not exist at {args.commit}')
    for missing in book.missing:
        progress.log(f'warning: included file not found: {missing}')
    if not book.tokens:
        raise ContribError(f'no text found in {args.main} and the files it includes')
    common = words.load(args.common_words)
    return Session(args, progress, work_copy, mailmap, book, common, script)


def run_replay(session, author_key, watched=()):
    session.progress.log('replaying the history')
    result = replay.Replay(session.work_copy, author_key, session.mailmap, session.progress,
                           excluded_files=session.book.preamble_files,
                           include_preamble=session.args.include_preamble,
                           watched=watched).run()
    replay.check_state(session.book, result.state)
    return result


# * Authors
THE_AUTHOR = ('the author',)      # a key no name can collide with


def name_of(identity):
    """The name part of "Name <email>"."""
    return identity.rsplit(' <', 1)[0]


def by_name(identity, raw):
    """Author key: the name after .mailmap."""
    return name_of(identity)


def regex_matcher(pattern):
    """A function telling whether a commit's identity (after .mailmap, or raw) matches."""
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as error:
        raise ContribError(f'invalid --author regex {pattern!r}: {error}') from None

    def matches(identity, raw):
        return compiled.search(identity) is not None or compiled.search(raw) is not None
    return matches


def one_author_key(pattern):
    """Author key for the one-author scripts: THE_AUTHOR for every matching identity,
    the name after .mailmap for everybody else."""
    matches = regex_matcher(pattern)

    def key(identity, raw):
        return THE_AUTHOR if matches(identity, raw) else name_of(identity)
    return key, matches


def start_one_author(args, progress, script, *, does_watch=False):
    """Everything a one-author script needs: (context, result, matches).  With DOES_WATCH,
    the replay also collects the removals of the author's words."""
    context = start(args, progress, script)
    author_key, matches = one_author_key(args.author)
    watched = {THE_AUTHOR} if does_watch else ()
    result = run_replay(context, author_key, watched=watched)
    require_author(result, args)
    return context, result, matches


def require_author(result, args):
    """Fail unless some commit in the history is by THE_AUTHOR."""
    if not any(commit.author == THE_AUTHOR for commit in result.commits.values()):
        raise ContribError(f'no commit in the history of {args.commit} has an author matching'
                           f' {args.author!r}')


def add_identities_section(document, result):
    """The section listing the identities counted as THE_AUTHOR."""
    section = document.section('identities', 'Identities counted as the author')
    section.paragraph('Every commit whose author (as recorded, or after `.mailmap`) matches'
                      ' the regex counts as the author\'s.')
    table = section.table('identities', '', [report.Column('identity', 'Identity')])
    for identity in identities(result).get(THE_AUTHOR, []):
        table.add(identity=identity)


def identities(result):
    """Author key -> sorted list of identities used in its commits (after .mailmap and raw)."""
    found = {}
    for commit in result.commits.values():
        found.setdefault(commit.author, set()).update({commit.identity, commit.raw_identity})
    return {key: sorted(values) for key, values in found.items()}


def display_name(result, key):
    """The most frequent name (after .mailmap) among the commits of KEY."""
    counts = Counter(name_of(commit.identity) for commit in result.commits.values()
                     if commit.author == key)
    if not counts:
        return str(key)
    return max(sorted(counts), key=lambda name: counts[name])


# * Units
SENTENCE_KINDS = ('text', 'heading')    # sentences proper and headings


def author_masks(context, result):
    """(is_by_author, is_uncommon): one boolean per token of the project."""
    book = context.book
    is_by_author = [result.state[t.path][t.index].writer == THE_AUTHOR for t in book.tokens]
    is_uncommon = [not words.is_common(t.text, context.common) for t in book.tokens]
    return is_by_author, is_uncommon


def unit_lists(book):
    """(key, label, units) for sentences, formulas and paragraphs; a unit is a non-empty
    list of token indices."""
    sentences = [s.tokens for s in book.sentences if s.kind in SENTENCE_KINDS]
    formulas = [f.tokens for f in book.formulas]
    paragraphs = [b.tokens for b in book.blocks if b.kind == 'text']
    return [(key, label, [unit for unit in units if unit])
            for key, label, units in [('sentences', 'Sentences', sentences),
                                      ('formulas', 'Formulas', formulas),
                                      ('paragraphs', 'Paragraphs', paragraphs)]]


def unit_fractions(units, is_by_author):
    """For each unit, the fraction of its words by the author."""
    return [sum(1 for index in unit if is_by_author[index]) / len(unit) for unit in units]


# * Reports
def add_prose(document, key, title, paragraphs):
    """A section made of PARAGRAPHS."""
    section = document.section(key, title)
    for paragraph in paragraphs:
        section.paragraph(paragraph)
    return section


def iso_time(timestamp=None):
    """TIMESTAMP (default: now) as local ISO 8601 time, to the minute."""
    moment = datetime.now() if timestamp is None else datetime.fromtimestamp(timestamp)
    local = moment.astimezone()
    return local.isoformat(timespec='minutes')


def tokens_by_chapter(book):
    """Chapter number -> indices of its tokens in book.tokens."""
    chapters = {}
    for index, token in enumerate(book.tokens):
        chapters.setdefault(token.chapter, []).append(index)
    return chapters


def new_report(session, result, title, extra=()):
    """A report with the common header fields."""
    args = session.args
    work_copy = session.work_copy
    target = result.commits[work_copy.rewritten_hash]
    document = report.Report(title)
    document.add_field('repository', 'Repository', str(work_copy.original))
    document.add_field('revision', 'Revision', f'{args.commit} ({work_copy.original_hash[:12]})')
    document.add_field('commit_date', 'Date of that commit', iso_time(target.time))
    document.add_field('commit_subject', 'Its subject', target.subject)
    document.add_field('main_file', 'Main file', session.book.main)
    document.add_field('preamble', 'Preamble counted', 'yes' if args.include_preamble else 'no')
    if args.mailmap is not None:
        mailmap = str(session.mailmap)
    elif session.mailmap is not None:
        mailmap = '.mailmap of the revision'
    else:
        mailmap = 'none'
    document.add_field('mailmap', 'Mailmap', mailmap)
    for key, label, value in extra:
        document.add_field(key, label, value)
    document.add_field('history', 'Commits in the history', str(len(result.commits)))
    document.add_field('script', 'Script', session.script)
    document.add_field('generated', 'Generated', iso_time())
    return document


def common_words_field(session):
    """The header field naming the common-words file, for the scripts that use it."""
    name = session.args.common_words
    return ('common_words', 'Common-words file', str(name) if name else 'default')


def write_report(session, document, author=None):
    args = session.args
    path = cli.output_path(args, session.script, args.commit, cli.EXTENSIONS[args.format],
                           author)
    report.write(document, args.format, path)
    session.progress.finish(path)
