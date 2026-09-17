# Prior art: tools that check footnotes, links, and citations

## Terms used in this document

- **Link checker**: a tool that visits a list of URLs and reports which ones return an error or fail to load.
- **Wayback Machine**: an archive run by the Internet Archive that stores old copies of web pages. It can show whether a page used to exist even if it is gone now.
- **DOI (Digital Object Identifier)**: a permanent ID string assigned to an academic paper. It still finds the paper even if the paper's web address changes.
- **Crossref**: a nonprofit registry that stores DOIs and details for millions of academic papers. It offers a free search API.
- **NLI (natural language inference)**: a task where a model decides if one piece of text supports, contradicts, or says nothing about another piece of text. Fact-checking tools use this to compare a source against a claim.
- **Attribution**: in AI research, this means whether a piece of generated text is actually backed up by the source it points to.
- **RAG (retrieval-augmented generation)**: a setup where a model first pulls in relevant documents, then writes an answer that is supposed to stick to those documents.

## Summary

This survey found no open-source tool that does all three checks curl-my-footnotes plans to do in one pass on a document's footnotes. Tools split cleanly into three camps that do not talk to each other.

General link checkers, such as lychee and markdown-link-check, report only whether a URL returns an error. They cannot tell a dead link from one that never existed, and they never look at whether a page supports a claim.

One close match exists for telling dead links from invented ones: urlhealth, released alongside an April 2026 paper by Rao, Wong, and Callison-Burch, checks URL liveness and uses the Wayback Machine to classify a failing link as stale or hallucinated. It works on a list of URLs, not on footnote-and-claim pairs pulled from a document.

A separate group of research tools, such as MiniCheck, RAGAS's faithfulness metric, and SourceCheckup, judges whether a source's text supports a claim. None of them fetch the page themselves or handle a dead-versus-invented distinction. curl-my-footnotes sits in the gap between these two camps: a single script that extracts footnotes from a document, fetches each link, falls back to the Wayback Machine the way urlhealth does, and (in v2) adds a claim-support judge with a script-checked evidence quote.

## A. General link checkers

| Tool | Link | Language | License | Maintained | Checks | Catches dead / invented / unsupported |
|---|---|---|---|---|---|---|
| lychee | https://github.com/lycheeverse/lychee | Rust | Apache-2.0 | Yes, last commit 2026-09-14 | Crawls Markdown, HTML, reStructuredText, or a website and checks each hyperlink and mail address | Dead only |
| markdown-link-check | https://github.com/tcort/markdown-link-check | JavaScript | ISC | Yes, last commit 2026-07-28 | Checks every hyperlink in a Markdown file to see if it is alive or dead | Dead only |
| linkinator | https://github.com/JustinBeckwith/linkinator | TypeScript | MIT | Yes, last commit 2026-09-16 | Crawls a site or a folder of documents and validates every link it finds | Dead only |
| LinkChecker | https://github.com/linkchecker/linkchecker | Python | GPL-2.0 | Yes, last commit 2026-07-28 | Crawls websites or local files and validates links, with recursive site checks | Dead only |
| muffet | https://github.com/raviqqe/muffet | Go | MIT | Yes, last commit 2026-09-15 | Fast website link checker, built for checking large sites in CI | Dead only |
| broken-link-checker | https://github.com/stevenvachon/broken-link-checker | JavaScript | MIT | Yes, last commit 2026-09-07 | Finds broken links and missing images inside HTML | Dead only |

This group is mature and actively maintained. All six tools are free, open source, and built to answer one question: does this URL return a working page right now. None of them distinguish a page that used to exist from one that never did, because none of them query an archive. None of them look at page content against a claim. They are a good model for curl-my-footnotes's basic fetch step, but they stop exactly where the "dead vs. invented" problem starts.

## B. Tools aimed at AI-invented / hallucinated links or citations

