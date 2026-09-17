# curl-my-footnotes

A footnote checker for the age of AI-written text. It reads a document, finds every footnote, and tells you which links you can trust and which you must check by hand.

It works as a Claude Code skill and as a plain command-line script.

## Terms used in this document

- A **footnote** here means a claim in a document plus the link that should back it up.
- A **dead link** is a link to a page that once existed and is now gone.
- An **invented link** is a link that an AI model made up. The page never existed.
- The **Wayback Machine** is the Internet Archive's public store of old copies of web pages.
- A **robot check** is the "prove you are human" screen that some sites show to scripts.
- A **status code** is the number a web server sends back with a page. 200 means fine. 404 means not found.
- A **false pass** is when a tool says a footnote is good and the footnote is bad.

## Status

| Part | State |
|---|---|
| Version 1: script that checks whether each link loads | Built. 54 offline tests pass. One live run verified. |
| Version 2: model step that reads each page and judges whether it supports the claim | Not built. It waits on an eval design. See [docs/design.md](docs/design.md). |

## Why this exists

AI models write links that look real. Some of those links do not load. A larger share load fine and do not support the claim.

- A 2026 study tested 10 models and about 53,000 links. Between 5 and 18 percent of the links did not load. Between 3 and 13 percent were invented. ([arXiv 2604.03173](https://arxiv.org/abs/2604.03173))
- A 2026 study of research agents found that more than 94 percent of links loaded. More than 80 percent of the pages were on topic. Only 39 to 77 percent of the cited claims were supported by the page. ([arXiv 2605.06635](https://arxiv.org/abs/2605.06635))
- A 2025 medical study found that about 30 percent of statements from GPT-4o with web search were not supported by the cited source. ([Nature Communications](https://www.nature.com/articles/s41467-025-58551-6))

A footnote can fail in three ways.

1. **Dead link.** The page is gone.
2. **Invented link.** The page never existed.
3. **Unsupported claim.** The page loads and does not say what the footnote claims.

Version 1 handles the first two. Version 2 will handle the third, which the research says is the largest problem.

## How version 1 works

1. The script pulls every footnote out of a markdown, text, or HTML file. It pairs each link with the sentence it sits on.
2. The script visits each unique link once.
3. If a page is missing or blocked, the script asks the Wayback Machine for a saved copy.
4. A small pure function turns those two results into one label and one plain sentence that gives the reason.
5. The script writes a report, a data file, and the text of each page for the future reading step.

No AI model runs in version 1. The same input gives the same labels, as long as the sites and the archive answer the same way.

## The six labels

Each label says what the tool saw. No label guesses why.

| Label | Meaning |
|---|---|
| `live` | The site answered with a normal page. This is weak evidence. Some sites answer every address, even invented ones. |
| `dead, archived copy exists` | The page is gone. The archive holds a saved copy, so the page once existed. |
| `does not load, never archived (possibly invented)` | The page is gone and the archive never saw it. |
| `blocked live, archived copy exists` | The site blocked the script. The archive holds a readable saved copy. |
| `could not check` | The tool could not find out. The reason sentence says why. |
| `not checked, no link` | The footnote has no link, for example a book. |

Safety rules built into the labels:

- A robot-check page never counts as `live`.
- An archive failure never counts as "never archived".
- An archived copy that is itself a robot check gives `could not check`.
- The script never turns off certificate checking.

## Quick start

You need Python 3.10 or later. The script uses the standard library only.

```bash
python3 scripts/check_footnotes.py my-document.md
```

Options:

| Option | Effect |
|---|---|
| `--out-dir DIR` | Where to write the results. The default is `./footnote-check-<file name>/`. |
| `--no-archive` | Skip the Wayback Machine. The run takes seconds. Every link that does not load becomes `could not check`. |
| `--timeout 15` | Seconds to wait for each page. |

The script writes three things:

- `report.md` is the plain-English report. It also prints to the screen.
- `results.json` holds one row per footnote.
- `pages/` holds the text of each page, for the future reading step.

A document with healthy links finishes in seconds. Each link that does not load adds a polite wait for the archive. A test document with four such links took about twenty minutes.

## Install as a Claude Code skill

```bash
git clone https://github.com/henryjrobinson/curl-my-footnotes.git ~/code/github/curl-my-footnotes
ln -s ~/code/github/curl-my-footnotes ~/.claude/skills/curl-my-footnotes
```

Then start a new Claude Code session and say "curl my footnotes" with a file path.

## Run the tests

```bash
python3 -m unittest discover -s tests -v
```

All tests run offline.

## Known limits

- A `live` label does not mean the footnote is honest. Nobody has read the page yet.
- Some sites return a normal page for every address. The script cannot detect that without a real browser.
- The script does not read PDF text.
- The script does not look up books or journal papers that have no link.
- The Wayback Machine fails now and then. When it fails, the label is `could not check`.
- A footnote marker at the end of a long paragraph may cover several sentences. The report flags these footnotes.

## More documentation

- [docs/design.md](docs/design.md) is the full design record: research, decisions, rejected options, and findings from real runs.
- [docs/prior-art.md](docs/prior-art.md) is a survey of existing tools for checking links, citations, and claims.

## License

No license is chosen yet.
