from dataclasses import replace
from datetime import date

from tools.nifty200_pit import build_public_dataset as builder
from tools.nifty200_pit.models import Observation, SourceRecord


def _verified_bata_sources(tmp_path, monkeypatch):
    hashes = [
        "19165b2821beacbd70053fce918555230a5966c558685dcb4dcac658e1141692",
        "5bf12c923a4fdae35c64b42db565f61869e6ab9b76cfe6b78a47a7d6fba5b275",
        "1e4904294f249df9baad33639503a04ce51e45df5940eabeb27e01b7e49ec6e2",
    ]
    sources = []
    for digest in hashes:
        path = tmp_path / digest
        path.write_bytes(b"test-only evidence")
        sources.append(SourceRecord("official", str(path), digest, "now"))
    monkeypatch.setattr(builder, "sha256_file", lambda path: path.name)
    monkeypatch.setattr(builder, "parse_bhavcopy_identities", lambda source: [{
        "symbol": "BATAINDIA", "series": "EQ",
        "isin": "INE176A01010" if source.source_sha256 == hashes[1] else "INE176A01028",
        "snapshot_date": "2015-10-07" if source.source_sha256 == hashes[1] else "2015-10-08",
    }])
    return sources


def test_stock_split_links_durable_identity_without_changing_isin_dates_or_membership(tmp_path, monkeypatch):
    sources = _verified_bata_sources(tmp_path, monkeypatch)
    old = Observation(symbol="BATAINDIA", isin="INE176A01010", instrument_id="NSE-ISIN:INE176A01010",
                      action="ADD", effective_date=date(2012, 4, 27), source_sha256="entry", raw_text="source entry")
    new = replace(old, isin="INE176A01028", instrument_id="NSE-ISIN:INE176A01028",
                  action="DROP", effective_date=date(2024, 3, 28), source_sha256="exit")
    master = [{"symbol": new.symbol, "isin": new.isin, "instrument_id": new.instrument_id,
               "valid_from": "2015-10-08", "source_sha256": "reference", "confidence": "CERTIFIED"}]
    rows, mapped, aliases, audit = builder._apply_documented_isin_continuity([old, new], master, master, sources)
    assert rows == [old, replace(new, instrument_id=old.instrument_id)]
    assert mapped[0]["instrument_id"] == old.instrument_id
    assert mapped[0]["identity_reference_instrument_id"] == new.instrument_id
    assert mapped[0]["isin"] == new.isin and mapped[0]["valid_from"] == "2015-10-08"
    assert aliases == mapped
    assert len(audit["links"]) == 1
    assert len(audit["observations"]) == 1
    assert audit["observations"][0]["new_instrument_id"] == old.instrument_id
    assert audit["links"][0]["independent_qa"] == "NOT_ASSERTED"
    assert master[0]["instrument_id"] == new.instrument_id


def test_continuity_requires_all_three_first_party_sources_and_matching_reference_rows(tmp_path, monkeypatch):
    sources = _verified_bata_sources(tmp_path, monkeypatch)
    event = Observation(symbol="BATAINDIA", isin="INE176A01028", instrument_id="NSE-ISIN:INE176A01028")
    for evidence in (sources[:-1], [replace(sources[0], source_tier="B1"), *sources[1:]]):
        rows, _, _, audit = builder._apply_documented_isin_continuity([event], [], [], evidence)
        assert rows == [event] and audit["links"] == []
    monkeypatch.setattr(builder, "sha256_file", lambda _: "wrong")
    assert builder._apply_documented_isin_continuity([event], [], [], sources)[0] == [event]
    monkeypatch.setattr(builder, "sha256_file", lambda path: path.name)
    monkeypatch.setattr(builder, "parse_bhavcopy_identities", lambda _: [{
        "symbol": "BATAINDIA", "series": "IL", "isin": "INE176A01028", "snapshot_date": "2015-10-08",
    }])
    assert builder._apply_documented_isin_continuity([event], [], [], sources)[0] == [event]


