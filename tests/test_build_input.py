from settlemaker_bridge.build_input import build_azgaar_burg_input


def test_no_port_omits_harbour_size():
    burg = build_azgaar_burg_input("s", 5000, has_port=False)
    assert burg["port"] is False
    assert "harbourSize" not in burg


def test_port_sets_harbour_size():
    # Regression guard for a real bug: settlemaker's placeHarbour() (see
    # node_modules/settlemaker/dist/generator/model.js) no-ops unless
    # params.harbourSize is set -- port alone was never enough, and
    # AzgaarBurgInput's own harbourSize is honoured only when port is ALSO
    # true (dist/input/azgaar-input.js). Without this, has_port=True never
    # actually placed a harbour ward, confirmed directly: a sweep of 14
    # seed/population combinations with has_port=True produced zero
    # 'harbour' wards; adding harbourSize alone (nothing else changed) made
    # one appear on the same seed.
    burg = build_azgaar_burg_input("s", 5000, has_port=True)
    assert burg["harbourSize"] in ("large", "small")


def test_port_harbour_size_is_large_for_a_big_population():
    # Doc comment on AzgaarBurgInput.harbourSize: "'large' for major sea
    # routes + big pop, 'small' otherwise". TownShape has no "major sea
    # routes" concept, so this maps purely off population, using
    # settlemaker's own DEFAULT_CORE_CAPACITY (10,000, azgaar-input.d.ts) as
    # the existing "big city" line rather than inventing a new threshold.
    small = build_azgaar_burg_input("s", 9999, has_port=True)
    large = build_azgaar_burg_input("s", 10000, has_port=True)
    assert small["harbourSize"] == "small"
    assert large["harbourSize"] == "large"
