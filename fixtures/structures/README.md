# Structure fixtures

These pristine PDB files are downloaded from RCSB PDB and stored as gzip
files under the RCSB PDB data license (CC0 1.0). `MANIFEST.json` records the
deposition metadata and SHA-256 digests of both the uncompressed download and
the committed gzip file. The selected analysis chain is recorded per entry;
1JFR intentionally contains both chains because Foldseek must handle
multi-chain references.

Refresh the fixtures with:

```sh
./.venv/bin/python scripts/fetch_structure_fixtures.py
```

Tests use only these committed files and never access the network.
