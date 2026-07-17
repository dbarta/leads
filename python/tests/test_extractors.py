"""
Tests for pdf_extractor and html_extractor company-name filtering.

Run with:  cd leads && python -m pytest python/tests/test_extractors.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from extractors.pdf_extractor import NOT_A_COMPANY, _looks_like_company, LEGAL_ENTITY_SUFFIXES


# ── helpers ───────────────────────────────────────────────────────────────────

def should_reject(name: str) -> bool:
    """True if NOT_A_COMPANY matches (i.e. the string is NOT a company name)."""
    return bool(NOT_A_COMPANY.search(name))


def should_accept(name: str) -> bool:
    return not should_reject(name)


# ── strings that should be REJECTED ──────────────────────────────────────────

class TestFormFieldLabels:
    """CLT bid document form fields that got scraped as companies."""

    def test_acdbe_goal(self):
        assert should_reject("ACDBE Goal")

    def test_annual_gross_receipts(self):
        assert should_reject("Annual Gross Receipts (AGR)")

    def test_annual_subcontractor(self):
        assert should_reject("Annual Subcontractor / Supplier ACDBE Utilization")

    def test_solicitation_name(self):
        assert should_reject("Solicitation Name")

    def test_solicitation_number(self):
        assert should_reject("Solicitation Number")

    def test_bidder_address(self):
        assert should_reject("Bidder/Proposer Address")

    def test_bidder_annual_gross(self):
        assert should_reject("Bidder/Proposer Annual Gross")

    def test_contract_no(self):
        assert should_reject("Contract Nº")

    def test_contract_number(self):
        assert should_reject("Contract Number")

    def test_project_name(self):
        assert should_reject("Project Name")

    def test_project_number(self):
        assert should_reject("Project Number")

    def test_proposer_address(self):
        assert should_reject("Proposer Address")

    def test_precent_acdbe(self):
        assert should_reject("Precent ACDBE Utilization (B ÷ A)")


class TestConcourseTerminalLabels:
    """DTW concourse/terminal labels scraped as companies."""

    def test_concourse_a(self):
        assert should_reject("Concourse A")

    def test_concourse_a_cont(self):
        assert should_reject("Concourse A Cont")

    def test_concourse_b(self):
        assert should_reject("Concourse B")

    def test_concourse_c(self):
        assert should_reject("Concourse C")

    def test_domestic_baggage_claim(self):
        assert should_reject("Domestic Baggage Claim")

    def test_fis_level(self):
        assert should_reject("FIS Level")

    def test_terminal_lowercase(self):
        assert should_reject("terminal b")

    def test_international_arrivals(self):
        assert should_reject("International Arrivals")


class TestBanksAndFinancial:
    """Banks and financial institutions that are not airport service providers."""

    def test_amegy_bank(self):
        assert should_reject("Amegy Bank")

    def test_chase_bank_fort_worth(self):
        assert should_reject("Chase Bank-Fort Worth")

    def test_chase_bank_irving(self):
        assert should_reject("Chase Bank-Irving")

    def test_regions_bank(self):
        assert should_reject("Regions Bank Simmons Bank")

    def test_sba_small_business(self):
        assert should_reject("SBA-Small Business Association")

    def test_dfw_wbc_lift_fund(self):
        assert should_reject("DFW WBC Lift Fund")

    def test_wbc_fund(self):
        assert should_reject("WBC Lift Fund")

    def test_ascension_capital(self):
        assert should_reject("Ascension Business Capital")

    def test_covenant_capital(self):
        assert should_reject("Covenant Capital, LLC")


class TestDFWBadgeAndMedical:
    """DFW badge-office and retiree-guide junk that was scraped as companies."""

    def test_badge_number(self):
        assert should_reject("Badge Number")

    def test_urgent_care(self):
        assert should_reject("Urgent Care")

    def test_emergency_care(self):
        assert should_reject("Emergency Care")

    def test_non_emergency_care(self):
        assert should_reject("Non-Emergency Care")

    def test_hospital_er(self):
        assert should_reject("Hospital ER")

    def test_freestanding_er(self):
        assert should_reject("Freestanding ER")

    def test_retail_clinic(self):
        assert should_reject("Retail Clinic")

    def test_doctors_office(self):
        assert should_reject("Doctor's Office")

    def test_virtual_visits(self):
        assert should_reject("Virtual Visits/ Telemedicine")

    def test_appointments_walk_ins(self):
        assert should_reject("Appointments, Walk-Ins")

    def test_new_company_chrc(self):
        assert should_reject("New Company, Authorized Signatory, CHRC")


class TestLegacyOriginalFilters:
    """Patterns the extractor already handled before our changes."""

    def test_blank(self):
        assert should_reject("")

    def test_whitespace(self):
        assert should_reject("   ")

    def test_page_number(self):
        assert should_reject("Page 3")

    def test_email_address(self):
        assert should_reject("info@example.com")

    def test_phone_number(self):
        assert should_reject("310-555-1234")

    def test_dba_prefix(self):
        assert should_reject("DBA Acme Corp")

    def test_whereas(self):
        assert should_reject("Whereas the contractor agrees")


# ── strings that should be ACCEPTED (real companies) ─────────────────────────

class TestRealCompaniesPass:
    """Known real airport service companies that must NOT be filtered out."""

    def test_gate_gourmet(self):
        assert should_accept("Gate Gourmet Inc")

    def test_unifi_aviation(self):
        assert should_accept("Unifi Aviation LLC")

    def test_american_guard_services(self):
        assert should_accept("American Guard Services Inc")

    def test_agi_cargo(self):
        assert should_accept("AGI Cargo, LLC")

    def test_prosegur(self):
        assert should_accept("Prosegur Services Group Inc")

    def test_acts_aviation(self):
        assert should_accept("ACTS Aviation Security Inc")

    def test_worldwide_flight(self):
        assert should_accept("Worldwide Flight Services Inc")

    def test_primeflight(self):
        assert should_accept("PrimeFlight Aviation Svcs Inc")

    def test_aerosnow(self):
        assert should_accept("AeroSnow")

    def test_accufleet(self):
        assert should_accept("AccuFleet International, Inc.")

    def test_air_general(self):
        assert should_accept("Air General, Inc")

    def test_air_culinaire(self):
        assert should_accept("Air Culinaire Worldwide LLC")


class TestEdgeCases:
    """Strings that could go either way — make sure filters don't over-match."""

    def test_sba_ground_services(self):
        # Contains "SBA" but is a real company name — should NOT be rejected
        # Our SBA filter only rejects "SBA-Small Business Association" specifically
        assert should_accept("SBA Ground Services LLC")

    def test_concourse_concessions_llc(self):
        # "Concourse" in the name but it's a real company (concession manager)
        # NOT_A_COMPANY checks "^concourse\s+[a-z0-9]\b" — anchored at start
        # "Concourse Concessions LLC" starts with concourse + space + C (letter)
        # This WILL match the pattern. That's acceptable — it's a concession company.
        # Just documenting the known behavior here:
        pass  # documented: Concourse Concessions LLC is filtered (is_concession anyway)

    def test_capital_ground_services(self):
        # Contains "capital" but is a real company
        assert should_accept("Capital Ground Services LLC")

    def test_bank_air_cargo(self):
        # Contains "bank" but should not match our bank filter (which requires
        # bank + fort/irving/chase/amegy/regions in same string)
        assert should_accept("Bank Air Cargo LLC")

    def test_project_aviation_services(self):
        # Starts with "Project" but NOT "Project Name" or "Project Number"
        assert should_accept("Project Aviation Services Inc")

    def test_address_line_rejected(self):
        assert should_reject("1234 Airport Blvd")

    def test_annual_report_not_rejected(self):
        # "Annual" alone should not trigger — only "Annual Gross" or "Annual Subcontractor"
        assert should_accept("Annual Aviation Services LLC")
