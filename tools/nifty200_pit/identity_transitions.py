"""Source-bound limits on old identity observations after an explicit ISIN change."""

from datetime import date, datetime
import csv
import io
from pathlib import Path
import re
from typing import Any
from zipfile import ZipFile

from pypdf import PdfReader

from tools.nifty200_pit.source_catalogue import sha256_file

TRANSITIONS = (
    ("J&KBANK", "INE168A01017", "INE168A01041", date(2014, 9, 4),
     "https://www.msei.in/SX-Content/Circulars/2014/August/Circular-2158.pdf",
     "777f92cd8ba2e116603595e28a1232955ac7c323c98110f1e2ff0a7fb97f8731"),
    ("KSCL", "INE455I01011", "INE455I01029", date(2014, 1, 27),
     "https://www.msei.in/SX-Content/Circulars/2014/January/Circular-1722.pdf",
     "de2f63f864a980118f00ea69bf937cad39aae76b44dffba8f81197f37f18134c"),
    ("GRASIM", "INE047A01013", "INE047A01021", date(2016, 10, 6),
     "https://www.msei.in/SX-Content/Circulars/2016/October/Circular-4581.pdf",
     "974296c5ad548d0f69e686af4cdb36d04e2472c7dc486a6ea68144d50ea2511d"),
    ("ASTRAL", "INE006I01020", "INE006I01038", date(2013, 9, 5),
     "https://www.msei.in/SX-Content/Circulars/2013/August/Circular-1410.pdf",
     "5c31af638d8bda7c3ae5e368f80ab5214bb64c5c2176b4c409e38a24d0aefb6d"),
    ("ASTRAL", "INE006I01038", "INE006I01046", date(2014, 9, 25),
     "https://www.msei.in/SX-Content/Circulars/2014/September/Circular-2221.pdf",
     "e2eb66fd60c85ae1a81873dc1cbbd54018b89172011aa54f08061595074f2dc0"),
    ("AVANTIFEED", "INE871C01012", "INE871C01020", date(2015, 11, 26),
     "https://www.msei.in/SX-Content/Circulars/2015/November/Circular-3554.pdf",
     "53fedca5af202a514431b0d2035fe2575e797b2aa54431bc0d64062183620d26"),
    ("AVANTIFEED", "INE871C01020", "INE871C01038", date(2018, 6, 26),
     "https://www.msei.in/SX-Content/Circulars/2018/June/Circular-6487.pdf",
     "89394ee4cb1af0f063161be054ac31df1a13c02ae78a6ad23258305e5024e91b"),
    ("BAJFINANCE", "INE296A01016", "INE296A01024", date(2016, 9, 8),
     "https://www.msei.in/SX-Content/Circulars/2016/September/Circular-4496.pdf",
     "11b2a619b064c270d04a3fedc14633317d0a87959a212f98dad5349ad14babc5"),
    ("CESC", "INE486A01013", "INE486A01021", date(2021, 9, 17),
     "https://www.msei.in/SX-Content/Circulars/2021/September/Circular-10876.pdf",
     "debfe8c84bce0d5dde9eb2483525cdf28b3469508b2f1ccbfe21aac7bd662c3a"),
    ("DEEPAKNTR", "INE288B01011", "INE288B01029", date(2014, 6, 20),
     "https://www.msei.in/SX-Content/Circulars/2014/June/Circular-1993.pdf",
     "c0f11df39db0d4cc65d59bc2af7c482b067d1fa0debb1f3a46f7239bcb56aa0d"),
    ("GODREJPROP", "INE484J01019", "INE484J01027", date(2013, 11, 21),
     "https://www.msei.in/SX-Content/Circulars/2013/November/Circular-1592.pdf",
     "53346d2c1c42fb3985e329859a84028a89af219d5ef9672ebbee8b1106b56782"),
    ("GUJGASLTD", "INE844O01022", "INE844O01030", date(2019, 1, 15),
     "https://www.msei.in/SX-Content/Circulars/2019/January/Circular-7193.pdf",
     "84f803ec34342b9b7c0b53fd048b8f73f0ecf477be826e25d1b0b88f1821cc89"),
    ("KARURVYSYA", "INE036D01010", "INE036D01028", date(2016, 11, 17),
     "https://www.msei.in/SX-Content/Circulars/2016/November/Circular-4695.pdf",
     "a9bdaffd58af89da20f2e435ca7442ba4d2db26910cbd40ee94d2c2ab2b531dd"),
    ("NATCOPHARM", "INE987B01018", "INE987B01026", date(2015, 11, 26),
     "https://www.msei.in/SX-Content/Circulars/2015/November/Circular-3582.pdf",
     "8cc134331933ddaa8d6030f53efd4b1054b35ca234cd390f5c27db9e33888244"),
    ("NAVINFLUOR", "INE048G01018", "INE048G01026", date(2017, 7, 19),
     "https://www.msei.in/SX-Content/Circulars/2017/July/Circular-5356.pdf",
     "aea8dd59557d64972397c587d77cff8a45ba321634e0f4bad8508fe50aa825ac"),
    ("NBCC", "INE095N01015", "INE095N01023", date(2016, 6, 2),
     "https://www.msei.in/SX-Content/Circulars/2016/June/Circular-4217.pdf",
     "49dcee910cad4a534c3178508c2443f9a7a4afadf084dc37e79ec8dc2e3853c9"),
    ("NBCC", "INE095N01023", "INE095N01031", date(2018, 4, 25),
     "https://www.msei.in/SX-Content/Circulars/2018/April/Circular-6260.pdf",
     "ff186e104f0ec6fce4257422655e453aa289a9b80389b44fff260177856d4521"),
    ("PIIND", "INE603J01022", "INE603J01030", date(2013, 4, 12),
     "https://www.msei.in/SX-Content/Circulars/2013/April/Circular-1114.pdf",
     "d4357f8381ce18ada64efdeb2519bde3af79c6f2c537a83202ace35d5bce7b36"),
    ("TRENT", "INE849A01012", "INE849A01020", date(2016, 9, 12),
     "https://www.msei.in/SX-Content/Circulars/2016/September/Circular-4501.pdf",
     "6e76c1f97341757461fa77db7d8d28044b828d73947794c065e45a11ccb8bec6"),
    ("TRIDENT", "INE064C01014", "INE064C01022", date(2019, 12, 13),
     "https://www.msei.in/SX-Content/Circulars/2019/November/Circular-8378.pdf",
     "fe3e3412b15e21638862e6de493c688bf3492f27a5a0cf1c880c4ec99ca104d2"),
    ("YESBANK", "INE528G01019", "INE528G01027", date(2017, 9, 21),
     "https://www.msei.in/SX-Content/Circulars/2017/September/Circular-5543.pdf",
     "6bee48b705e78b19574ba0a393fc52d493dd8f071c28e0f32bba855229b595e9"),
    ("YESBANK", "INE528G01027", "INE528G01035", date(2020, 3, 16),
     "https://nsearchives.nseindia.com/content/circulars/CMPT43834.pdf",
     "a4d156c72902691a12f3693d812774384f982e768b0909023e9171eb3ef209cc"),
)

