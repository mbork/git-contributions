#!/usr/bin/env python3
# * Overview
"""Everything one author wrote that is still in a LaTeX project in Git: statistics, then every
sentence with the author's words, by chapter and section.  See docs/surviving_text.md."""

# * Imports
from contrib import cli, fair, session
from contrib.report import Column
from contrib.session import THE_AUTHOR

# * Texts
SCRIPT = 'surviving_text.py'
GAP = '[...]'

DESCRIPTION = """\
List everything one author wrote that is still in a LaTeX project kept in Git: first
statistics (words, sentences, formulas, paragraphs), then every sentence containing the
author's words, by chapter and section, with other authors' words shown as [...].  Moving
text is not a contribution here: text keeps its writer wherever it is moved.  The report
goes to a file; see docs/surviving_text.md."""

INTRODUCTION = [
    'This report lists the text written by one author, named above, that is still in the'
    ' project at the revision given above.  Every word of the project (comments excluded) is'
    ' followed through the whole history of the repository to the person who typed it.'
    ' Moving text around does not count here: a paragraph keeps its writer wherever someone'
    ' moves it.',
    'The statistics come first.  Then every sentence, heading and displayed formula that'
    ' contains at least one word by the author is listed on a line of its own, in the order'
    ' of the project, grouped by chapter and section, with the file and line it comes from.',
]

GUIDE = [
    f'In the list, words by other authors are replaced by {GAP}.  A line without {GAP} is'
    ' entirely the author\'s; a line like "We prove [...] by induction." means the author'
    ' wrote the beginning and the end, and someone else the middle (or rewrote it later).',
    'The text is shown as LaTeX source, one space between words: formulas and commands'
    ' appear as they are typed.  Displayed formulas are listed like sentences.  Headings'
    ' are listed too.  Lines made only of structural commands such as `\\label{...}` are'
    ' left out of the list, but their words count in the statistics.',
    '"Entirely" means every word of the sentence, formula or paragraph is the author\'s;'
    ' "partly" means some but not all.  "Words other than common words" leaves out very'
    ' common words such as "the", "of", "let" or "assume", which say little about'
    ' authorship.',
    'Text before the first chapter (the title page, for example) is listed under "(before'
    ' the first chapter)"; text right after a `\\part` heading is listed under that part.'
    '  Verbatim text is shown as typed; LaTeX comments are not shown.',
]

CAVEATS = [
    'Only what Git records is measured: text the author wrote but someone else committed'
    ' is not the author\'s here.',
    'A word is any run of non-blank characters, so a change of punctuation (`word` to'
    ' `word,`) makes the whole word belong to whoever changed it.  When someone heavily'
    ' rewrites a sentence, common words that stay in place still count as the original'
    ' author\'s, so they may show up here in a sentence that is otherwise someone else\'s.',
    'Text deleted in one commit and re-added in a later one belongs to whoever re-added it.',
]


# * Command line
def parse_args():
    parser = cli.make_parser(SCRIPT, DESCRIPTION, is_one_author=True)
    return cli.parse_args(parser)


# * Excerpts
def excerpt(book, indices, is_by_author):
    """The author's words among INDICES (book token indices), other runs shown as GAP."""
    pieces = []
    for index in indices:
        if is_by_author[index]:
            pieces.append(book.tokens[index].text)
        elif not pieces or pieces[-1] != GAP:
            pieces.append(GAP)
    return ' '.join(pieces)


def listed_units(book):
    """Sentences, headings and displayed formulas, in project order, as lists of indices."""
    units = [s.tokens for s in book.sentences if s.kind in session.SENTENCE_KINDS]
    units += [b.tokens for b in book.blocks if b.kind == 'display']
    return sorted((unit for unit in units if unit), key=lambda unit: unit[0])


def section_title(book, token):
    return book.sections[token.section].title


