# weewx-rsync-metrics
Service to record rsync upload metrics in an archive records.   Adds three columns, rsync_files, rsync_bytes and rsync_duration to the archiive table.  These can be used to track rync performance overm time and passed to a monitoring process like Zabbix to alert if too slow.

Requires changes to rsyncupload.py and reportengine.py that have been submitted as a pull request to weewx 5.3.1

To use:
  weectl extension install weewx-rsync-metrics.tar.gz
  add "record_stats = true" to the [rsync] stanza in weewx.conf
  