_AJANTA_SESSIONS = (
    ("09AUG2012", "INE031B01015", "a87eecb3503634167298bed84d9dfbc1d5b1d0d747faf99d90c525cacb22efb1"),
    ("10AUG2012", "INE031B01031", "37c18b9ac6eec7168a26e438b6f8ab7d8020961569015753f146d97ed666122c"),
)

_AJANTA_2015_SESSIONS = (
    ("19MAR2015", "INE031B01031", "da295c74d69cd74e2df4e33a356913a4fdae654c7dd84df98280d3a8c2212858"),
    ("20MAR2015", "INE031B01031", "d876d3d801afc7c3c315d319f9e96c55f64ab4dfc32074377ca9f2c0a6554271"),
    ("23MAR2015", "INE031B01049", "0e0bf3ba4fbd4e51385f3d91f3f816a2478385cd06d1fd79edf2b6108be5d5a3"),
)


def _ajanta_transition(sources: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]] | None:
    """Verify the exact EQ symbol, ISIN and trade date in the two NSE files."""
    pair: list[dict[str, str]] = []
    for session, isin, digest in _AJANTA_SESSIONS:
        member = f"cm{session}bhav.csv"
        url = f"https://nsearchives.nseindia.com/content/historical/EQUITIES/2012/AUG/{member}.zip"
        matches = [s for s in sources if (s["source_url"], s["source_sha256"]) == (url, digest)
                   and s.get("source_tier") == "A1"]
        if not matches:
            return None
        stamp = datetime.strptime(session, "%d%b%Y").strftime("%d-%b-%Y").upper()
        for source in matches:
            path = Path(source["local_path"])
            if sha256_file(path) != digest:
                raise ValueError("transition_source_hash:AJANTPHARM")
            with ZipFile(path) as archive, archive.open(member) as raw:
                with io.TextIOWrapper(raw, encoding="utf-8-sig") as content:
                    equity = [(row["ISIN"].strip(), row["TIMESTAMP"].strip()) for row in csv.DictReader(content)
                              if row["SYMBOL"].strip() == "AJANTPHARM" and row["SERIES"].strip() == "EQ"]
            if equity != [(isin, stamp)]:
                raise ValueError("transition_source_semantics:AJANTPHARM")
        pair.append({"url": url, "digest": digest, "member": member})
    return pair[0], pair[1]


