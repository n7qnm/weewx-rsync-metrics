#
#    Copyright (c) 2026
#
#    See the file LICENSE.txt for your full rights.
#
"""
rsync_metrics.py — weewx data service
======================================
Captures rsync upload statistics by intercepting log messages from
weeutil.rsyncupload via a standard Python logging handler. No changes
to the weewx core are required.

Statistics captured per upload cycle:
    rsyncFiles    — number of files transferred
    rsyncBytes    — bytes transferred
    rsyncDuration — upload duration in seconds

Output options (configurable, one or more):
    archive   — inject into weewx archive record (and daily summaries)
    csv       — append to a CSV file
    mqtt      — publish JSON payload to an MQTT broker

Configuration in weewx.conf
-----------------------------
[RsyncMetrics]
    # One or more of: archive, csv, mqtt
    output = archive, mqtt

    # archive output: injects into weewx archive record
    # (no additional config needed)

    # csv output
    csv_path = /var/log/weewx/rsync-metrics.csv

    # mqtt output
    mqtt_host = localhost
    mqtt_port = 1883
    mqtt_user =
    mqtt_password =
    mqtt_tls = false
    mqtt_topic = weather/weewx/rsync/metrics
    mqtt_status_topic = weather/weewx/rsync/status
    mqtt_client_id = weewx-rsync-metrics

[Engine]
    [[Services]]
        data_services = user.rsync_metrics.RsyncMetricsService

Installation
------------
1. Copy this file to the weewx user directory:
       ~/weewx-data/bin/user/rsync_metrics.py      (pip install)
       /etc/weewx/bin/user/rsync_metrics.py        (package install)

2. Add [RsyncMetrics] stanza to weewx.conf (see above)

3. Add RsyncMetricsService to data_services in [Engine] [[Services]]

4. Restart weewx

No patches to weewx core are required.
"""

import csv
import json
import logging
import os
import re
import threading
import time

import weewx
import weewx.units
from weewx.engine import StdService

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Log line parser
# Matches: rsync'd 28 files (173,544 bytes) in 0.87 seconds
# This format has been stable across weewx versions.
# ---------------------------------------------------------------------------

RSYNC_RE = re.compile(
    r"rsync'd\s+(\d+)\s+files?\s+\(([\d,]+)\s+bytes?\)\s+in\s+([\d.]+)\s+seconds?"
)

# ---------------------------------------------------------------------------
# Thread-safe stats store
# Written by the logging handler (StdReport thread)
# Read by new_archive_record (main weewx thread)
# ---------------------------------------------------------------------------

_lock  = threading.Lock()
_stats = {}


def _set_stats(files, nbytes, duration):
    with _lock:
        _stats.update({
            'rsyncFiles':    files,
            'rsyncBytes':    nbytes,
            'rsyncDuration': duration,
            'timestamp':     time.time(),
        })


def _clear_stats():
    with _lock:
        _stats.clear()


def _get_stats():
    with _lock:
        return dict(_stats)


# ---------------------------------------------------------------------------
# Logging handler — zero core changes required
# ---------------------------------------------------------------------------

class _RsyncStatsHandler(logging.Handler):
    """
    Intercepts log records from weeutil.rsyncupload and extracts upload
    statistics from the summary line weewx emits after each successful run.

    Installed on the 'weeutil.rsyncupload' logger at service startup.
    Removed cleanly at service shutdown.
    """

    def __init__(self, callback_success, callback_failure):
        super().__init__()
        self._callback_success = callback_success
        self._callback_failure = callback_failure

    def emit(self, record):
        msg = record.getMessage()

        # Success line: rsync'd N files (B bytes) in D seconds
        m = RSYNC_RE.search(msg)
        if m:
            try:
                files    = int(m.group(1))
                nbytes   = int(m.group(2).replace(',', ''))
                duration = float(m.group(3))
                self._callback_success(files, nbytes, duration)
            except (ValueError, AttributeError) as e:
                log.warning("rsync_metrics: failed to parse rsync stats: %s", e)
            return

        # Failure line: rsync reported errors
        if 'rsync error' in msg or 'rsync reported errors' in msg:
            self._callback_failure()


# ---------------------------------------------------------------------------
# Output handlers
# ---------------------------------------------------------------------------

