#!/usr/bin/env python3
# * Overview
"""Every author's fair share of a LaTeX project in Git, in percent.  See docs/author_shares.md."""

# * Imports
from contrib import cli, fair, session
from contrib.report import Column

# * Texts
SCRIPT = 'author_shares.py'

DESCRIPTION = """\
Estimate every author's share of a LaTeX project kept in Git, word by word.

Writing a surviving word counts 1; typing it in place of someone else's words, moving
someone else's text, and having your text removed or replaced by someone else count less
(see the weights below).  The report goes to a file; see docs/author_shares.md."""

INTRODUCTION = [
    'This report estimates how much each author contributed to the project at the revision'
    ' given above.  It looks at every word of the text (comments excluded) and follows it'
    ' through the whole history of the repository: who first typed it, whether it was typed'
    ' in place of someone else\'s words, who moved it around, and which words were later'
    ' removed or replaced by someone else.',
    'Each kind of contribution earns points per word, and an author\'s fair share is their'
    ' part of all points.  Writing the text that is in the project earns the most; rewriting'
    ' someone else\'s text earns somewhat less, because it builds on their work; moving text'
    ' earns little; and a draft that someone else later reworked still earns its author'
    ' something, because it shaped the result.  Removing your own text earns nothing, so'
    ' that redrafting does not pay by itself.',
]

GUIDE = [
    '"Fair share" is the main figure.  "Share of the text" only says who typed the words'
    ' that are in the project now, ignoring everything else; it is the simplest and the most'
    ' easily checked figure, but it gives nothing for drafts others rewrote.',
    '"Written" and "rewritten" count the author\'s words in the project: typed fresh, or typed'
    ' in place of someone else\'s words.  "Moved" counts other authors\' words in the project'
    ' that this author moved (for example, a paragraph moved to another chapter).'
    ' "Removed by others" counts words this author wrote that someone else later deleted'
    ' or replaced.',
    'The weights are a judgment call, not a fact.  The sensitivity table shows how the fair'
    ' share changes when each weight is set to 0 or 1; figures that barely move there are'
    ' robust.  The per-chapter tables use only the text in each chapter: removed words have'
    ' no place in the current text, so they count only in the totals.',
]

CAVEATS = [
    'Only what Git records is measured.  Text written by one person but committed by'
    ' another counts for the one who committed it; ideas, proofs worked out in discussion,'
    ' reviewing and editorial decisions are invisible.',
    'A word is any run of non-blank characters, so `\\emph{word},` or a short formula like'
    ' `$x^2$` is one word.  Bulk mechanical changes (reformatting, renaming a macro) count'
    ' like any other edit.',
    'When a sentence is heavily rewritten, common words such as "the" or "of" that happen'
    ' to stay in place keep their original author.  This favors original authors a little.',
    'Text dropped while resolving a merge conflict earns nobody removal credit.',
]


# * Command line
def parse_args():
    parser = cli.make_parser(SCRIPT, DESCRIPTION, is_one_author=False)
    fair.add_weight_options(parser)
    args = cli.parse_args(parser)
    args.weights = fair.weights_from(args, parser)
    return args


# * The report
def build_report(context, result, weights):
    book = context.book
    tallies = fair.tally(book, result)
    shares = fair.shares(tallies, weights)
    total_words = len(book.tokens)
    authors_by_share = fair.ranked(tallies, shares)
    extra = [*fair.weight_fields(weights), ('words', 'Words in the text', str(total_words))]
    document = session.new_report(context, result, 'Authors\' shares of the project', extra)

    intro = document.section('introduction', 'What this report measures')
    for paragraph in INTRODUCTION:
        intro.paragraph(paragraph)
    guide = document.section('guide', 'How to read it')
    for paragraph in GUIDE:
        guide.paragraph(paragraph)

    main_section = document.section('shares', 'Shares')
    table = main_section.table('shares', 'Fair share and its parts, per author', [
        Column('author', 'Author'), Column('fair_share', 'Fair share', 'percent'),
        Column('text_share', 'Share of the text', 'percent'),
        Column('written', 'Written', 'int'), Column('rewritten', 'Rewritten', 'int'),
        Column('moved', 'Moved', 'int'), Column('removed', 'Removed by others', 'int'),
        Column('points', 'Points', 'number')])
    for author in authors_by_share:
        counts = tallies[author]
        table.add(author=author, fair_share=shares[author],
                  text_share=fair.percent(fair.in_text(counts), total_words),
                  written=counts['written'], rewritten=counts['rewritten'],
                  moved=counts['moved'], removed=counts['removed'],
                  points=fair.points(counts, weights))

    sensitivity = document.section('sensitivity', 'Sensitivity to the weights')
    sensitivity.paragraph('Fair share with one weight changed at a time, the others as in'
                          ' the header.')
    variants = fair.sensitivity(tallies, weights)
    columns = [Column('author', 'Author'), Column('default', 'As given', 'percent')]
    columns += [Column(key, label, 'percent') for key, label, _ in variants]
    table = sensitivity.table('sensitivity', 'Fair share under other weights', columns)
    for author in authors_by_share:
        values = {key: variant[author] for key, _, variant in variants}
        table.add(author=author, default=shares[author], **values)

    chapters = document.section('chapters', 'Per chapter')
    chapters.paragraph('Removal credit is not included here (see the guide above).')
    by_chapter = session.tokens_by_chapter(book)
    for number, (title, _) in enumerate(book.chapters):
        tokens = [book.tokens[index] for index in by_chapter.get(number, [])]
        if not tokens:
            continue
        chapter_tallies = fair.tally(book, result, tokens)
        chapter_shares = fair.shares(chapter_tallies, weights)
        part = chapters.section(f'chapter_{number + 1}', title)
        table = part.table(f'chapter_{number + 1}', f'{len(tokens)} words', [
            Column('author', 'Author'), Column('words', 'Words', 'int'),
            Column('text_share', 'Share of the text', 'percent'),
            Column('points_share', 'Share of the points', 'percent')])
        for author in fair.ranked(chapter_tallies, chapter_shares):
            words_in_text = fair.in_text(chapter_tallies[author])
            table.add(author=author, words=words_in_text,
                      text_share=fair.percent(words_in_text, len(tokens)),
                      points_share=chapter_shares[author])

    people = document.section('identities', 'Authors and their identities')
    people.paragraph('Names are as recorded in the commits, after `.mailmap`.')
    table = people.table('identities', '', [Column('author', 'Author'),
                                            Column('identities', 'Identities used')])
    found = session.identities(result)
    for author in sorted(found, key=str):
        table.add(author=author, identities=', '.join(found[author]))

    caveats = document.section('caveats', 'Caveats')
    for paragraph in CAVEATS:
        caveats.paragraph(paragraph)
    return document


# * Main
def main(progress):
    args = parse_args()
    context = session.start(args, progress, SCRIPT)
    result = session.run_replay(context, session.by_name)
    progress.log('computing the shares')
    document = build_report(context, result, args.weights)
    session.write_report(context, document)


if __name__ == '__main__':
    cli.run(main)
