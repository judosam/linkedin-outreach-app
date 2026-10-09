import tarfile
import os

include_dirs = ['app', 'static', 'templates', 'cookies_files', 'scripts']
include_files = [
    'requirements.txt', '.env', 'pipeline_common.py', 'campaigns.py',
    'get_cookies.py', 'salesApiConnection.py', 'salesApiLeadSearch.py',
    'salesApiMessagingThreadsCheckingReplies.py',
    'salesApiMessagingThreadsSendMessages.py', 'salesApiSavedSearch.py',
    'email_notifier.py', 'gchat_notifier.py', 'notification_format.py'
]

archive_path = 'deploy_package.tar.gz'
with tarfile.open(archive_path, 'w:gz') as tar:
    for d in include_dirs:
        if os.path.exists(d):
            tar.add(d)
    for f in include_files:
        if os.path.exists(f):
            tar.add(f)
    if os.path.exists('app_data/app_data.db'):
        tar.add('app_data/app_data.db')

size_mb = os.path.getsize(archive_path) / (1024 * 1024)
print(f"Package created: {archive_path} ({size_mb:.2f} MB)")
