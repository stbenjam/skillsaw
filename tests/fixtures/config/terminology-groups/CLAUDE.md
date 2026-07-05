# Project Standards

This marketplace documents plugins written in Go, Java, and Python.

## Layout

- Put each plugin in its own directory under `plugins/`.
- Go plugins export a `Run` function as the entry point.
- Keep shared helpers in the `internal/` directory.