def _ajanta_2015_transition(sources: list[dict[str, Any]]) -> tuple[dict[str, str], ...] | None:
    """Verify the NSE EQ identity across the 2015 split's adjacent sessions."""
    verified: list[dict[str, str]] = []
    for session, isin, digest in _AJANTA_2015_SESSIONS:
        member = f"cm{session}bhav.csv"
        url = f"https://nsearchives.nseindia.com/content/historical/EQUITIES/2015/MAR/{member}.zip"
        matches = [s for s in sources if (s["source_url"], s["source_sha256"]) == (url, digest)
                   and s.get("source_tier") == "A1"]
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError("transition_duplicate_source:AJANTPHARM")
        source = matches[0]
        path = Path(source["local_path"])
        if sha256_file(path) != digest:
            raise ValueError("transition_source_hash:AJANTPHARM")
        with ZipFile(path) as archive:
            if archive.testzip() is not None or member not in archive.namelist():
                raise ValueError("transition_source_member:AJANTPHARM")
            with archive.open(member) as raw:
                with io.TextIOWrapper(raw, encoding="utf-8-sig") as content:
                    equity = [(row["ISIN"].strip(), row["TIMESTAMP"].strip())
                              for row in csv.DictReader(content)
                              if row["SYMBOL"].strip() == "AJANTPHARM" and row["SERIES"].strip() == "EQ"]
        stamp = datetime.strptime(session, "%d%b%Y").strftime("%d-%b-%Y").upper()
        if equity != [(isin, stamp)]:
            raise ValueError("transition_source_semantics:AJANTPHARM")
        verified.append({"url": url, "digest": digest, "member": member})
    return tuple(verified)


