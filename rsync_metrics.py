#
#    Copyright (c) 2026
#
#    See the file LICENSE.txt for your full rights.
#
"""
rsync_metrics.py — weewx data service
======================================
Injects rsync upload statistics captured by RsyncUpload (when record_stats=True)
into each archive record, making them available as first-class observations in
the weewx database, skins, plots, and daily summary tables.

Fields added to archive:
    rsyncFiles    (INTEGER) — number of files transferred
    rsyncBytes    (INTEGER) — bytes transferred
    rsyncDuration (REAL)    — upload duration in seconds

Because StdReport (and thus rsync) runs *after* each archive record is
committed, the stats injected into record N come from the upload that ran
after record N-1 was written — a one archive-interval lag.  This is
intentional and is the correct behavior for this architecture.

Installation
------------
1. Copy this file to the weewx user directory:
       /etc/weewx/bin/user/rsync_metrics.py        (package install)
       ~/weewx-data/bin/user/rsync_metrics.py      (pip install)

2. In weewx.conf, add to [Engine] [[Services]] data_services:
       data_services = user.rsync_metrics.RsyncMetricsService

3. In weewx.conf, enable record_stats in [[RSYNC]]:
       [[RSYNC]]
           record_stats = true

4. Restart weewx.

The archive schema is extended automatically on first run.  If automatic
schema extension fails (e.g., permission issues), see the manual SQL
commands in the comments at the bottom of this file.
"""

import logging
import time

import weewx
import weewx.units
from weewx.engine import StdService

log = logging.getLogger(__name__)

SCHEMA_ADDITIONS = [
    ('rsyncFiles',    'INTEGER'),
    ('rsyncBytes',    'INTEGER'),
    ('rsyncDuration', 'REAL'),
]

# Maximum age of a stats sample before it is considered stale and replaced
# with NULL.  Two archive intervals is a safe default: it handles a single
# missed or failed upload without silently injecting outdated values.
# The service reads the actual archive_interval from the config at startup.
STALE_FACTOR = 2


def _register_units():
    """Register observation groups and display units for the new fields."""

    # rsyncFiles: a simple count, dimensionless
    weewx.units.obs_group_dict['rsyncFiles'] = 'group_count'

    # rsyncDuration: time in seconds; reuse weewx's existing elapsed-time group
    weewx.units.obs_group_dict['rsyncDuration'] = 'group_elapsed'
    if 'group_elapsed' not in weewx.units.USUnits:
        weewx.units.USUnits['group_elapsed']       = 'second'
        weewx.units.MetricUnits['group_elapsed']   = 'second'
        weewx.units.MetricWXUnits['group_elapsed'] = 'second'

    # rsyncBytes: data size in bytes; define a minimal group for this
    weewx.units.obs_group_dict['rsyncBytes'] = 'group_data'
    if 'group_data' not in weewx.units.USUnits:
        weewx.units.USUnits['group_data']            = 'byte'
        weewx.units.MetricUnits['group_data']        = 'byte'
        weewx.units.MetricWXUnits['group_data']      = 'byte'
        weewx.units.default_unit_label_dict['byte']  = ' B'
        weewx.units.default_unit_format_dict['byte'] = '%d'


class RsyncMetricsService(StdService):
    """
    Injects rsync upload metrics into each archive record.

    Reads stats written by RsyncUpload.run() (when record_stats=True) from
    the shared store in weeutil.rsyncupload, and injects them into the
    NEW_ARCHIVE_RECORD event so they are written to the archive table and
    picked up automatically by the daily summary manager.
    """

    def __init__(self, engine, config_dict):
        super().__init__(engine, config_dict)

        # Read archive interval so we can detect stale stats
        self.archive_interval = int(
            config_dict.get('StdArchive', {}).get('archive_interval', 300)
        )
        self.stale_threshold = self.archive_interval * STALE_FACTOR

        # Register unit groups before anything touches the fields
        _register_units()

        # Extend the archive schema with our new columns
        self._extend_schema(engine)

        # Bind to the archive record event
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.new_archive_record)

        log.info("rsync_metrics: service started (stale_threshold=%ds)",
                 self.stale_threshold)

    def _extend_schema(self, engine):
        """Add rsync columns to the archive table if they are absent."""
        try:
            db_manager = engine.db_binder.get_manager(
                data_binding='wx_binding', initialize=True
            )
            existing = db_manager.connection.columnsOf('archive')
            for col_name, col_type in SCHEMA_ADDITIONS:
                if col_name not in existing:
                    db_manager.connection.execute(
                        f"ALTER TABLE archive ADD COLUMN {col_name} {col_type}"
                    )
                    log.info("rsync_metrics: added column %s %s to archive table",
                             col_name, col_type)
                else:
                    log.debug("rsync_metrics: column %s already present", col_name)
        except Exception as e:
            log.error("rsync_metrics: schema extension failed: %s", e)
            log.error("rsync_metrics: run the manual SQL commands shown in "
                      "rsync_metrics.py to add the columns by hand")

    def new_archive_record(self, event):
        """
        Inject the most recent rsync stats into the archive record.

        If no stats have been captured yet, or the most recent stats are
        older than stale_threshold seconds, inject NULL for all three
        fields so the archive record correctly reflects the absence of a
        successful upload rather than carrying forward stale values.
        """
        try:
            from weeutil.rsyncupload import get_rsync_stats
        except ImportError:
            log.error("rsync_metrics: cannot import get_rsync_stats from "
                      "weeutil.rsyncupload — is record_stats patch applied?")
            return

        stats = get_rsync_stats()

        if not stats:
            log.debug("rsync_metrics: no stats captured yet, injecting NULL")
            files = nbytes = duration = None
        else:
            age = time.time() - stats.get('timestamp', 0)
            if age > self.stale_threshold:
                log.debug("rsync_metrics: stats stale (age=%.0fs > threshold=%ds), "
                          "injecting NULL", age, self.stale_threshold)
                files = nbytes = duration = None
            else:
                files    = stats.get('rsyncFiles')
                nbytes   = stats.get('rsyncBytes')
                duration = stats.get('rsyncDuration')
                log.debug("rsync_metrics: injecting files=%s bytes=%s duration=%s",
                          files, nbytes, duration)

        event.record['rsyncFiles']    = files
        event.record['rsyncBytes']    = nbytes
        event.record['rsyncDuration'] = duration

    def shutDown(self):
        log.info("rsync_metrics: service stopped")


# =============================================================================
# Manual schema migration (only if automatic ALTER TABLE fails)
# =============================================================================
#
# SQLite:
#   sqlite3 /var/lib/weewx/weewx.sdb
#   ALTER TABLE archive ADD COLUMN rsyncFiles    INTEGER;
#   ALTER TABLE archive ADD COLUMN rsyncBytes    INTEGER;
#   ALTER TABLE archive ADD COLUMN rsyncDuration REAL;
#   .quit
#
# MySQL:
#   mysql -u weewx -p weewx
#   ALTER TABLE archive ADD COLUMN rsyncFiles    INT;
#   ALTER TABLE archive ADD COLUMN rsyncBytes    INT;
#   ALTER TABLE archive ADD COLUMN rsyncDuration FLOAT;
#   quit;
#
# =============================================================================