class _ArchiveOutput:
    """Injects stats into weewx archive records via NEW_ARCHIVE_RECORD."""

    # Schema additions for the archive table
    SCHEMA = [
        ('rsyncFiles',    'INTEGER'),
        ('rsyncBytes',    'INTEGER'),
        ('rsyncDuration', 'REAL'),
    ]

    def __init__(self, engine, stale_threshold):
        self.stale_threshold = stale_threshold
        self._extend_schema(engine)
        _register_units()
        log.info("rsync_metrics: archive output enabled")

    def _extend_schema(self, engine):
        try:
            db_manager = engine.db_binder.get_manager(
                data_binding='wx_binding', initialize=True
            )
            existing = db_manager.connection.columnsOf('archive')
            for col_name, col_type in self.SCHEMA:
                if col_name not in existing:
                    db_manager.connection.execute(
                        f"ALTER TABLE archive ADD COLUMN {col_name} {col_type}"
                    )
                    log.info("rsync_metrics: added column %s %s to archive",
                             col_name, col_type)
                else:
                    log.debug("rsync_metrics: column %s already present", col_name)
        except Exception as e:
            log.error("rsync_metrics: schema extension failed: %s", e)
            log.error("rsync_metrics: see manual SQL in rsync_metrics.py comments")

    def handle(self, stats, event):
        """Called from new_archive_record — inject values into the record."""
        if not stats:
            files = nbytes = duration = None
        else:
            age = time.time() - stats.get('timestamp', 0)
            if age > self.stale_threshold:
                log.debug("rsync_metrics: stats stale (age=%.0fs), injecting NULL", age)
                files = nbytes = duration = None
            else:
                files    = stats.get('rsyncFiles')
                nbytes   = stats.get('rsyncBytes')
                duration = stats.get('rsyncDuration')
                log.debug("rsync_metrics: archive <- files=%s bytes=%s duration=%s",
                          files, nbytes, duration)

        event.record['rsyncFiles']    = files
        event.record['rsyncBytes']    = nbytes
        event.record['rsyncDuration'] = duration

    def shutdown(self):
        pass