# * Statistics
def add_statistics(document, book, is_by_author, is_uncommon, listed):
    section = document.section('statistics', 'Statistics')
    table = section.table('statistics', 'What the author wrote that is in the project', [
        Column('measure', 'Measure'), Column('count', 'By the author', 'int'),
        Column('total', 'Total', 'int'), Column('share', 'Share', 'percent')])
    uncommon_words = sum(1 for is_mine, is_rare in zip(is_by_author, is_uncommon)
                         if is_mine and is_rare)
    rows = [('Words', sum(is_by_author), len(book.tokens)),
            ('Words other than common words', uncommon_words, sum(is_uncommon))]
    for key, label, units in session.unit_lists(book):
        fractions = session.unit_fractions(units, is_by_author)
        if key == 'paragraphs':
            rows.append(('Paragraphs with words by the author',
                         sum(1 for f in fractions if f > 0), len(units)))
            continue
        rows += [(f'{label} entirely by the author', sum(1 for f in fractions if f == 1),
                  len(units)),
                 (f'{label} partly by the author', sum(1 for f in fractions if 0 < f < 1),
                  len(units))]
    for label, count, total in rows:
        table.add(measure=label, count=count, total=total, share=fair.percent(count, total))
    section.paragraph(f'The list below has {listed} lines.')


# * The list
def add_text(document, book, units, is_by_author):
    """One subsection per chapter and section, each with a listing of its lines."""
    text = document.section('text', 'The text')
    chapters = {}
    listings = {}
    for indices in units:
        first = book.tokens[indices[0]]
        is_part = first.section >= 0 and book.sections[first.section].command == 'part'
        if is_part:
            key = ('part', first.section)
            if key not in listings:
                part = text.section(f'part_{first.section + 1}',
                                    'Part: ' + section_title(book, first))
                listings[key] = part.listing(f'lines_part_{first.section + 1}')
            add_line(book, listings[key], indices, is_by_author)
            continue
        if first.chapter not in chapters:
            title = book.chapters[first.chapter][0]
            chapters[first.chapter] = text.section(f'chapter_{first.chapter + 1}', title)
        key = (first.chapter, first.section)
        if key not in listings:
            suffix = f'{first.chapter + 1}_{first.section + 1}'
            is_chapter_text = first.section == book.chapters[first.chapter][1]
            if is_chapter_text:
                part = chapters[first.chapter]
            else:
                part = chapters[first.chapter].section(f'section_{suffix}',
                                                       section_title(book, first))
            listings[key] = part.listing(f'lines_{suffix}')
        add_line(book, listings[key], indices, is_by_author)


def add_line(book, listing, indices, is_by_author):
    first = book.tokens[indices[0]]
    source = book.files[first.path]
    location = f'{first.path}:{source.line_of(first.start)}'
    listing.add(location, excerpt(book, indices, is_by_author))


# * The report
def build_report(context, result):
    book = context.book
    is_by_author, is_uncommon = session.author_masks(context, result)
    name = session.display_name(result, THE_AUTHOR)
    extra = [('author', 'Author', name),
             ('author_regex', 'Author regex', context.args.author),
             session.common_words_field(context),
             ('words', 'Words in the text', str(len(book.tokens)))]
    document = session.new_report(context, result, f'Text by {name} in the project', extra)
    session.add_prose(document, 'introduction', 'What this report shows', INTRODUCTION)
    session.add_prose(document, 'guide', 'How to read it', GUIDE)
    units = [indices for indices in listed_units(book)
             if any(is_by_author[index] for index in indices)]
    add_statistics(document, book, is_by_author, is_uncommon, len(units))
    add_text(document, book, units, is_by_author)
    session.add_identities_section(document, result)

    session.add_prose(document, 'caveats', 'Caveats', CAVEATS)
    return document, name


# * Main
def main(progress):
    args = parse_args()
    context, result, _ = session.start_one_author(args, progress, SCRIPT)
    progress.log('collecting the author\'s text')
    document, name = build_report(context, result)
    session.write_report(context, document, name)


if __name__ == '__main__':
    cli.run(main)
