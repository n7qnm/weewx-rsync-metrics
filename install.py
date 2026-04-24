"""
install.py — weewx extension installer for rsync-metrics
"""

from weecfg.extension import ExtensionInstaller


def loader():
    return RsyncMetricsInstaller()


class RsyncMetricsInstaller(ExtensionInstaller):
    def __init__(self):
        super().__init__(
            version='0.1',
            name='rsync-metrics',
            description='Records rsync upload statistics as archive observations',
            author='Clay',
            author_email='',
            data_services='user.rsync_metrics.RsyncMetricsService',
            config={
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
                }
            },
            files=[
                ('bin/user', ['bin/user/rsync_metrics.py']),
            ],
        )