| Tool | Link | Language | License | Maintained | Checks | Catches dead / invented / unsupported |
|---|---|---|---|---|---|---|
| urlhealth | https://github.com/delip/urlhealth (PyPI: https://pypi.org/project/urlhealth/) | Python | MIT on the GitHub repo (PyPI package metadata lists no license classifier) | Yes, last commit 2026-04-09, PyPI version 0.1.0 | Checks whether a URL is live, dead, or likely hallucinated, using the Wayback Machine as a fallback | Dead and invented |
| refchecker | https://github.com/markrussinovich/refchecker | Python | MIT | Yes, last commit 2026-09-07 | Validates that an academic paper reference actually exists | Dead and invented (for academic references, not general web footnotes) |
| hallucinator | https://github.com/gianlucasb/hallucinator | Rust | Not confirmed (GitHub reports "NOASSERTION," meaning no detectable license file) | Yes, last commit 2026-09-10 | Extracts references from academic PDFs and checks them against CrossRef, arXiv, DBLP, and OpenAlex | Invented (flags a reference it cannot find in any database) |
| Citation-Hallucination-Detection | https://github.com/Vikranth3140/Citation-Hallucination-Detection | Python | MIT | Yes, last commit 2026-04-24 | Combines exact bibliographic lookup, fuzzy matching, and optional LLM verification to classify a citation as valid, partially valid, or hallucinated | Invented |
| llm-citation-verifier | https://github.com/DWFlanagan/llm-citation-verifier | Python | Not confirmed (no license field found on the repo) | Last commit 2025-07-14 | An LLM tool plugin that checks citations against Crossref to catch fake DOIs in AI-written text | Invented |

This is the newest and smallest group, and it is the one closest to curl-my-footnotes's actual problem. Most of these tools target academic citations (DOIs, paper titles) rather than arbitrary web footnotes. urlhealth is the only one built for general URLs and the only one that explicitly uses the Wayback Machine to separate "used to exist" from "never existed," which is the same method curl-my-footnotes v1 uses. None of these tools judge whether the page's content actually supports the claim attached to the link.

## C. Reference / bibliography verifiers

| Tool | Link | Language / Platform | License | Maintained | Checks | Catches dead / invented / unsupported |
|---|---|---|---|---|---|---|
| Crossref REST API | https://api.crossref.org | REST API (JSON) | Metadata is mostly public domain. Crossref states almost none of it is copyrighted | Yes, live production service | Looks up a DOI or searches by title/author to see if a paper record exists in Crossref's registry | Invented (a citation whose DOI or title has no Crossref record is likely fabricated) |
| habanero | https://github.com/sckott/habanero | Python | MIT | Yes, last commit 2026-09-13 | Python client that wraps Crossref API calls for search, DOI lookup, and journal or funder data | Invented (supports building an invented-reference check on top of Crossref) |
| OpenAlex | https://api.openalex.org (docs: https://help.openalex.org) | REST API (JSON) | Data released under CC0 | Yes, live production service | Looks up a scholarly work by ID, title, or DOI in a large open catalog | Invented |
| Semantic Scholar API | https://api.semanticscholar.org | REST API (JSON) | Governed by Semantic Scholar's API License Agreement. Free tier is rate-limited | Yes, live production service | Searches for a paper and returns metadata to confirm it exists | Invented |
| Open Library API | https://openlibrary.org/developers/api | REST API (JSON, YAML, RDF/XML) | Not confirmed (the developer page points to a separate licensing page not checked directly) | Yes, live production service | Looks up a book by ISBN or search terms to confirm it exists | Invented (for book citations) |
| DOI.org resolver | https://www.doi.org | HTTP redirect service | Not confirmed | Yes, live production service | Resolves a DOI string to its current publisher URL, or fails if the DOI is not registered | Invented (an unregistered DOI fails to resolve) |
| claude-skill-citation-checker | https://github.com/PHY041/claude-skill-citation-checker | Python | Not confirmed (no license field found on the repo) | Last commit 2026-03-22 | A Claude Code skill that verifies entries in a .bib file against CrossRef, Semantic Scholar, and OpenAlex | Invented |

