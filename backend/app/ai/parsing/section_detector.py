from __future__ import annotations
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HeadingCandidate:
    title: str
    level: int
    score: int
    line_index: int
    reasons: list[str]


class SectionDetector:
    CONTINUED_RE = re.compile(r"\s*\(continued\)\s*$", re.I)
    PAGE_RE = re.compile(r"^\d{1,3}$")
    LEADING_INDEX_RE = re.compile(r"^\d{1,3}\s+[A-Za-z]")
    NUMBERED_NOTE_RE = re.compile(r"^(?:C?\d{1,2})\.?\s*[A-Z][A-Za-z].{1,100}$")
    ACTION_ITEM_RE = re.compile(
        r"^\d{1,3}\.?\s+(?:to|that|approve|receive|appoint|re-appoint|re-elect|authorise|authorize)\b",
        re.I,
    )
    ADDRESS_RE = re.compile(
        r"^(?:"
        r"\d+[A-Za-z]?[.,]?\s+"
        r"|(?:unit|suite|level|floor|no\.?|number)\s+\d+"
        r").*"
        r"(?:"
        r"road|street|avenue|way|park|drive|lane|foundry|building|"
        r"postcode|"
        r"[A-Z]{1,2}\d[A-Z0-9]?\s*\d[A-Z]{2}"
        r")\b",
        re.IGNORECASE,
    )
    YEAR_COLUMNS_RE = re.compile(r"\b(?:19|20)\d{2}\b.*\b(?:19|20)\d{2}\b")
    PART_BOUNDARY_RE = re.compile(
        r"^(?:notes? to (?:the )?financial statements|company balance sheet|company statement|consolidated statement|five year financial summary|alternative performance measures)",
        re.I,
    )
    DATE_RE = re.compile(
        r"^(?:(?:for the year ended|as at|at)\s+)?\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+20\d{2}$",
        re.I,
    )
    URL_RE = re.compile(r"(?:www\.|https?://|@)", re.I)
    NUMERIC_RE = re.compile(r"(?:£|\$|€|₹)?\(?-?\d[\d,]*(?:\.\d+)?%?\)?")
    UNITS_RE = re.compile(r"(?:£[’']?000|\$[’']?000|€[’']?000|%|20\d{2})", re.I)
    SHORT_VALID = {
        "revenue",
        "taxation",
        "borrowings",
        "provisions",
        "governance",
        "strategy",
        "cashflow",
        "security",
        "depreciation",
        "cost",
        "profit",
        "equity",
        "inventories",
        "leases",
    }
    GENERIC_MASTHEADS = {
        "goodwin plc",
        "group strategic report",
        "directors’ reports",
        "directors reports",
        "financial statements",
        "notes to the financial statements",
        "independent auditor’s report",
    }
    TABLE_SCHEMA_PATTERNS = [
        re.compile(x, re.I)
        for x in (
            r"\bshare-?\b.*\bcash\b.*\btotal\b",
            r"\byear\b.*\bpercentile\b.*\bpay\b",
            r"\bassets?\b.*\bassets?\b",
            r"^(?:us|uk|eur|gbp)(?:\s+(?:us|uk|eur|gbp))+$",
            r"^assets in$",
            r"^other assets in$",
            r"^year ended$",
            r"^share- cash attributable$",
            r"^trans- based flow",
        )
    ]
    STRUCTURAL = {
        "report",
        "statement",
        "policy",
        "risk",
        "risks",
        "strategy",
        "governance",
        "responsibilities",
        "assets",
        "liabilities",
        "equity",
        "revenue",
        "taxation",
        "borrowings",
        "provisions",
        "investments",
        "remuneration",
        "cash",
        "flows",
        "income",
        "capital",
        "dividends",
        "information",
        "summary",
        "operations",
        "audit",
        "committee",
        "directors",
        "environment",
        "performance",
        "expenses",
        "concern",
        "security",
        "depreciation",
    }

    def build_sections(self, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        repeated = self._repeated(pages)
        sections = []
        active = {}
        known = {}
        current_id = current_title = None
        in_notes = False
        for page in pages:
            no = int(page["page_number"])
            page_text = page.get("text") or ""
            if re.search(r"NOTES? TO (?:THE )?FINANCIAL STATEMENTS", page_text, re.I):
                in_notes = True
            if re.search(
                r"^COMPANY BALANCE SHEET|COMPANY STATEMENT", page_text, re.I | re.M
            ):
                in_notes = False
            heads = self.detect_page_headings(
                page_text, page_no=no, repeated_lines=repeated, in_notes=in_notes
            )
            started = []
            for h in heads:
                base = self.CONTINUED_RE.sub("", h.title).strip()
                key = base.casefold()
                if self.CONTINUED_RE.search(h.title) and key in known:
                    current_id = known[key]
                    current_title = base
                    next(s for s in sections if s["section_id"] == current_id)[
                        "page_end"
                    ] = no
                    continue
                parent = next(
                    (active[l] for l in range(h.level - 1, 0, -1) if l in active), None
                )
                sid = f"SEC-{len(sections)+1:05d}"
                sections.append(
                    {
                        "section_id": sid,
                        "title": base[:500],
                        "heading_level": h.level,
                        "parent_section_id": parent,
                        "page_start": no,
                        "page_end": no,
                        "heading_score": h.score,
                        "heading_reasons": h.reasons,
                        "detection_method": "conservative_text_rules_v3",
                    }
                )
                known[key] = sid
                active[h.level] = sid
                for stale in [x for x in active if x > h.level]:
                    del active[stale]
                current_id = sid
                current_title = base
                started.append(sid)
            page["section_id"] = current_id
            page["section_title"] = current_title
            page["section_ids_started"] = started
            page["heading_candidates"] = [
                {
                    "title": h.title,
                    "level": h.level,
                    "line_index": h.line_index,
                    "score": h.score,
                }
                for h in heads
            ]
        if not sections:
            sections = [
                {
                    "section_id": "SEC-00001",
                    "title": "Document",
                    "heading_level": 1,
                    "parent_section_id": None,
                    "page_start": 1,
                    "page_end": max((p["page_number"] for p in pages), default=1),
                    "heading_score": 0,
                    "heading_reasons": ["fallback"],
                    "detection_method": "fallback",
                }
            ]
            for p in pages:
                p.update(
                    section_id="SEC-00001",
                    section_title="Document",
                    section_ids_started=[],
                )
        self._close_ranges(sections, max((p["page_number"] for p in pages), default=1))
        return sections

    def detect_page_headings(
        self, text, *, page_no=1, repeated_lines=None, in_notes=False
    ):
        repeated_lines = repeated_lines or set()
        lines = [self.clean(x) for x in text.splitlines() if self.clean(x)]
        if sum(bool(self.LEADING_INDEX_RE.match(x)) for x in lines[:30]) >= 4 or any(
            x.casefold().replace(" ", "") == "index" for x in lines[:5]
        ):
            return []
        out = []
        for i, line in enumerate(lines[:30]):
            c = self._score(line, i, repeated_lines, in_notes)
            if c:
                out.append(c)
        majors = [x for x in out if x.level == 1]
        subs = [x for x in out if x.level == 2]
        chosen = []
        if majors:
            chosen.append(max(majors, key=lambda x: (x.score, -x.line_index)))
        for x in sorted(subs, key=lambda x: x.line_index):
            if len(chosen) >= 3:
                break
            if x.title.casefold() not in {y.title.casefold() for y in chosen}:
                chosen.append(x)
        return sorted(chosen, key=lambda x: x.line_index)

    def choose_table_context(self, page, table):
        headings = page.get("heading_candidates") or []
        meaningful = [h for h in headings if not self._table_schema(h["title"])]
        if meaningful:
            numbered = [
                h for h in meaningful if self.NUMBERED_NOTE_RE.match(h["title"])
            ]
            pick = max(
                numbered or meaningful, key=lambda h: (h["score"], -h["line_index"])
            )
            return page.get("section_id"), pick["title"]
        return page.get("section_id"), page.get("section_title")

    def _score(self, line, index, repeated, in_notes=False):
        words = line.split()
        lower = line.casefold()
        alpha = [c for c in line if c.isalpha()]
        if (
            not line
            or self.PAGE_RE.fullmatch(line)
            or self.URL_RE.search(line)
            or self.DATE_RE.fullmatch(line)
            or self.LEADING_INDEX_RE.match(line)
        ):
            return None
        if (
            self.ACTION_ITEM_RE.match(line)
            or self.ADDRESS_RE.match(line)
            or self.YEAR_COLUMNS_RE.search(line)
        ):
            return None
        if (
            lower in self.GENERIC_MASTHEADS
            or lower in repeated
            or self._table_schema(line)
        ):
            return None
        if len(words) > 14 or len(line) > 145:
            return None
        numbered = bool(self.NUMBERED_NOTE_RE.match(line))
        meaningful = [w for w in words if len(re.sub("[^A-Za-z]", "", w)) >= 3]
        if len(meaningful) < 3 and lower not in self.SHORT_VALID and not numbered:
            return None
        numeric = len(self.NUMERIC_RE.findall(line))
        units = len(self.UNITS_RE.findall(line))
        digit = sum(c.isdigit() for c in line) / max(len(line), 1)
        if not numbered and (numeric >= 2 or units >= 2 or digit > 0.22):
            return None
        if line.endswith((".", ",", ";")):
            return None
        if words and words[-1].casefold() in {"in", "of", "from", "to", "and", "or"}:
            return None
        short_ratio = sum(len(re.sub("[^A-Za-z]", "", w)) < 4 for w in words) / max(
            len(words), 1
        )
        if short_ratio > 0.55 and not numbered:
            return None
        upper = sum(c.isupper() for c in alpha) / max(len(alpha), 1)
        struct = sum(w.strip("():/-").casefold() in self.STRUCTURAL for w in words)
        score = 0
        reasons = []
        if index <= 10:
            score += 2
            reasons.append("near_start")
        if 1 <= len(words) <= 8:
            score += 2
            reasons.append("short")
        elif len(words) <= 12:
            score += 1
        if upper >= 0.82:
            score += 3
            reasons.append("uppercase")
        elif struct:
            score += 2
            reasons.append("structural")
        if numbered:
            score += 4
            reasons.append("numbered_note")
        if self.CONTINUED_RE.search(line):
            score += 2
        if line[0].islower() or lower.startswith(
            ("the ", "this ", "these ", "our ", "and ", "of ", "in ", "to ")
        ):
            score -= 3
        if score < 6:
            return None
        level = 1 if upper >= 0.82 and len(words) <= 10 else 2
        if in_notes and numbered:
            level = 1
        if self.PART_BOUNDARY_RE.match(line):
            level = 1
        return HeadingCandidate(line, level, score, index, reasons)

    def _table_schema(self, line):
        return any(p.search(line.strip()) for p in self.TABLE_SCHEMA_PATTERNS)

    def _repeated(self, pages):
        c = Counter()
        for p in pages:
            for x in [self.clean(v) for v in (p.get("text") or "").splitlines()[:8]]:
                if x and len(x) <= 90:
                    c[x.casefold()] += 1
        return {x for x, n in c.items() if n >= 3}

    @staticmethod
    def _close_ranges(sections, last):
        for i, s in enumerate(sections):
            end = last
            for later in sections[i + 1 :]:
                if later["heading_level"] <= s["heading_level"]:
                    end = max(s["page_start"], later["page_start"] - 1)
                    break
            s["page_end"] = max(s["page_end"], end)

    @staticmethod
    def clean(v):
        return re.sub(r"\s+", " ", v or "").strip()
