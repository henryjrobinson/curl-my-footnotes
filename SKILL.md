---
name: curl-my-footnotes
description: Checks the footnotes of a document by loading every link it cites and reporting what came back. Use when the user says "check footnotes", "check my footnotes", "curl my footnotes", "verify citations", "verify these sources", "are these links real", "did you make this up", or asks to check the sources in a document, a report, or a draft. Works on Claude's own footnotes and on documents written by other people. Version 1 checks only whether the site answers at each address. It does not read the page or judge whether it supports the claim.
---

# curl my footnotes

## What this skill does

This skill finds every claim in a document that cites a link. It then asks the web for each link and writes down what came back. The point is to catch links that do not exist, links that died, and links that were never real.

A footnote here means two things together. The first is the claim, which is the sentence that cites the source. The second is the link that is supposed to back that claim up.

The skill reads markdown footnotes such as `[^1]`, numbered references such as `[12]`, inline links such as `[text](url)`, and plain links pasted into the text. It skips mail links, page anchors, and relative links.

When a link does not load, the skill asks the Wayback Machine whether a copy was ever saved. That answer separates two very different problems. A link that died still has an archived copy. A link that never existed has nothing.

## How to run it

Run the script. It needs Python 3.10 or later and no installed packages.

```
python3 <SKILL_DIR>/scripts/check_footnotes.py <file>
```

The file can be `.md`, `.txt`, or `.html`.

If the user pasted text into the chat instead of naming a file, save the text to a temporary file first, then run the script on that file.

Useful options:

- `--out-dir DIR` sets where the results go. The default is `./footnote-check-<name>/`.
- `--no-archive` skips the Wayback Machine. Use it when the run must be fast or offline from the archive.
- `--timeout 15` sets how many seconds to wait for each page.

The script writes three things into the output folder. `report.md` is for a person to read. `results.json` holds the same findings as data. The `pages/` folder holds the text of each page that loaded, saved for a later version of this skill.

The script exits with code 0 whenever the run finished, however many footnotes were bad. It exits with code 2 only when the input file is missing, unreadable, or empty.

A run can take several minutes. The Wayback Machine limits how fast anyone may ask it questions, so the script waits between archive calls on purpose.

## How to present the results

Show the script's `report.md` to the user as it is written.

Never change a label. Never change a count. Never re-sort the findings to look better. The labels describe what the tool saw, and the tool saw it, not you.

Never call a footnote good, verified, correct, or supported. Version 1 checked one thing only, which is whether the site answered at that address. A page that loads can still say the opposite of the claim, and some sites answer every address they are given. Saying more than the tool measured is the exact failure this skill was built to catch.

If the user asks whether a source really supports a claim, say plainly that this version does not check that, and point at the "Not built yet" section below.

## The six labels

- `live`. The site answered at that address and the answer looks like a real page. This is weak evidence. Some sites answer every address, even invented ones, with a page that looks normal.
- `dead, archived copy exists`. The page is gone, and the Wayback Machine has a saved copy.
- `does not load, never archived (possibly invented)`. The page is gone, and the archive never had a copy. This is the pattern a made up citation leaves.
- `blocked live, archived copy exists`. The site refused the script or showed it a robot check, and the archive has a saved copy. The link is probably fine.
- `could not check`. The tool could not reach a conclusion. The reason says which case it hit. An archive lookup that failed is always this label, never the possibly invented one. An archived copy that is itself a robot check also lands here, because such a copy is no evidence that the page exists.
- `not checked, no link`. The footnote cites a book, a paper, or a person, with no link to fetch.

Three more notes matter when you read a report.

The tool spots robot check pages. Many sites answer a script with a page that says "Client Challenge", "Just a moment", or "Checking your browser", and they send it with a normal status code. The tool treats that as an unclear answer, the same as being refused outright. Such a link is never marked `live`, and the text of the robot check page is never saved for reading.

One gap remains. Some sites answer every address with a page that looks perfectly normal, including addresses that were never real. The tool cannot tell those apart, so it marks them `live`. A `live` label means the site answered, not that the source exists.

A footnote marked with an uncertain claim scope sits at the end of a paragraph that holds several sentences. The footnote may cover all of them. The report shows one sentence, so read the paragraph before judging that footnote.

## Not built yet

Version 1 stops at "does this page exist". The next step is a model that reads each saved page and judges whether it supports the claim.

That step is not built, and it waits on an eval design from Henry. The eval must name the metric, the grader, the sample size, and the kill number before any judging runs.

Do not improvise that judgment while running this skill. Do not read the files in `pages/` and decide for yourself whether a source checks out. A judgment with no rubric behind it is a guess wearing a label, and it would undo the reason this skill exists.
