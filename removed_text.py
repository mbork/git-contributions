#!/usr/bin/env python3
# * Overview
"""Everything one author wrote that did not survive in a LaTeX project in Git: statistics,
then every removed piece, commit by commit.  See docs/removed_text.md."""

# * Imports
from collections import Counter

from contrib import cli, fair, session, words
from contrib.report import Column
from contrib.session import THE_AUTHOR

# * Texts
SCRIPT = 'removed_text.py'

DESCRIPTION = """\
List everything one author wrote in a LaTeX project kept in Git that is no longer in it at
the given revision: first statistics (who removed how much), then every removed piece of
text, commit by commit, with who removed it, when, and where it was.  The report goes to
a file; see docs/removed_text.md."""

INTRODUCTION = [
    'This report lists the text written by one author, named above, that was later deleted'
    ' or replaced, up to the revision given above.  Every word (comments excluded) is'
    ' followed through the whole history of the repository; when a word written by the'
    ' author disappears from the project, it is listed here, with the commit that removed it.',
    'Text that was only moved -- a block of at least 8 words taken out and put back'
    ' elsewhere in one commit, for example a paragraph moved to another chapter -- is not'
    ' removed and does not appear here.  The statistics come first; then the removed pieces,'
    ' commit by commit, in the order of the history.',
]

GUIDE = [
    'A piece is a run of consecutive words by the author removed in one commit.  Each piece'
    ' shows the file and section it was in at the time, and the commit says who removed it'
    ' and when.  The text is LaTeX source with one space between words.',
    'Pieces the author removed themselves are usually redrafting; pieces removed by someone'
    ' else are usually rewriting or cutting by a co-author.  A replaced word counts as'
    ' removed: if someone changed "colour" to "color", the author\'s "colour" is listed.',
]

CAVEATS = [
    'Only what Git records is measured: text the author wrote but someone else saved into'
    ' the repository is not the author\'s here.',
    'When two lines of work are combined (a merge), text dropped while reconciling them by'
    ' hand is not listed; and text that one line of work removed but the merge brought back'
    ' is listed as removed although it is in the project again.',
    'A word is any run of non-blank characters, so a change of punctuation (`word` to'
    ' `word,`) lists the old word as removed.  Text moved in two steps (taken out in one'
    ' change, put back in a later one), or in blocks of fewer than 8 words, is listed as'
    ' removed.',
    'Removals from the preamble (the part of a file before `\\begin{document}`) are not'
    ' listed unless `--include-preamble` is given.',
]

STATISTICS_NOTE = (
    '"Ever typed" counts every word the author typed in any commit, including words later'
    ' removed; moved words are not typed again.  Typed words can also leave the project by'
    ' being moved into a file that is no longer included, so the rows need not add up.')


# * Command line
def parse_args():
    parser = cli.make_parser(SCRIPT, DESCRIPTION, is_one_author=True)
    return cli.parse_args(parser)


# * Removers
def remover_name(key, name):
    return f'{name} (the author)' if key == THE_AUTHOR else str(key)


# * Report sections
def add_statistics(document, context, result, name):
    removals = result.removals
    by_remover = Counter()
    for removal in removals:
        by_remover[removal.remover] += len(removal.words)
    removed_total = sum(by_remover.values())
    uncommon = sum(1 for removal in removals for word in removal.words
                   if not words.is_common(word, context.common))
    is_by_author, _ = session.author_masks(context, result)
    surviving = sum(is_by_author)
    section = document.section('statistics', 'Statistics')
    table = section.table('statistics', 'The author\'s words', [
        Column('measure', 'Measure'), Column('words', 'Words', 'int')])
    table.add(measure='Ever typed by the author', words=result.typed.get(THE_AUTHOR, 0))
    table.add(measure='Still in the project', words=surviving)
    table.add(measure='Removed or replaced', words=removed_total)
    table.add(measure='Removed or replaced, other than common words', words=uncommon)
    table.add(measure='Removed pieces', words=len(removals))
    table.add(measure='Commits that removed them',
              words=len({removal.commit for removal in removals}))
    table = section.table('removers', 'Who removed the author\'s words', [
        Column('remover', 'Removed by'), Column('words', 'Words', 'int'),
        Column('share', 'Share', 'percent')])
    for key, count in sorted(by_remover.items(), key=lambda item: (-item[1], str(item[0]))):
        table.add(remover=remover_name(key, name), words=count,
                  share=fair.percent(count, removed_total))
    section.paragraph(STATISTICS_NOTE)


def add_pieces(document, context, result, name):
    section = document.section('pieces', 'The removed text')
    if not result.removals:
        section.paragraph('Nothing the author wrote was removed.')
        return
    original_of = context.work_copy.original_of()
    by_commit = {}
    for removal in result.removals:
        by_commit.setdefault(removal.commit, []).append(removal)
    for number, (commit_hash, removals) in enumerate(by_commit.items(), 1):
        commit = result.commits[commit_hash]
        original = original_of.get(commit_hash, commit_hash)
        date = session.iso_time(commit.time)[:10]
        part = section.section(f'commit_{number}', f'{date} {original[:10]} {commit.subject}')
        count = sum(len(removal.words) for removal in removals)
        noun = 'word' if count == 1 else 'words'
        remover = removals[0].remover
        part.paragraph(f'Removed by {remover_name(remover, name)}: {count} {noun},'
                       f' commit `{original}`.')
        listing = part.listing(f'commit_{number}')
        for removal in removals:
            location = removal.path
            if removal.section:
                location += f', {removal.section}'
            listing.add(location, ' '.join(removal.words))


# * The report
def build_report(context, result):
    name = session.display_name(result, THE_AUTHOR)
    extra = [('author', 'Author', name),
             ('author_regex', 'Author regex', context.args.author),
             session.common_words_field(context)]
    document = session.new_report(context, result, f'Text by {name} that was removed', extra)
    session.add_prose(document, 'introduction', 'What this report shows', INTRODUCTION)
    session.add_prose(document, 'guide', 'How to read it', GUIDE)
    add_statistics(document, context, result, name)
    add_pieces(document, context, result, name)
    session.add_identities_section(document, result)
    session.add_prose(document, 'caveats', 'Caveats', CAVEATS)
    return document, name


# * Main
def main(progress):
    args = parse_args()
    context, result, _ = session.start_one_author(args, progress, SCRIPT, does_watch=True)
    progress.log('collecting the removed text')
    document, name = build_report(context, result)
    session.write_report(context, document, name)


if __name__ == '__main__':
    cli.run(main)