This group is mostly infrastructure, not finished tools. Crossref, OpenAlex, Semantic Scholar, and Open Library are all free lookup APIs that answer "does this record exist," and habanero is a convenience client on top of one of them. They are strong at catching an invented academic citation, because a fabricated paper or book will not show up in the registry. None of them fetch a web page, so none of them can tell a dead link from a live one, and none of them judge claim support. They only cover formal bibliography entries (papers, books, DOIs), not arbitrary web footnotes.

## D. Claim-support / attribution checking

| Tool | Link | Language | License | Maintained | Checks | Catches dead / invented / unsupported |
|---|---|---|---|---|---|---|
| SourceCheckup | https://github.com/kevinwu23/SourceCheckup (paper: https://www.nature.com/articles/s41467-025-58551-6) | Python | Not confirmed (no license field found on the repo) | Last commit 2025-03-12 | An automated pipeline (published in Nature Communications, 2025) that checks whether an LLM's medical answer is actually supported by the sources it cites | Unsupported claim |
| ALCE | https://github.com/princeton-nlp/ALCE | Python | MIT | Last commit 2024-10-09 | A benchmark and methods (EMNLP 2023) for having an LLM generate text with citations, scored on whether each citation supports its sentence | Unsupported claim |
| AttributionBench | https://github.com/OSU-NLP-Group/AttributionBench | Python | Not confirmed (no license field found on the repo) | Last commit 2025-08-18 | A benchmark (ACL 2024 Findings) for testing how well automatic evaluators can decide if a source supports a claim | Unsupported claim |
| RAGAS (faithfulness metric) | https://github.com/vibrantlabsai/ragas (renamed from explodinggradients/ragas, old link still resolves) | Python | Apache-2.0 | Yes, last commit 2026-02-24 | An LLM app evaluation library. Its faithfulness metric checks whether claims in a generated answer are backed up by retrieved context | Unsupported claim |
| MiniCheck | https://github.com/Liyan06/MiniCheck | Python | Apache-2.0 | Last commit 2025-08-27 | A small, fast model (EMNLP 2024) built to fact-check a sentence against a specific grounding document | Unsupported claim |
| SummaC | https://github.com/tingofurro/summac | Python / Jupyter Notebook | Apache-2.0 | Last commit 2025-01-30 | Code and models from a TACL paper that use NLI to check consistency between a summary sentence and its source document | Unsupported claim |

This group does the exact judgment curl-my-footnotes v2 needs: given a claim and a candidate source, decide if the source backs up the claim. All six tools assume the source text is already in hand. None of them fetch a page, none of them tell a dead link from an invented one, and none of them are built around a document's own footnotes as the unit of work. MiniCheck and SummaC are the smallest and cheapest to run locally. RAGAS and ALCE are built around a full evaluation pipeline rather than a single check. This is the group curl-my-footnotes v2 is most likely to borrow a model or a method from, rather than a whole tool.

## E. Commercial or hosted products

| Tool | Link | Language / Platform | License | Maintained | Checks | Catches dead / invented / unsupported |
|---|---|---|---|---|---|---|
| GPTZero Hallucination Detector | https://gptzero.me/hallucination-detector | Hosted SaaS web app | Proprietary, no public source license | Yes, active product page | Scans a document's bibliography for academic writing and flags fabricated sources and poorly supported claims | Invented (primary), unsupported claim (partial, per its own description) |
| Paperpile Citation Checker | https://paperpile.com/blog/citation-checker-hallucinations/ | Hosted SaaS web tool, free | Proprietary, no public source license | Yes, active product page | Checks every entry in a pasted BibTeX file against reference databases and flags ones that look fabricated | Invented |
| Webcite | https://webcite.co/ | Hosted API, paid (free tier plus $20/month and up) | Proprietary, no public source license | Yes, active product with a public pricing page | Fact-checks AI-generated claims against journals, news, and government records, and returns a credibility score | Unsupported claim (primary). Does not explicitly address dead or invented links |
| CiteLLM | https://citellm.com/ | Cloud API or self-hosted, paid ($99/month and up) | Proprietary, no public source license | Yes, active product with a public pricing page | Links values extracted from a document (for example a PDF) back to the exact source location so a person can check them | Unsupported claim, for extracted values against their source document. Not built for web footnotes |

