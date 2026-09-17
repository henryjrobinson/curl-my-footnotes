# Design record

This document records how curl-my-footnotes was designed. It covers the research, the design, the review of the design, the decisions, and the findings from real runs. It was written on 2026-09-16.

## Terms used in this document

- A **footnote** means a claim in a document plus the link that should back it up.
- A **dead link** is a link to a page that once existed and is now gone.
- An **invented link** is a link that an AI model made up. The page never existed.
- The **Wayback Machine** is the Internet Archive's public store of old copies of web pages.
- A **status code** is the number a web server sends back with a page. 200 means fine. 404 means not found.
- A **soft 404** is a "page not found" screen that wrongly reports status 200.
- A **robot check** is the "prove you are human" screen that some sites show to scripts.
- A **deterministic** step gives the same output for the same input. It uses no AI model.
- A **false pass** is when the tool says a footnote is good and the footnote is bad.
- A **false alarm** is when the tool flags a footnote that is good.
- **Alarm fatigue** means people stop reading warnings after too many wrong ones.
- A **golden set** is a test document where the right answer for every footnote is known in advance.
- A **kill number** is a score, chosen before any results exist, below which the feature does not ship.
- **Prompt injection** is text on a web page that tries to give orders to an AI model that reads the page.
- A **pure function** is code whose result depends only on its inputs. It makes no network calls.

## 1. The starting idea

The owner asked for a Claude skill that reads each footnote and pings the link. A link that fails is reported as bad. The purpose is to catch invented sources in AI-written text and in other people's documents.

The owner asked two questions.

1. How likely is an invented link that points at a real, working page?
2. If that is likely, should a model open each page and check that it relates to the claim?

The owner also set one constraint. A deterministic run must come first, to validate the links themselves.

## 2. What the research says

The answer to question 1 is "likely, not remote". That makes the page-reading step the main feature.

