"""Run the package's tests without a project: python runtests.py"""
import os
import sys

import django
from django.conf import settings
from django.test.utils import get_runner

if __name__ == '__main__':
    os.environ['DJANGO_SETTINGS_MODULE'] = 'tests.settings'
    django.setup()
    failures = get_runner(settings)().run_tests(['tests'])
    sys.exit(bool(failures))
