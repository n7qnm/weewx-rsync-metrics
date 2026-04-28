# weewx-rsync-metrics

Captures rsync upload statistics (file count, bytes transferred, duration)
and routes them to one or more outputs. Requires **no changes to weewx core** —
implemented entirely as a Python logging handler intercepting log messages
from `weeutil.rsyncupload`.

## Outputs

| Output | Description |
|--------|-------------|
| `archive` | Injects stats into weewx archive records as `rsyncFiles`, `rsyncBytes`, `rsyncDuration`. Daily summaries (min/max/avg) generated automatically. |
| `csv` | Appends a timestamped row to a CSV file after each upload cycle. |
| `mqtt` | Publishes a JSON payload to an MQTT broker after each upload cycle. |

One or more outputs can be enabled simultaneously.

## Installation

```bash
weectl extension install https://github.com/n7qnm/weewx-rsync-metrics/releases/download/v0.2/weewx-rsync-metrics.tar.gz
```

No patches required. Restart weewx after installation.

## Configuration

The installer adds a `[RsyncMetrics]` stanza to `weewx.conf` with all
options and their defaults. Edit as needed:

```ini
[RsyncMetrics]
    # One or more of: archive, csv, mqtt
    output = archive

    # csv output
    csv_path = /var/log/weewx/rsync-metrics.csv

    # mqtt output (requires: pip install paho-mqtt)
    mqtt_host = localhost
    mqtt_port = 1883
    mqtt_user =
    mqtt_password =
    mqtt_tls = false
    mqtt_topic = weather/weewx/rsync/metrics
    mqtt_status_topic = weather/weewx/rsync/status
    mqtt_client_id = weewx-rsync-metrics
```

## MQTT payload

```json
{
  "rsyncFiles": 28,
  "rsyncBytes": 173544,
  "rsyncDuration": 0.87,
  "timestamp": 1713393962
}
```

A Last Will and Testament message (`offline`) is published to
`mqtt_status_topic` on disconnect, and `online` on connect. This enables
Zabbix or other monitoring systems to detect if weewx stops running.

## Archive fields

| Field | Type | Description |
|-------|------|-------------|
| `rsyncFiles` | INTEGER | Files transferred |
| `rsyncBytes` | INTEGER | Bytes transferred |
| `rsyncDuration` | REAL | Duration in seconds |

The archive schema is extended automatically on first run.

Because StdReport runs *after* each archive record is committed, values
in record N reflect the upload that ran after record N-1 — a one archive
interval lag. This is expected behavior.

Daily summary tables (`archive_day_rsync*`) are maintained automatically,
giving you `$day.rsyncDuration.max`, `$day.rsyncBytes.sum`, etc. in skins.

## Skin templates

```html
<tr>
  <td class="label">$obs.label.rsyncDuration</td>
  <td class="data">$current.rsyncDuration.format("%.2f s")</td>
</tr>
<tr>
  <td class="label">$obs.label.rsyncBytes</td>
  <td class="data">$current.rsyncBytes</td>
</tr>
```

## Manual schema migration

If automatic `ALTER TABLE` fails:

**SQLite:**
```sql
sqlite3 ~/weewx-data/archive/weewx.sdb
ALTER TABLE archive ADD COLUMN rsyncFiles    INTEGER;
ALTER TABLE archive ADD COLUMN rsyncBytes    INTEGER;
ALTER TABLE archive ADD COLUMN rsyncDuration REAL;
```

**MySQL:**
```sql
ALTER TABLE archive ADD COLUMN rsyncFiles    INT;
ALTER TABLE archive ADD COLUMN rsyncBytes    INT;
ALTER TABLE archive ADD COLUMN rsyncDuration FLOAT;
```

## Verification

After the first upload cycle, check the logs:

```
rsync_metrics: service started (outputs=['archive'] stale_threshold=600s)
rsync_metrics: archive <- files=28 bytes=173544 duration=0.87
```

## Uninstall

```bash
weectl extension uninstall rsync-metrics
```

Archive columns and collected data are preserved on uninstall.
