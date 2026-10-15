"""Finding the master a distributor's spelling means, without an alias per spelling.

A name from a file is tried against the masters in this order, and the first
level that points at exactly one master wins. A level that points at two
different masters is not used: the name goes on to the next, and if nothing is
sure it is asked about (with suggestions) rather than guessed.

1. exact      the master's name or one of its aliases, punctuation and case
              ignored (services/names.norm)
2. history    a spelling seen before: MAPPING_MASTER and MAPPING_MASTER_MID keep
              each row's CUSTOMER_NAME / PRODUCT_NAME as the file had it beside
              the CUSTOMER_ID / PRODUCT_ID it was. The old system's 100,000 rows
              teach the app every spelling it met, and each conversion adds its
              own. The distributor's own history counts first.
3. chosen     a spelling someone matched by hand on the Convert screen
              (NAME_MATCH), for names history has not met yet
4. cleaned    the same once company words and plurals are taken out:
              "Ashma Medico Pvt ltd" = "ASHMA MEDICO"; for products the tablet
              and capsule words, and one spelling for SYP / SYR / SYRUP, GM / G …:
              "STEMETIL 5MG TAB" = "STEMETIL 5 MG"
5. shortened  every word of one is the start of the other's word in the same
              place, the first word whole, and no other master begins the same way: "Baibhav Binayak Pharmaceutic" =
              "BAIBHAV & BINAYAK PHARMACEUTICALS", "KAMANA MEDICINE DIST KTM" =
              "KAMANA MEDICINE DISTRIBUTOR" (a trailing town code is allowed)
6. similar    nearly the same letters (difflib ratio 0.90 or more, and clearly
              closer than the next master by 0.06; for products 0.92 and 0.08)

From level 4 on, numbers have to agree: for a customer all of them; for a
product its strength, the first number, while a pack size (10S, 20 S) may be on
one side only — UDILIV 150MG is never UDILIV 300MG. And a product's form and
variant words have to agree: APNICAF INJ is not APNICAF ORAL, ROVAMYCIN not
ROVAMYCIN FORTE, STEMETIL not STEMETIL MD.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from itertools import takewhile
from difflib import SequenceMatcher

from .names import norm

COMPANY_WORDS = {"PVT", "PRIVATE", "PRIV", "PVTLTD", "LTD", "LIMITED", "P", "PL", "PLTD", "CO", "COMPANY",
                 "INC", "LLP", "AND", "THE", "M", "S", "MS", "MESSRS"}
# A product's tablet / capsule words say nothing (STEMETIL 5MG TAB is STEMETIL
# 5MG), nor do units beside their number (BRUFEN 600 is BRUFEN 600 MG) or the
# packing (DIGENE GEL PET 200 ML).
PRODUCT_WORDS = {"S", "TAB", "TABS", "TABLET", "TABLETS", "CAP", "CAPS", "CAPSULE", "CAPSULES",
                 "MG", "ML", "G", "MCG", "IU", "PET", "BOTTLE", "BOTT", "BTL", "STRIP", "STRIPS",
                 "BOX", "PACK", "PKT", "JAR", "TUBE"}
# One word for one thing.
PRODUCT_SAME = {"SYP": "SYRUP", "SYR": "SYRUP", "INJECTION": "INJ", "SUSPENSION": "SUSP",
                "SOLUTION": "SOL", "OINTMENT": "OINT", "GMS": "G", "GM": "G", "GRAM": "G",
                "MLS": "ML", "SACHETS": "SACHET", "DROPS": "DROP"}
# But these make it another product, so the two names have to agree on them:
# APNICAF INJ is not APNICAF ORAL, ROVAMYCIN not ROVAMYCIN FORTE, STEMETIL not
# STEMETIL MD.
PRODUCT_KINDS = {"SYRUP", "INJ", "SUSP", "SOL", "ORAL", "DROP", "GEL", "CREAM", "OINT", "ENEMA",
                 "SACHET", "LOTION", "SPRAY", "POWDER", "MD", "DT", "ER", "SR", "XR", "CR", "FORTE",
                 "PLUS", "DS", "KID", "PAED", "JUNIOR", "NASAL", "EYE", "EAR", "VAGINAL", "RETARD",
                 "MONO", "CONTI", "INFUSION", "VIAL", "INSTITUTION", "PLAIN"}

LEVELS = ("exact", "history", "chosen", "cleaned", "shortened", "similar")


def _is_num(w: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", w))


def _pack_out(ws: list[str]) -> list[str]:
    """A product's pack size goes: "15S", "15 S", 30"S, "5X10S", "1X28". Then a
    part written twice once ("225ML 225ML", "15 S 15S")."""
    out, i = [], 0
    while i < len(ws):
        if i + 2 < len(ws) and _is_num(ws[i]) and ws[i + 1] == "X" and _is_num(ws[i + 2]):
            i += 3                                   # 5 X 10 (S): a pack
            if i < len(ws) and ws[i] == "S":
                i += 1
            continue
        if i + 1 < len(ws) and _is_num(ws[i]) and ws[i + 1] == "S":
            i += 2                                   # 15 S: a pack of fifteen
            continue
        out.append(ws[i])
        i += 1
    for size in (3, 2, 1):                           # 225 ML 225 ML -> 225 ML
        j = 0
        while j + 2 * size <= len(out):
            if out[j:j + size] == out[j + size:j + 2 * size]:
                del out[j + size:j + 2 * size]
            else:
                j += 1
    return out


def words(name: str | None, kind: str) -> tuple[str, ...]:
    """The words that tell names apart: upper case, numbers (decimals kept, 37.5)
    apart from letters ("150MG" -> 150, MG), company or tablet words out,
    plurals singular; for a product its pack size out too."""
    if not name:
        return ()
    raw = re.findall(r"\d+(?:\.\d+)?|[A-Z]+", str(name).upper().replace("&", " "))
    if kind == "product":
        raw = _pack_out(raw)
    drop = COMPANY_WORDS if kind == "customer" else PRODUCT_WORDS
    out = []
    for w in raw:
        if kind == "product":
            w = PRODUCT_SAME.get(w, w)
        if not w or w in drop:
            continue
        if len(w) > 3 and w.endswith("S") and not w.endswith("SS") and not _is_num(w):
            w = w[:-1]
        out.append(w)
    return tuple(out)


def same_numbers(kind: str, a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """Customers: the same numbers. Products: the same strength (the first
    number), and one may carry more (a pack size: 10S, 20 S) — DUPHASTON 10 MG
    20 S is DUPHASTON 10MG; DUPHASTON 10 is never 20, UDILIV 150 never 300."""
    na, nb = numbers(a), numbers(b)
    if kind == "customer":
        return na == nb
    if not na or not nb:
        return True
    return na[0] == nb[0] and (set(na) <= set(nb) or set(nb) <= set(na))


def same_kind(kind: str, a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """A product's form and variant words agree (SYRUP, INJ, MD, FORTE …)."""
    if kind != "product":
        return True
    return {w for w in a if w in PRODUCT_KINDS} == {w for w in b if w in PRODUCT_KINDS}


