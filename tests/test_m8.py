from pathlib import Path

from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

from bio_tools.homology import parse_m8


def test_m8_parsing_and_deduplication(tmp_path: Path) -> None:
    path = tmp_path / "hits.m8"
    path.write_text(
        "q\tsp|P1|ONE\t90\t10\t1\t0\t1\t10\t2\t11\t1e-5\t40\n"
        "q\tsp|P1|ONE\t91\t10\t1\t0\t1\t10\t2\t11\t1e-4\t39\n"
    )
    records = {
        "sp|P1|ONE": SeqRecord(Seq("ACDEFGHIKL"), id="sp|P1|ONE", description="sp|P1|ONE Protein one"),
    }
    hits = parse_m8(path, records)
    assert len(hits) == 1
    assert hits[0].accession == "P1"
    assert hits[0].percent_identity == 90
    assert hits[0].query_coverage == 1