| Finding | Source |
|---|---|
| 10 models and about 53,000 links were tested. 5 to 18 percent of links did not load. 3 to 13 percent were invented. The study told invented links from dead links by looking for a saved copy in the Wayback Machine. | [arXiv 2604.03173](https://arxiv.org/abs/2604.03173) |
| In research agents, more than 94 percent of links loaded and more than 80 percent of pages were on topic. Only 39 to 77 percent of cited claims were factually supported. | [arXiv 2605.06635](https://arxiv.org/abs/2605.06635) |
| About 30 percent of statements from GPT-4o with web search were not supported by the cited source. Between 50 and 90 percent of full responses were not fully supported. | [Nature Communications, 2025](https://www.nature.com/articles/s41467-025-58551-6) |
| Eight AI search tools gave wrong citations for more than 60 percent of queries. Grok 3 sent 154 of 200 citations to error pages. | [Columbia Journalism Review, 2025](https://www.cjr.org/tow_center/we-compared-eight-ai-search-engines-theyre-all-bad-at-citing-news.php) |

Confidence note: these numbers were read from fetched summaries of each source on 2026-09-16. Each link was confirmed to load. The full papers were not read line by line.

The plain reading: a link ping catches roughly one bad footnote in three. The other two load without error.

## 3. The three ways a footnote fails

1. **Dead link.** The page once existed and is gone. The footnote was honest. The fix is to cite the archived copy.
2. **Invented link.** The page never existed.
3. **Unsupported claim.** The page loads and does not say what the footnote claims. The page can even be on the right topic and still lack the specific fact.

"On topic" is the wrong test. A page about unemployment is on topic for the sentence "unemployment hit 4.2 percent". The page supports the sentence only if the 4.2 is on the page. This project uses the word **supports** everywhere and never the word "relevant".

## 4. The design

### Step 0: extract the footnotes (script)

The script pairs each link with the sentence it sits on. It handles markdown footnotes, numbered references, inline links, and bare links. HTML is converted first. A footnote with no link is recorded and never dropped.

### Step 1: check each link (script)

The script fetches each unique link once. It detects soft 404 pages, redirects to the home page, and robot-check pages.

### Step 1b: ask the archive (script)

This step came from the owner's design. When a page is missing or blocked, the script asks the Wayback Machine for a saved copy. The lookup is a plain web request. No model is needed.

- A saved copy proves the page once existed.
- The text of the saved copy is kept, so the reading step can judge it later.
- A side benefit: many sites that block scripts still have saved copies.

### Step 2: read each page (model, not built)

A model gets the claim and the page text. It returns a verdict and a word-for-word quote **from the page** that supports the claim. A script then confirms that the quote really appears in the page text. If the quote is missing, the verdict drops to "could not confirm".

One point caused confusion in review, so it is stated here plainly. The script never compares the footnoted sentence with anything. The model makes the whole judgment, and paraphrase is fine. If the document says "the official position of the White House is to support X", the model may accept a page that says "the President today endorsed X". The script only proves that the evidence sentence exists on the page. This stops the checking model from inventing proof.

### Step 3: the report (template)

The labels and counts come from the script's saved results. A model may word the summary. A model may never change a label or a count.

### Why a model at all

Steps 0, 1, 1b, and 3 need no model. Step 2 needs one because a script cannot judge whether a paragraph supports a sentence. A keyword-overlap script would pass any page on the right topic. That is exactly the failure the research found.

### Plan for the model step

- **Which model.** Inside a Claude skill, the running Claude session does the reading. For long documents, each footnote can go to a small, cheap model as a sub-task.
- **Cost.** A rough guess is one to three US cents and a few seconds per footnote. This guess is unverified.
- **How it fails.**
  1. It passes a page that is on topic and lacks the specific number. This is the expected top failure.
  2. It invents a quote. The script catches this.
  3. The page contains prompt injection. The reading model gets no tools and can only return a verdict, so an attack has nothing to grab.
  4. The page builds its content with JavaScript and the script sees a blank page. The footnote goes to `could not check`.
- **How it is measured.** See section 9. The eval is not designed yet.

## 5. The labels, and why they are worded this way

An early draft used labels such as "valid, possibly hallucinated". Review rejected that wording for three reasons.

1. The tool can see what happened. It cannot see why. A page that loads and does not support the claim has at least four causes. A model invented the connection. A human misread the source. The author pasted the wrong link. The page changed after it was cited.
2. A link that loads was not invented. "Valid, possibly hallucinated" contradicts itself.
3. When the document belongs to someone else, a wrong accusation has a real cost.

So each label states only what the tool saw. Only one case earns the word "possibly": the page does not load and the archive never saw it. Even then the word stays, because the archive does not hold every page.

The labels come from two questions. Could we get the page: live, archive only, never existed, or unknown? Does it support the claim: yes, no, or could not judge? Version 1 answers the first question.

| Version 1 label | When |
|---|---|
| `live` | Status 200, not a soft 404, not a home-page redirect, not a robot check. |
| `dead, archived copy exists` | Page missing (404, 410, soft 404, home-page redirect, or the domain does not exist) and the archive has a readable copy. |
| `does not load, never archived (possibly invented)` | Page missing and the archive answered that it has no copy. |
| `blocked live, archived copy exists` | The live fetch was unclear (401, 403, 429, 451, 5xx, timeout, certificate error, robot check) and the archive has a readable copy. |
| `could not check` | The live fetch was unclear and the archive has no copy. Or the archive could not be reached. Or the archived copy is itself a robot check. Or archive checking was turned off. |
| `not checked, no link` | The footnote has no link. |

Version 2 will add the support verdict to `live` and to the two archived labels.

## 6. Which mistake is worse

The false pass is far worse. The whole reason to run the tool is to stop trusting footnotes blindly. A false pass gives false confidence, which is worse than no tool.

The false alarm is cheap and not free. It has two costs.

1. On someone else's document, a false alarm says the author faked a source when they did not.
2. Too many false alarms cause alarm fatigue. Then the real flags get skipped.

The rule that follows: the tool says "good" only with proof. Anything it could not load or could not judge goes to `could not check`. It is never folded into "good" or into "bad".

The cost also depends on who the user is. For an author, a false pass means embarrassment. For a reader, it means relying on a claim that nothing backs up. The report must serve both.

## 7. Draft acceptance criteria

These are a draft from the design review. The owner has not signed off on a final list.

1. Every footnote in the document appears in the report exactly once. None are dropped, including footnotes with no link.
2. Every footnote gets exactly one label.
3. The tool never uses a model to decide whether a link loads. The model is used only to judge support.
4. A footnote is marked as supported only when the report shows a quote that a script found on the page.
5. The tool never marks a footnote as good unless both checks ran and passed.
6. A footnote that fails a check is a normal result and goes in the report. A check that could not run is reported loudly for that footnote. It never stops the run for the other footnotes.
7. The report states what the tool did not check.

## 8. Findings from real runs

These facts came from running the script against real sites on 2026-09-16. Several of them changed the design.

1. **The archive's simple lookup address refused every call.** `archive.org/wayback/available` returned status 429 (too many requests) on the first call and on every later call from the build machine. The script falls back to the archive's second address, called CDX.
2. **The CDX address works and fails now and then.** It returned 200, 503, 504, and dropped connections in one session. Its error pages are HTML, not data. The script never reads an error page as "the archive has no copy".
3. **"The lookup failed" and "the lookup said no" are different answers.** On one run, three CDX failures in a row produced `could not check` for a link that the archive does hold. A later run found it. Without this split, a busy archive would turn real links into accusations.
4. **A robot check can return status 200.** The Nature site answers scripts with a page titled "Client Challenge". An invented Nature link first came back `live`. That was a false pass. Robot-check pages now count as blocked.
5. **The archive can hold a robot check too.** The saved copy of a real Nature article was the same robot-check screen. "Archived copy exists" was hollow. That case now gives `could not check`, and the text is never saved for the reading step.
6. **Some sites answer every address with a normal page.** A script cannot detect this. The report says that a loaded link is weak evidence. Only the reading step can close this gap.
7. **Python can lack a certificate list.** The build machine's Python had an empty list of trusted certificates, so every secure request failed. The script borrows the operating system's list. It never turns certificate checking off.
8. **Run time.** Healthy links take seconds. Each link that does not load adds a polite wait for the archive. Six footnotes with four such links took about twenty minutes.

## 9. Open items

1. **The eval for the reading step.** The owner's rule is that a model's judgment gets a designed measurement before it runs. The design must name the golden set, the grader, the deciding metric, and the kill number. None of these exist yet. A starting idea from review: about 50 footnotes of five kinds, with "right topic, fact absent" as the largest group. The deciding metric would be the false pass rate. The owner has not adopted this.
2. **When the reading step runs.** It could run always, or only on request. Review leaned toward "always, with a links-only mode". The owner has not decided.
3. **Sources with no link.** Journal papers often carry a DOI, a permanent catalogue number, and the free Crossref database can confirm the paper exists. Free book catalogues such as Open Library can confirm a book exists. These lookups prove the source exists. They do not prove that a given page says what the footnote claims. Version 1 declines all of these and says so.
4. **Pairing a claim with its footnote.** A marker at the end of a paragraph may cover one sentence or several. One source may be cited in five places for five claims. A wrong pairing causes false alarms no matter how good the model is. Version 1 flags the uncertain cases. The golden set must include them.
5. **Partial support.** A claim may hold two facts and the page may support one. The verdict scale for this case is not designed.
6. **A real browser for blocked sites.** This would reduce `could not check` results. It adds weight and run time.
7. **A license for this repo.**

## 10. Options that were rejected

| Option | Why it was rejected |
|---|---|
| Build only the link ping and stop. | The research says it catches about a third of bad footnotes. A free package already does it. It gives false comfort. |
| Use the existing `urlhealth` package for step 1. | It treats any status 200 as live, so it would pass a robot-check page. It labels every status other than 200 and 404 as unknown. It was at version 0.1.0. Its GitHub repository carries an MIT license, and its package page listed none. Its archive method remains a good design reference. See [prior-art.md](prior-art.md). |
| Match the footnoted sentence against the page with a script. | Authors paraphrase. String matching cannot judge meaning. |
| Let the model write the final labels. | A model could then change a verdict while it writes the summary. |
| Label unclear cases as bad. | This accuses honest footnotes and causes alarm fatigue. |

## 11. How version 1 was built

A planning model wrote the specification and reviewed the result. A cheaper model wrote the code and the tests from that specification. The planning model ran the tests again, read the labelling logic, and checked the live results before the commit. Three defects were found through real runs and fixed in the same session. They are findings 4, 5, and 6 in section 8.
