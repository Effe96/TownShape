from town_relationships.overlap import dates_overlap


def test_overlapping_ranges_return_the_intersection():
    assert dates_overlap("1300-01-01", "1300-06-01", "1300-03-01", "1300-09-01") == ("1300-03-01", "1300-06-01")


def test_non_overlapping_ranges_return_none():
    assert dates_overlap("1290-01-01", "1291-01-01", "1300-01-01", "1301-01-01") is None


def test_open_ended_range_treated_as_ongoing():
    assert dates_overlap("1300-01-01", None, "1300-06-01", "1300-12-01") == ("1300-06-01", "1300-12-01")


def test_both_open_ended_has_no_overlap_end():
    assert dates_overlap("1300-01-01", None, "1300-06-01", None) == ("1300-06-01", None)
