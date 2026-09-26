#!/bin/sh
# Refuse edits to generated files.
case "$1" in *_pb2.py) exit 2 ;; esac
