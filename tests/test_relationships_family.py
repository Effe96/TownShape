from datetime import date

from town_relationships.family import derive_family_relationships

REFERENCE_DATE = date(1300, 1, 1)


def _resident(resident_id, household_id, age):
    birth_year = REFERENCE_DATE.year - age
    return {"id": resident_id, "household_id": household_id, "birth_date": date(birth_year, 1, 1).isoformat()}


def test_two_adult_household_with_children_gets_spouse_parent_and_sibling():
    residents = [
        _resident(1, 100, 40), _resident(2, 100, 38),
        _resident(3, 100, 10), _resident(4, 100, 8),
    ]
    relationships = derive_family_relationships(residents, [], REFERENCE_DATE)

    triples = {(r["resident_a_id"], r["resident_b_id"], r["relationship_type"]) for r in relationships}
    assert (1, 2, "spouse") in triples
    assert (1, 3, "parent") in triples
    assert (2, 3, "parent") in triples
    assert (1, 4, "parent") in triples
    assert (2, 4, "parent") in triples
    assert (3, 4, "sibling") in triples
    assert "household_member" not in {r["relationship_type"] for r in relationships}


def test_three_adult_household_extra_adult_gets_household_member_not_a_role():
    residents = [_resident(1, 100, 45), _resident(2, 100, 43), _resident(3, 100, 20)]
    relationships = derive_family_relationships(residents, [], REFERENCE_DATE)

    by_type = {}
    for r in relationships:
        by_type.setdefault(r["relationship_type"], set()).add((r["resident_a_id"], r["resident_b_id"]))

    assert by_type.get("spouse") == {(1, 2)}
    assert by_type.get("household_member") == {(1, 3), (2, 3)}
    assert "parent" not in by_type


def test_single_resident_household_produces_no_relationships():
    residents = [_resident(1, 100, 30)]
    assert derive_family_relationships(residents, [], REFERENCE_DATE) == []


def test_single_adult_household_still_tags_parent_but_no_spouse():
    residents = [_resident(1, 100, 30), _resident(2, 100, 5)]
    relationships = derive_family_relationships(residents, [], REFERENCE_DATE)
    triples = {(r["resident_a_id"], r["resident_b_id"], r["relationship_type"]) for r in relationships}
    assert triples == {(1, 2, "parent")}


def test_birth_record_overrides_household_heuristic_for_parentage():
    residents = [
        _resident(1, 100, 45), _resident(2, 100, 43), _resident(3, 100, 22), _resident(4, 100, 0),
    ]
    births = [{"child_resident_id": 4, "mother_resident_id": 3, "father_resident_id": None}]
    relationships = derive_family_relationships(residents, births, REFERENCE_DATE)

    by_type = {}
    for r in relationships:
        by_type.setdefault(r["relationship_type"], set()).add((r["resident_a_id"], r["resident_b_id"]))

    # The heuristic would have used the first two adults (1, 2); the real birth
    # record says the mother is adult #3 -- the exact record must win.
    assert by_type.get("parent") == {(3, 4)}

    # Verify that (3, 4) does NOT appear as household_member (no contradictory relationships)
    household_member_pairs = by_type.get("household_member", set())
    assert (3, 4) not in household_member_pairs and (4, 3) not in household_member_pairs