def apply_transition_boundaries(
    rows: list[dict[str, Any]], sources: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Constrain EQ observations to the trade boundary without admitting them.

    Only inspected source URL/hash pairs can constrain a row. Later old-ISIN
    observations are contradictory evidence and raise rather than disappearing.
    """
    result = [dict(row) for row in rows]
    audit = []
    series_cache: dict[tuple[str, str], dict[tuple[str, str], set[str]]] = {}

    def source_series(row: dict[str, Any]) -> set[str]:
        key = (str(row.get("source_url") or ""), str(row.get("source_sha256") or ""))
        if key not in series_cache:
            lookup: dict[tuple[str, str], set[str]] = {}
            for source in sources:
                if ((source["source_url"], source["source_sha256"]) != key or
                        source.get("source_tier") not in {"A1", "A2"}):
                    continue
                path = Path(source["local_path"])
                if path.suffix.lower() != ".csv":
                    continue
                if sha256_file(path) != key[1]:
                    raise ValueError("transition_observation_source_hash:" + key[1])
                content = path.read_bytes()
                try:
                    text = content.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = content.decode("cp1252")
                for original in csv.DictReader(io.StringIO(text)):
                    raw = {str(k).strip().upper(): str(v or "").strip() for k, v in original.items() if k}
                    identity = (raw.get("SYMBOL", ""), raw.get("ISIN NUMBER") or raw.get("ISIN CODE", ""))
                    if raw.get("SERIES"):
                        lookup.setdefault(identity, set()).add(raw["SERIES"].upper())
            series_cache[key] = lookup
        return series_cache[key].get((row["symbol"], row["isin"]), set())
    transitions = list(TRANSITIONS)
    ajanta = _ajanta_transition(sources)
    if ajanta:
        transitions.insert(0, ("AJANTPHARM", "INE031B01015", "INE031B01031", date(2012, 8, 10),
                               ajanta[1]["url"], ajanta[1]["digest"]))
    ajanta_2015 = _ajanta_2015_transition(sources)
    paired_transition_sources: dict[str, tuple[dict[str, str], ...]] = {}
    if ajanta:
        paired_transition_sources[ajanta[1]["url"]] = ajanta
    if ajanta_2015:
        transitions.insert(0, ("AJANTPHARM", "INE031B01031", "INE031B01049", date(2015, 3, 23),
                               ajanta_2015[-1]["url"], ajanta_2015[-1]["digest"]))
        paired_transition_sources[ajanta_2015[-1]["url"]] = ajanta_2015
    restored_rows = []
    transition_keys = {(symbol, isin) for symbol, old, new, *_ in transitions for isin in (old, new)}
    for index, row in enumerate(result):
        scopes = (source_series(row) if not row.get("series") and
                  (row.get("symbol"), row.get("isin")) in transition_keys else set())
        if scopes:
            for scope in sorted(scopes):
                restored_rows.append({**row, "series": scope,
                                      "series_source_sha256": row["source_sha256"],
                                      "transition_series_restored": True,
                                      "original_master_row_index": index})
        else:
            restored_rows.append(row)
    result = restored_rows
    for symbol, old, new, boundary, url, digest in transitions:
        matches = [s for s in sources if s["source_sha256"] == digest and
                   s["source_url"] == url and s.get("source_tier") in {"A1", "A2"}]
        if not matches:
            continue
        pages = []
        paired_source = paired_transition_sources.get(url)
        if paired_source is None:
            for source in matches:
                path = Path(source["local_path"])
                if sha256_file(path) != digest:
                    raise ValueError("transition_source_hash:" + symbol)
                pages = [page.extract_text() or "" for page in PdfReader(path).pages]
        proof_pages = []
        for page_number, text in enumerate(pages, 1):
            compact = re.sub(r"\s+", "", text)
            dates = re.findall(r"Ex\s*-\s*date\s+i\.e\.\s*([A-Za-z]+)\s+([0-9\s]+?)\s*,\s*(\d{4})", text, re.I)
            has_isin = (symbol + old + new in compact) or ((old + new) in compact and symbol in compact)
            has_eq = "equityshares" in compact.lower() or "equity" in compact.lower()
            if "ForandonbehalfofNSEClearingLimited" in compact:
                has_isin = (
                    symbol in compact and
                    f"fromexistingISIN{old}tothenewISIN{new}" in compact
                )
                has_eq = "DEPARTMENT:CAPITALMARKETSEGMENT" in compact
                dates = re.findall(
                    rf"Fromtradedate([A-Za-z]+)(\d{{1,2}}),(\d{{4}})"
                    rf"earlypay-inofthesecurity{re.escape(symbol)}shallbemadeonlyinnewISIN{re.escape(new)}toavail",
                    compact,
                )
            cleaned_dates = []
            for month, day_str, year in dates:
                clean_day = re.sub(r"\s+", "", day_str)
                cleaned_dates.append((month, clean_day, year))
            trade_dates = {datetime.strptime(f"{m} {d} {y}", "%B %d %Y").date() for m, d, y in cleaned_dates}
            if has_isin and has_eq and trade_dates == {boundary}:
                proof_pages.append(page_number)
        source_details: dict[str, Any]
        if paired_source:
            current = paired_source[-1]
            source_details = {"source_member": current["member"],
                              "transition_source_members": [item["member"] for item in paired_source],
                              "transition_source_sha256s": [item["digest"] for item in paired_source],
                              "transition_source_urls": [item["url"] for item in paired_source]}
            if len(paired_source) == 2:
                source_details.update({"prior_source_member": paired_source[0]["member"],
                                       "prior_source_sha256": paired_source[0]["digest"],
                                       "prior_source_url": paired_source[0]["url"]})
        else:
            if len(proof_pages) != 1:
                raise ValueError("transition_source_semantics:" + symbol)
            source_details = {"source_page": proof_pages[0]}
        for index, row in enumerate(result):
            if row.get("symbol") != symbol or row.get("isin") not in {old, new}:
                continue
            restored = bool(row.get("transition_series_restored"))
            if not row.get("series"):
                if source_series(row) != {"EQ"}:
                    continue
                row["series"] = "EQ"
                row["series_source_sha256"] = row["source_sha256"]
                restored = True
            if row["series"] != "EQ":
                continue
            snapshot = row.get("snapshot_date")
            start = row.get("valid_from")
            if row["isin"] == new:
                # A later snapshot may repeat the issuer's original listing date.
                # Limit that observation's possible scope without creating a proof.
                if (row.get("has_explicit_historical_interval") or not snapshot or not start
                        or date.fromisoformat(str(snapshot)[:10]) < boundary
                        or date.fromisoformat(str(start)[:10]) >= boundary):
                    continue
                end = row.get("valid_until")
                if end and date.fromisoformat(str(end)[:10]) <= boundary:
                    raise ValueError("pre_transition_successor_interval:" + symbol)
                row["valid_from"] = boundary.isoformat()
                row["transition_start_source_sha256"] = digest
                row["transition_start_source_url"] = url
                audit.append({"row_index": index, "symbol": symbol, "old_isin": old,
                              "new_isin": new, "previous_valid_from": start,
                              "valid_from": boundary.isoformat(), "source_url": url,
                              "source_sha256": digest, **source_details,
                              "series_restored_from_source": restored,
                              "confidence_changed": False, "new_interval_created": False})
                continue
            if ((snapshot and date.fromisoformat(str(snapshot)[:10]) >= boundary) or
                    (start and date.fromisoformat(str(start)[:10]) >= boundary)):
                raise ValueError("post_transition_old_isin:" + symbol)
            end = row.get("valid_until")
            if end and date.fromisoformat(str(end)[:10]) <= boundary:
                continue
            row["valid_until"] = boundary.isoformat()
            row["transition_boundary_source_sha256"] = digest
            row["transition_boundary_source_url"] = url
            audit.append({"row_index": index, "symbol": symbol, "old_isin": old,
                          "new_isin": new, "previous_valid_until": end,
                          "valid_until": boundary.isoformat(), "source_url": url,
                          "source_sha256": digest, **source_details,
                          "series_restored_from_source": restored,
                          "confidence_changed": False, "new_interval_created": False})
    return result, audit
