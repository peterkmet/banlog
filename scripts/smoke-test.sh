#!/usr/bin/env bash
set -euo pipefail

echo "==> banlog status"
banlog status

echo "==> nft set exists"
nft list set inet banlog banlog_ssh

echo "==> history lookup (empty result is ok)"
banlog history --ip 8.8.8.8

echo "==> last sync_run is success"
sqlite3 /var/lib/banlog/banlog.db \
  "SELECT status FROM sync_runs ORDER BY id DESC LIMIT 1;" | grep -q "^success$"

echo "All smoke tests passed."
