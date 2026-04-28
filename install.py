"""
install.py — weewx extension installer for rsync-metrics
"""

from weecfg.extension import ExtensionInstaller


def loader():
    return RsyncMetricsInstaller()


class RsyncMetricsInstaller(ExtensionInstaller):
    def __init__(self):
        super().__init__(
            version='0.2',
            name='rsync-metrics',
            description='Captures rsync upload statistics via logging handler. '
                        'No core patches required. Outputs to archive DB, CSV, and/or MQTT.',
            author='Clay (N7QNM)',
            author_email='',
            data_services='user.rsync_metrics.RsyncMetricsService',
            config={
                'RsyncMetrics': {
                    'output': 'archive',
                    'csv_path': '/var/log/weewx/rsync-metrics.csv',
                    'mqtt_host': 'localhost',
                    'mqtt_port': '1883',
                    'mqtt_user': '',
                    'mqtt_password': '',
                    'mqtt_tls': 'false',
                    'mqtt_topic': 'weather/weewx/rsync/metrics',
                    'mqtt_status_topic': 'weather/weewx/rsync/status',
                    'mqtt_client_id': 'weewx-rsync-metrics',
                },
                'StdReport': {
                    'Defaults': {
                        'Labels': {
                            'Generic': {
                                'rsyncFiles':    'ISP Upload Files',
                                'rsyncBytes':    'ISP Upload Size',
                                'rsyncDuration': 'ISP Upload Duration',
                            }
                        }
                    }
                },
            },
            files=[
                ('bin/user', ['bin/user/rsync_metrics.py']),
            ],
        )
