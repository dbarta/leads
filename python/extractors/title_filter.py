"""
Title filtering for contact discovery.

Logic (in order):
  1. If title contains a TARGET keyword → always keep (decision-maker)
  2. If title contains an EXCLUDE keyword → discard (too junior / operational)
  3. Otherwise → keep (let human review)
"""
from __future__ import annotations
import re

# Decision-maker titles — if any of these appear, always keep the contact
TARGET_PATTERNS = [
    r"\bowner\b", r"\bco-owner\b", r"\bpresident\b", r"\bceo\b",
    r"\bchief executive\b", r"\bfounder\b", r"\bco-founder\b",
    r"\bprincipal\b", r"\bmanaging member\b", r"\bmanaging partner\b",
    r"\bmanaging director\b", r"\bgeneral manager\b",
    r"\bcfo\b", r"\bchief financial\b", r"\bcontroller\b", r"\bcomptroller\b",
    r"\bfinance director\b", r"\bdirector of finance\b",
    r"\bvp\b", r"\bvice president\b",
    r"\bdirector\b",  # broad but filtered by EXCLUDE below if too junior
    r"\brisk manager\b", r"\bchief risk\b", r"\binsurance manager\b",
    r"\bchief operating\b", r"\bcoo\b",
]

# Operational/junior titles — if matched AND no TARGET match, discard
EXCLUDE_PATTERNS = [
    # Cleaning / janitorial
    r"\bjanitor\b", r"\bjanitorial\b", r"\bcustodian\b", r"\bcustodial\b",
    r"\bcleaner\b", r"\bcleaning\s+crew\b", r"\bcleaning\s+staff\b",
    # Ground / ramp operations (line-level)
    r"\bramp\s+agent\b", r"\bramp\s+operator\b", r"\bramp\s+lead\b",
    r"\bramp\s+supervisor\b", r"\bline\s+service\s+tech", r"\bground\s+agent\b",
    r"\bskycap\b", r"\bwheelchair\s+agent\b",
    # Baggage
    r"\bbaggage\s+handler\b", r"\bbaggage\s+agent\b", r"\bbaggage\s+claim\b",
    # Mechanics / technicians (line-level; director/manager variants kept by TARGET)
    r"\bmechanic\b", r"\bline\s+technician\b", r"\bavionics\s+tech",
    # Supervisors / leads (line-level)
    r"\bshift\s+supervisor\b", r"\bshift\s+lead\b", r"\bteam\s+lead\b",
    r"\bcrew\s+chief\b", r"\bforeman\b",
    # Administrative / support (non-decision)
    r"\bdispatcher\b", r"\bscheduler\b", r"\bcoordinator\b",
    r"\bspecialist\b", r"\bassociate\b",
    r"\bgate\s+agent\b", r"\bcustomer\s+service\s+agent\b",
    r"\bpassenger\s+service\s+agent\b",
    # Accounting clerks (keep controllers/CFOs via TARGET)
    r"\baccounts\s+payable\b", r"\baccounts\s+receivable\b",
    r"\bbookkeeper\b", r"\bpayroll\s+clerk\b",
]

# Compile once
_TARGET = [re.compile(p, re.IGNORECASE) for p in TARGET_PATTERNS]
_EXCLUDE = [re.compile(p, re.IGNORECASE) for p in EXCLUDE_PATTERNS]


def is_target_title(title: str) -> bool:
    """Return True if the title matches a decision-maker pattern."""
    t = (title or "").strip()
    return any(p.search(t) for p in _TARGET)


def is_excluded_title(title: str) -> bool:
    """Return True if the title is clearly too junior — should be discarded."""
    t = (title or "").strip()
    if is_target_title(t):
        return False  # TARGET always wins
    return any(p.search(t) for p in _EXCLUDE)


def should_keep_contact(title: str) -> bool:
    """
    Return True if the contact should be kept.
    - Blank title: keep (can't tell, let human decide)
    - Target title: keep
    - Excluded title: discard
    - Unknown title: keep
    """
    t = (title or "").strip()
    if not t:
        return True
    if is_target_title(t):
        return True
    if is_excluded_title(t):
        return False
    return True  # unknown — keep for human review


def filter_contacts(contacts: list[dict], title_key: str = "title") -> tuple[list[dict], list[dict]]:
    """
    Split contacts into (kept, excluded).
    Each contact dict must have a key matching title_key.
    """
    kept, excluded = [], []
    for c in contacts:
        if should_keep_contact(c.get(title_key, "")):
            kept.append(c)
        else:
            excluded.append(c)
    return kept, excluded
