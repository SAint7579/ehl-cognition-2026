# Scientific fixtures

These small protein fixtures are retrieved from the UniProt REST API:
`https://rest.uniprot.org/uniprotkb/<accession>.fasta`. The original FASTA
headers are preserved verbatim. UniProt data is available under the
[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) license; please
retain attribution when redistributing these files.

`MANIFEST.json` records the source, sequence digest, version, and retrieval
metadata for each sequence. To refresh the fixtures, run
`./.venv/bin/python scripts/fetch_fixtures.py` from the repository root and
review the resulting manifest and sequence changes.
