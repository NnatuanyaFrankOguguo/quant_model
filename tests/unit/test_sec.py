"""`packages.common.sec`: the archive folder of a filing, from CIK and accession number."""

from __future__ import annotations

import pytest

from packages.common.sec import filing_index_url


def test_the_archive_folder_drops_the_cik_padding_and_the_accession_dashes() -> None:
    assert (
        filing_index_url("0000320193", "0000320193-25-000079")
        == "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/"
    )


@pytest.mark.parametrize(
    ("cik", "accession"),
    [
        (None, "0000320193-25-000079"),
        ("0000320193", None),
        ("", ""),
        ("AAPL", "0000320193-25-000079"),
    ],
)
def test_a_missing_or_malformed_identifier_gives_no_link(
    cik: str | None, accession: str | None
) -> None:
    assert filing_index_url(cik, accession) is None