This group treats citation checking as a paid feature, not a script you run yourself. GPTZero and Paperpile target academic bibliographies and focus on catching fabricated references. Webcite and CiteLLM focus on claim support, one for open web claims and one for document extraction. None of them are open source, none of them publish their method in enough detail to reuse directly, and none of them are built as an offline script over a document's own footnotes.

## Gaps this project fills

- No open-source tool found combines dead-link detection, dead-versus-invented classification through the Wayback Machine, and claim-support checking in one script built for a document's own footnotes.
- General link checkers (lychee, markdown-link-check, linkinator, LinkChecker, muffet, broken-link-checker) report dead links only. None of them query an archive to separate "used to exist" from "never existed."
- urlhealth is the closest existing match for the dead-versus-invented split, but it checks a list of URLs, not footnote-and-claim pairs pulled out of a markdown, text, or HTML document.
- The claim-support tools found (SourceCheckup, ALCE, AttributionBench, RAGAS's faithfulness metric, MiniCheck, SummaC) all assume the source text is already available. None of them fetch the page or handle a robot-check or archive failure as its own outcome.
- The commercial products found (GPTZero, Paperpile, Webcite, CiteLLM) are hosted and proprietary. None publish an offline, script-based pipeline over a document's footnotes.

## What we could reuse

- **MiniCheck** as the v2 claim-support judge: it is a small model built specifically for checking a sentence against a grounding document, which is close to curl-my-footnotes's unsupported-claim check. Tradeoff: it is a pretrained model, so it would need testing against footnote wording and citation styles it was not trained on.
- **RAGAS's faithfulness metric** as a reference design: it already pairs an LLM judge with a claim-support check, similar to the v2 plan. Tradeoff: pulling in RAGAS means adding a full evaluation-framework dependency for one metric, which cuts against v1's Python-standard-library-only design.
- **habanero or a direct Crossref API call** for footnotes that cite an academic paper. Tradeoff: it only helps with formal citations that have a DOI or a paper title, not general web footnotes, so it would be a narrow, opt-in addition.
- **urlhealth's Wayback Machine approach** as a design reference rather than a dependency: it solves the same dead-versus-invented problem curl-my-footnotes v1 already solves on its own. Tradeoff: reading its code for method choices is useful, but depending on it directly would break the stdlib-only constraint.
- **AttributionBench's or ALCE's evaluation data** as a starting point for building a test set to measure v2 judge accuracy. Tradeoff: their benchmark examples come from Wikipedia and QA-style datasets, not footnotes, so new footnote-specific test cases would still be needed.

## How this survey was made

This survey was made between 2026-09-16 and 2026-09-17 (the session crossed midnight partway through). Every URL listed above was either opened with a web-fetch tool, confirmed by a direct HTTP status check returning 200, or confirmed through the GitHub API (`gh api repos/<owner>/<repo>`), which was used for every GitHub-hosted tool to pull its real language, license, last-commit date, and star count directly from GitHub's own records.

The following fields are marked "not confirmed" in the tables above because the source page did not state them clearly or the check did not reach the needed page:

- urlhealth: PyPI package metadata lists no license classifier, even though the GitHub repository's license file is MIT.
- hallucinator (gianlucasb): GitHub reports "NOASSERTION" for its license, meaning no license file was detected.
- llm-citation-verifier (DWFlanagan): no license field found on the GitHub repository.
- AttributionBench: no license field found on the GitHub repository.
- SourceCheckup: no license field found on the GitHub repository.
- claude-skill-citation-checker (PHY041): no license field found on the GitHub repository.
- Open Library API: the developer page pointed to a separate licensing page that was not loaded directly, so its exact data license is not confirmed.
- DOI.org resolver: no clear license or terms page was checked, since it functions as a redirect service rather than a data source.
