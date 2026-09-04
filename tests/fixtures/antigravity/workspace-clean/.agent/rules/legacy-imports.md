# Importing the 2019 timetable archive

The archive under `data/archive-2019/` predates the GTFS migration and its
columns do not match the current schema.

- Import it with `make import-archive`, never with `psql -f`. The target
  applies the column mapping in `internal/schedule/legacy.go`.
- Archive rows carry local time with no zone. The importer assumes
  `Europe/Dublin`; a row that fails to convert is written to
  `build/archive-rejects.csv` rather than skipped silently.
- Read `build/archive-rejects.csv` after every import and report its row
  count. A non-empty file is a schema mismatch, not a data quality issue.
