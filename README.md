# weewx-rsync-metrics

Records rsync upload statistics as first-class observations in the weewx
archive database, making them available in skins, plots, and daily summaries.

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `rsyncFiles` | INTEGER | Files transferred per upload cycle |
| `rsyncBytes` | INTEGER | Bytes transferred per upload cycle |
| `rsyncDuration` | REAL | Upload duration in seconds |

Because StdReport runs *after* each archive record is committed, the values
in record N reflect the upload that ran after record N-1 — a one archive
interval lag. This is correct and expected behavior.

Daily summary tables (`archive_day_rsync*`) are maintained automatically by
weewx's DaySummaryManager, giving you min/max/avg per day for free.

## Requirements

- weewx 5.x
- The `record_stats` patch applied to `weeutil/rsyncupload.py`
  (submit as a PR, or apply `rsyncupload.patch` manually)

## Installation

### 1. Apply the rsyncupload patch

```bash
# From your weewx source directory
patch -p1 < rsyncupload.patch

# Or for a package install, patch in-place:
sudo patch /usr/share/weewx/weeutil/rsyncupload.py rsyncupload.patch
```

### 2. Install the extension

```bash
weectl extension install weewx-rsync-metrics.tar.gz
```

### 3. Enable record_stats in weewx.conf

```ini
[StdReport]
    [[RSYNC]]
        record_stats = true
```

### 4. Restart weewx

```bash
sudo systemctl restart weewx
```

## Verification

After the first upload cycle, you should see in the logs:

```
rsync_metrics: service started (stale_threshold=600s)
rsync_metrics: injecting files=28 bytes=173544 duration=0.87
```

Query the database directly to confirm:

```bash
sqlite3 /var/lib/weewx/weewx.sdb \
  "SELECT datetime(dateTime,'unixepoch','localtime'), rsyncFiles, rsyncBytes, rsyncDuration \
   FROM archive ORDER BY dateTime DESC LIMIT 5;"
```

## Skin templates

Current conditions:
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

Daily summary:
```html
<!-- Max upload duration today -->
<td>$day.rsyncDuration.max.format("%.2f s")</td>
<!-- Total bytes uploaded today -->
<td>$day.rsyncBytes.sum</td>
```

## Manual schema migration

If the automatic `ALTER TABLE` fails:

**SQLite:**
```sql
sqlite3 /var/lib/weewx/weewx.sdb
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

## Uninstall

```bash
weectl extension uninstall rsync-metrics
```

Note: uninstalling the extension does not remove the archive columns.
The data is preserved. Remove columns manually if desired.
