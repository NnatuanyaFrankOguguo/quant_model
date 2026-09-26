"""Where an EDGAR filing lives, from the two things every filing row carries.

An accession number identifies a filing; the SEC's archive lays filings out by CIK and
accession, so the folder that holds every document of a filing has a fixed shape:

    https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/

That folder is the provenance a reader can open (`docs/05` §11, Q20) - the primary
document, the XBRL instance and the filing index are all inside it. Nothing here is fetched;
this is a string the API hands out so the screen can link to the source of every figure.
"""

from __future__ import annotations

__all__ = ["filing_index_url"]

_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"


def filing_index_url(cik: str | None, accession_no: str | None) -> str | None:
    """The archive folder of one filing, or None when either identifier is missing.

    The CIK is used without its zero padding and the accession number without its dashes,
    which is how the archive names its folders.
    """
    if not cik or not accession_no:
        return None
    if not cik.strip().isdigit():
        return None
    return f"{_ARCHIVE}/{int(cik)}/{accession_no.replace('-', '')}/"
