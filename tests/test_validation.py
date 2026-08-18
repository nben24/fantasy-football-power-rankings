import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import data_validation, memory


def test_duplicate_team_name_flagged():
    """Scenario 9: duplicate team names in a single extraction should be flagged."""
    extracted = {
        "teams": [{"name": "Gridiron Gang"}, {"name": "Gridiron Gang"}],
        "matchups": [],
        "uncertain_notes": [],
    }
    warnings = data_validation.validate_extracted_data(extracted)
    assert any("more than once" in w for w in warnings)


def test_missing_score_flagged():
    extracted = {
        "teams": [{"name": "A"}, {"name": "B"}],
        "matchups": [{"team_a": "A", "team_b": "B", "score_a": 100.0, "score_b": None}],
        "uncertain_notes": [],
    }
    warnings = data_validation.validate_extracted_data(extracted)
    assert any("Missing a score" in w for w in warnings)


def test_matchup_team_not_in_standings_flagged():
    extracted = {
        "teams": [{"name": "A"}, {"name": "B"}],
        "matchups": [{"team_a": "A", "team_b": "Ghost Team", "score_a": 100.0, "score_b": 90.0}],
        "uncertain_notes": [],
    }
    warnings = data_validation.validate_extracted_data(extracted)
    assert any("Ghost Team" in w for w in warnings)


def test_uncertain_notes_surfaced_as_warnings():
    extracted = {
        "teams": [{"name": "A"}],
        "matchups": [],
        "uncertain_notes": ["Team A score may be 142.8 or 148.8"],
    }
    warnings = data_validation.validate_extracted_data(extracted)
    assert any("142.8" in w for w in warnings)


def test_normalize_fuzzy_matches_existing_team_name():
    """OCR noise ('Gridiron Gang ' vs 'Gridiron Gang') shouldn't create a duplicate team."""
    league = {"team_aliases": {}, "weeks": {"1": {"teams": [{"name": "Gridiron Gang"}]}}}
    normalized = memory.normalize_team_name(league, "Gridiron Gan")  # missing a char, OCR-style
    assert normalized == "Gridiron Gang"


def test_normalize_matches_espn_ellipsis_truncation():
    """Real bug: ESPN truncates long team names with '...' in some screenshot
    crops but not others. 'EL SUCIO DE LOS...' vs 'EL SUCIO DE LOS SUCIOS' has
    a fuzzy-match ratio of only 0.75 (below the 0.82 cutoff), so without this
    check it gets treated as a brand-new team -- silently resetting rank
    history and producing false claims like 'first time at #1 all season.'
    Canonicalizes to the ALREADY-established name so prior weeks' stored data
    (which used the truncated form) keeps matching by exact string."""
    league = {"team_aliases": {}, "weeks": {"9": {"teams": [{"name": "EL SUCIO DE LOS..."}]}}}
    normalized = memory.normalize_team_name(league, "EL SUCIO DE LOS SUCIOS")
    assert normalized == "EL SUCIO DE LOS..."

    # And the reverse direction: full name seen first, truncated version later.
    league2 = {"team_aliases": {}, "weeks": {"9": {"teams": [{"name": "EL SUCIO DE LOS SUCIOS"}]}}}
    normalized2 = memory.normalize_team_name(league2, "EL SUCIO DE LOS...")
    assert normalized2 == "EL SUCIO DE LOS SUCIOS"


def test_normalize_ellipsis_truncation_requires_real_ellipsis_marker():
    """Two genuinely different teams shouldn't merge just because one name
    happens to be a prefix of another -- only ESPN's literal '...' marker
    should trigger this, not a generic prefix relationship."""
    league = {"team_aliases": {}, "weeks": {"1": {"teams": [{"name": "The Warriors United"}]}}}
    normalized = memory.normalize_team_name(league, "The Warriors")
    assert normalized == "The Warriors"  # NOT merged with "The Warriors United"


def test_normalize_leaves_genuinely_new_team_alone():
    league = {"team_aliases": {}, "weeks": {"1": {"teams": [{"name": "Gridiron Gang"}]}}}
    normalized = memory.normalize_team_name(league, "Totally Different Squad")
    assert normalized == "Totally Different Squad"
