# banlog

Maintains nftables IP blocklist sets from external feeds with a SQLite audit trail.

## Install

```bash
# via pipx
pipx install banlog

# via uv
uv tool install banlog
```

## Setup

```bash
sudo mkdir -p /etc/banlog /var/lib/banlog
sudo cp config/lists.example.json /etc/banlog/lists.json
# Edit /etc/banlog/lists.json to enable the feeds and services you need
```

## Usage

```bash
sudo banlog sync                        # fetch feeds, update nft sets
banlog status                           # active block counts per feed/service
banlog history --ip 1.2.3.4            # block history for an IP
banlog list --service ssh               # active IPs for a service
banlog feeds                            # show configured feeds
```

Global flags: `--config PATH`, `--db PATH`, `--log-level LEVEL`

## Wire into nftables

After first sync, reference the sets in your firewall rules:

```
table inet filter {
    chain input {
        type filter hook input priority 0; policy accept;
        ip saddr @banlog_ssh   tcp dport 22  drop
        ip saddr @banlog_https tcp dport 443 drop
    }
}
```

The `inet banlog` table must exist before loading these rules:

```bash
sudo banlog sync        # creates table and sets
sudo nft -f /etc/nftables.conf
```

## Systemd timer

```ini
# /etc/systemd/system/banlog.service
[Unit]
Description=banlog blocklist sync
[Service]
Type=oneshot
ExecStart=/usr/local/bin/banlog sync
```

```ini
# /etc/systemd/system/banlog.timer
[Unit]
Description=Run banlog every hour
[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now banlog.timer
```

## Troubleshooting

**`nft: No such table`** — run `sudo banlog sync` first to create the table and sets.

**`database is locked`** — a sync is running; `busy_timeout = 5000` retries automatically for 5 s.

**Schema version error** — the DB was written by a newer banlog. Upgrade the binary.

## Dev

```bash
uv sync
uv run pytest tests/unit/ --cov=banlog
uv run ruff check src/ && uv run ruff format --check src/
uv run mypy src/
```
