"""Run browser synchronization regressions as part of the deployment tests."""
from pathlib import Path
import shutil
import subprocess
import unittest


class BrowserSyncTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for browser synchronization tests')
    def test_synchronization_regressions(self):
        root = Path(__file__).resolve().parent.parent
        subprocess.run(['node', '--test', str(root / 'tests/sync.test.cjs')], cwd=root, check=True)