def agree(a: tuple[str, ...], b: tuple[str, ...], n: int) -> bool:
    """The first n words of a and b agree: the first the same, each other the
    start of the other's. Used to see whether a second master begins the way
    the matched one does ("MEDICHEM PHARMA" and "MEDICHEM PHARMA JKP")."""
    if len(a) < n or len(b) < n or not n or a[0] != b[0]:
        return False
    return all(x.startswith(y) or y.startswith(x) for x, y in zip(a[:n], b[:n]))


def numbers(ws: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(w for w in ws if _is_num(w))


def shortened(a: tuple[str, ...], b: tuple[str, ...], any_length: bool = False) -> bool:
    """a and b name the same thing, one written shorter: word for word, each the
    start of the other (the first word whole), at least two words compared, and
    the longer may run on by one word (a town code). any_length: by any number
    of words, to see whether another master begins the same way."""
    if len(a) < 2 or len(b) < 2 or a[0] != b[0]:
        return False
    if not any_length and abs(len(a) - len(b)) > 1:
        return False
    n = min(len(a), len(b))
    if max(sum(len(w) for w in a[:n]), sum(len(w) for w in b[:n])) < 8:
        return False
    return all(x.startswith(y) or y.startswith(x) for x, y in zip(a[:n], b[:n]))


class Matcher:
    """One kind (customer or product). Fed with what the masters, the history and
    the hand-chosen matches say; find() answers (id, level) or (None, None)."""

    def __init__(self, kind: str):
        self.kind = kind
        self.exact: dict[str, set[int]] = defaultdict(set)
        self.history: dict[str, Counter] = defaultdict(Counter)       # norm -> Counter(id: rows)
        self.history_own: dict[str, Counter] = defaultdict(Counter)   # this distributor's
        self.chosen: dict[str, int] = {}
        self.spellings: dict[tuple, set[int]] = defaultdict(set)      # words -> ids
        self.names: dict[int, str] = {}
        self._by_first: dict[str, list] | None = None

    # ------------------------------------------------------------ feeding
    def add_master(self, mid: int, *names):
        for i, n in enumerate(names):
            if not n:
                continue
            if i == 0:
                self.names[mid] = str(n)
            k = norm(n)
            if k:
                self.exact[k].add(mid)
            w = words(n, self.kind)
            if w:
                self.spellings[w].add(mid)
        self._by_first = None

    def add_history(self, name, mid, rows, own: bool):
        k = norm(name)
        if not k or mid is None:
            return
        self.history[k][mid] += rows
        if own:
            self.history_own[k][mid] += rows
        w = words(name, self.kind)
        if w and mid in self.names:          # only towards masters that still exist
            self.spellings[w].add(mid)
        self._by_first = None

    def add_chosen(self, name, mid):
        k = norm(name)
        if k:
            self.chosen[k] = mid

    # ------------------------------------------------------------ finding
    @staticmethod
    def _one(ids) -> int | None:
        ids = set(ids)
        return ids.pop() if len(ids) == 1 else None

    def _from_history(self, k: str) -> int | None:
        for book in (self.history_own, self.history):
            c = book.get(k)
            if c:
                (top, n), *rest = c.most_common()
                if top in self.names and (not rest or n >= 0.8 * sum(c.values())):
                    return top
        return None

    def _first(self):
        if self._by_first is None:
            self._by_first = defaultdict(list)
            for w, ids in self.spellings.items():
                self._by_first[w[0][:3]].append((w, ids))
        return self._by_first

    def find(self, *names) -> tuple[int | None, str | None]:
        names = [n for n in names if n]
        for n in names:                                         # 1. exact
            hit = self.exact.get(norm(n))
            if hit:
                one = self._one(hit)
                if one is not None:
                    return one, "exact"
        for n in names:                                         # 2. history
            one = self._from_history(norm(n))
            if one is not None:
                return one, "history"
        for n in names:                                         # 3. chosen by hand
            one = self.chosen.get(norm(n))
            if one is not None and one in self.names:
                return one, "chosen"
        for n in names:
            w = words(n, self.kind)
            if not w:
                continue
            one = self._one(self.spellings.get(w, ()))          # 4. cleaned
            if one is not None:
                return one, "cleaned"
            near = [(sw, si) for sw, si in self._first().get(w[0][:3], [])
                    if same_numbers(self.kind, w, sw) and same_kind(self.kind, w, sw)]
            hits = [(sw, si) for sw, si in near if shortened(w, sw)]
            one = self._one(i for _, si in hits for i in si)    # 5. shortened, and no
            if one is not None:                                 #    other master begins the
                n = min([len(w)] + [len(sw) for sw, _ in hits]) #    same way over the words
                alike = {i for sw, si in near if agree(w, sw, n) for i in si}   # compared
                if alike == {one}:
                    return one, "shortened"
            # 6. similar: products a little stricter, as one letter can be another product
            cut, gap = (0.90, 0.06) if self.kind == "customer" else (0.92, 0.08)
            best = self._ranked(w, near)
            if best and best[0][0] >= cut and (len(best) == 1 or best[0][0] - best[1][0] >= gap):
                top = best[0][1]
                # the words it has whole in common with the master; if another
                # master has them too, it is not sure ("MEDICHEM PHARMA JNK")
                same = max((sum(1 for _ in takewhile(lambda p: p[0] == p[1], zip(w, sw)))
                            for sw, si in near if top in si), default=0)
                alike = {i for sw, si in near if same and agree(w, sw, same) for i in si}
                if alike <= {top}:
                    return top, "similar"
        return None, None

    def _ranked(self, w, near) -> list[tuple[float, int]]:
        """(score, id), best first, one entry per master."""
        s = " ".join(w)
        score: dict[int, float] = {}
        for sw, ids in near:
            r = SequenceMatcher(None, s, " ".join(sw)).ratio()
            for i in ids:
                if r > score.get(i, 0):
                    score[i] = r
        return sorted(((r, i) for i, r in score.items()), reverse=True)

    def suggest(self, name, k: int = 3) -> list[dict]:
        """The closest masters, for a person to choose from."""
        w = words(name, self.kind)
        if not w:
            return []
        pool = self._first().get(w[0][:3], []) or [x for v in self._first().values() for x in v]
        ranked = self._ranked(w, pool)[:k]
        return [{"id": i, "name": self.names.get(i, str(i)), "score": round(r, 2)} for r, i in ranked]