class _CsvOutput:
    """Appends stats to a CSV file after each successful upload."""

    FIELDNAMES = ['timestamp_iso', 'rsyncFiles', 'rsyncBytes', 'rsyncDuration']

    def __init__(self, path):
        self.path = path
        # Write header if file doesn't exist
        if not os.path.exists(self.path):
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, 'w', newline='') as f:
                    csv.DictWriter(f, fieldnames=self.FIELDNAMES).writeheader()
                log.info("rsync_metrics: created CSV file %s", self.path)
            except Exception as e:
                log.error("rsync_metrics: failed to create CSV file: %s", e)
        log.info("rsync_metrics: CSV output enabled -> %s", self.path)

    def handle(self, files, nbytes, duration):
        try:
            with open(self.path, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writerow({
                    'timestamp_iso': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                    'rsyncFiles':    files,
                    'rsyncBytes':    nbytes,
                    'rsyncDuration': duration,
                })
            log.debug("rsync_metrics: CSV <- files=%d bytes=%d duration=%.2fs",
                      files, nbytes, duration)
        except Exception as e:
            log.error("rsync_metrics: CSV write failed: %s", e)

    def shutdown(self):
        pass


class _MqttOutput:
    """Publishes stats as a JSON payload to an MQTT broker."""

    def __init__(self, host, port, user, password, tls,
                 topic, status_topic, client_id):
        self.topic        = topic
        self.status_topic = status_topic
        self._client      = None

        try:
            import paho.mqtt.client as mqtt

            self._client = mqtt.Client(
                client_id=client_id,
                protocol=mqtt.MQTTv5,
            )
            self._client.will_set(status_topic, payload='offline', retain=True)

            if user:
                self._client.username_pw_set(user, password)
            if tls:
                self._client.tls_set()

            self._client.connect(host, port, keepalive=60)
            self._client.loop_start()
            self._client.publish(status_topic, 'online', retain=True)
            log.info("rsync_metrics: MQTT output enabled -> %s:%d %s", host, port, topic)

        except ImportError:
            log.error("rsync_metrics: paho-mqtt not installed — "
                      "pip install paho-mqtt")
            self._client = None
        except Exception as e:
            log.error("rsync_metrics: MQTT connect failed: %s", e)
            self._client = None

    def handle(self, files, nbytes, duration):
        if not self._client:
            return
        payload = json.dumps({
            'rsyncFiles':    files,
            'rsyncBytes':    nbytes,
            'rsyncDuration': duration,
            'timestamp':     int(time.time()),
        })
        try:
            self._client.publish(self.topic, payload, qos=1)
            log.debug("rsync_metrics: MQTT <- %s", payload)
        except Exception as e:
            log.error("rsync_metrics: MQTT publish failed: %s", e)

    def shutdown(self):
        if self._client:
            try:
                self._client.publish(self.status_topic, 'offline', retain=True)
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Unit registration (used by archive output)
# ---------------------------------------------------------------------------

def _register_units():
    weewx.units.obs_group_dict['rsyncFiles']    = 'group_count'
    weewx.units.obs_group_dict['rsyncDuration'] = 'group_elapsed'
    weewx.units.obs_group_dict['rsyncBytes']    = 'group_data'

    if 'group_elapsed' not in weewx.units.USUnits:
        weewx.units.USUnits['group_elapsed']       = 'second'
        weewx.units.MetricUnits['group_elapsed']   = 'second'
        weewx.units.MetricWXUnits['group_elapsed'] = 'second'

    if 'group_data' not in weewx.units.USUnits:
        weewx.units.USUnits['group_data']            = 'byte'
        weewx.units.MetricUnits['group_data']        = 'byte'
        weewx.units.MetricWXUnits['group_data']      = 'byte'
        weewx.units.default_unit_label_dict['byte']  = ' B'
        weewx.units.default_unit_format_dict['byte'] = '%d'


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------

class RsyncMetricsService(StdService):
    """
    Captures rsync upload statistics via a logging handler and routes them
    to one or more configurable outputs: archive, csv, mqtt.

    Requires no changes to weewx core.
    """

    def __init__(self, engine, config_dict):
        super().__init__(engine, config_dict)

        cfg = config_dict.get('RsyncMetrics', {})
        outputs = [o.strip() for o in cfg.get('output', 'archive').split(',')]

        self.archive_interval = int(
            config_dict.get('StdArchive', {}).get('archive_interval', 300)
        )
        stale_threshold = self.archive_interval * 2

        # Build output handlers
        self._archive_output = None
        self._csv_output     = None
        self._mqtt_output    = None

        if 'archive' in outputs:
            self._archive_output = _ArchiveOutput(engine, stale_threshold)
            self.bind(weewx.NEW_ARCHIVE_RECORD, self.new_archive_record)

        if 'csv' in outputs:
            path = cfg.get('csv_path', '/var/log/weewx/rsync-metrics.csv')
            self._csv_output = _CsvOutput(path)

        if 'mqtt' in outputs:
            self._mqtt_output = _MqttOutput(
                host        = cfg.get('mqtt_host', 'localhost'),
                port        = int(cfg.get('mqtt_port', 1883)),
                user        = cfg.get('mqtt_user', ''),
                password    = cfg.get('mqtt_password', ''),
                tls         = cfg.get('mqtt_tls', 'false').lower() == 'true',
                topic       = cfg.get('mqtt_topic', 'weather/weewx/rsync/metrics'),
                status_topic= cfg.get('mqtt_status_topic', 'weather/weewx/rsync/status'),
                client_id   = cfg.get('mqtt_client_id', 'weewx-rsync-metrics'),
            )

        # Install the logging handler on weeutil.rsyncupload
        self._log_handler = _RsyncStatsHandler(
            callback_success=self._on_success,
            callback_failure=self._on_failure,
        )
        logging.getLogger('weeutil.rsyncupload').addHandler(self._log_handler)

        log.info("rsync_metrics: service started (outputs=%s stale_threshold=%ds)",
                 outputs, stale_threshold)

    # ------------------------------------------------------------------

    def _on_success(self, files, nbytes, duration):
        """Called from the logging handler on a successful upload."""
        _set_stats(files, nbytes, duration)

        if self._csv_output:
            self._csv_output.handle(files, nbytes, duration)

        if self._mqtt_output:
            self._mqtt_output.handle(files, nbytes, duration)

    def _on_failure(self):
        """Called from the logging handler on a failed upload."""
        _clear_stats()
        log.debug("rsync_metrics: upload failure detected, stats cleared")

    # ------------------------------------------------------------------

    def new_archive_record(self, event):
        if self._archive_output:
            self._archive_output.handle(_get_stats(), event)

    # ------------------------------------------------------------------

    def shutDown(self):
        # Remove the logging handler cleanly
        logging.getLogger('weeutil.rsyncupload').removeHandler(self._log_handler)

        if self._csv_output:
            self._csv_output.shutdown()
        if self._mqtt_output:
            self._mqtt_output.shutdown()

        log.info("rsync_metrics: service stopped")


# =============================================================================
# Manual schema migration (only if automatic ALTER TABLE fails)
# =============================================================================
#
# SQLite:
#   sqlite3 ~/weewx-data/archive/weewx.sdb
#   ALTER TABLE archive ADD COLUMN rsyncFiles    INTEGER;
#   ALTER TABLE archive ADD COLUMN rsyncBytes    INTEGER;
#   ALTER TABLE archive ADD COLUMN rsyncDuration REAL;
#
# MySQL:
#   ALTER TABLE archive ADD COLUMN rsyncFiles    INT;
#   ALTER TABLE archive ADD COLUMN rsyncBytes    INT;
#   ALTER TABLE archive ADD COLUMN rsyncDuration FLOAT;
#
# =============================================================================