def test_stock_split_mapping_never_invents_or_promotes_identity_or_b1_events(tmp_path, monkeypatch):
    sources = _verified_bata_sources(tmp_path, monkeypatch)
    challenger = Observation(symbol="BATAINDIA", isin="INE176A01028", instrument_id="NSE-ISIN:INE176A01028",
                             source_tier="B1", confidence="PROVISIONAL", review_status="UNRESOLVED")
    untouched = [replace(challenger, symbol="OTHER"), replace(challenger, instrument_id=None),
                 replace(challenger, instrument_id="UNRELATED-INSTRUMENT"), replace(challenger, isin="UNRELATED-ISIN")]
    rows, _, _, _ = builder._apply_documented_isin_continuity([challenger, *untouched], [], [], sources)
    assert rows[0] == replace(challenger, instrument_id="NSE-ISIN:INE176A01010")
    assert rows[1:] == untouched


def test_documented_split_closes_real_style_drop_without_creating_membership_events(tmp_path, monkeypatch):
    from tools.nifty200_pit.intervals import build_intervals
    from tools.nifty200_pit.reconciliation import reconcile_observations

    sources = _verified_bata_sources(tmp_path, monkeypatch)
    entry = Observation(symbol="BATAINDIA", isin="INE176A01010", instrument_id="NSE-ISIN:INE176A01010",
                        action="ADD", effective_date=date(2012, 4, 27), announcement_date=date(2012, 3, 14),
                        source_sha256="a" * 64, confidence="CERTIFIED", review_status="ACCEPTED")
    exit_row = replace(entry, isin="INE176A01028", instrument_id="NSE-ISIN:INE176A01028", action="DROP",
                       effective_date=date(2024, 3, 28), announcement_date=date(2024, 2, 28), source_sha256="b" * 64)
    before = build_intervals(reconcile_observations([entry, exit_row]).events)
    assert len(before.conflicts) == 1
    projected, _, _, _ = builder._apply_documented_isin_continuity([entry, exit_row], [], [], sources)
    events = reconcile_observations(projected).events
    after = build_intervals(events)
    assert len(events) == 2
    assert len(after.intervals) == 1 and after.conflicts == []
    assert after.intervals[0].effective_until == date(2024, 3, 28)


def test_nbcc_multi_split_chain_requires_both_documented_links(tmp_path, monkeypatch):
    groups = [
        ("69b7b0ea2b72649ec447ed47df9f15a4ca2cfffeb4983a9557a9246c6d1c74ee",
         "87df9d926becfd62eae15fb55bfdd5dc2d2d017d00eaacaa8e403078395f5415",
         "9892c2b4c078fbeadaab8a45087f5b316a833d74e7d7cc4df949ed72953c6e09",
         "INE095N01015", "INE095N01023", "2016-06-02", "2016-06-03"),
        ("ff186e104f0ec6fce4257422655e453aa289a9b80389b44fff260177856d4521",
         "2c1bba907be7866dfccaa6e6380b60341d18547ff389f4100526043d0b541dc1",
         "1c29705c1138d2852db6f0eb0bfd25d61d649e57711b818c57fa033326b2d6cb",
         "INE095N01023", "INE095N01031", "2018-04-25", "2018-04-26"),
    ]
    sources = []
    reference = {}
    for notice, before, after, old, new, before_day, after_day in groups:
        for digest in (notice, before, after):
            path = tmp_path / digest
            path.write_bytes(b"test-only evidence")
            sources.append(SourceRecord("official", str(path), digest, "now"))
        reference[before] = [{"symbol": "NBCC", "isin": old, "series": "EQ", "snapshot_date": before_day}]
        reference[after] = [{"symbol": "NBCC", "isin": new, "series": "EQ", "snapshot_date": after_day}]
    monkeypatch.setattr(builder, "sha256_file", lambda path: path.name)
    monkeypatch.setattr(builder, "parse_bhavcopy_identities", lambda source: reference[source.source_sha256])
    final = Observation(symbol="NBCC", isin="INE095N01031", instrument_id="NSE-ISIN:INE095N01031")
    full = builder._apply_documented_isin_continuity([final], [], [], sources)
    assert full[0][0].instrument_id == "NSE-ISIN:INE095N01015"
    assert len(full[3]["links"]) == 2
    partial = builder._apply_documented_isin_continuity([final], [], [], sources[3:])
    assert partial[0][0].instrument_id == "NSE-ISIN:INE095N01023"
    assert len(partial[3]["links"]) == 1
