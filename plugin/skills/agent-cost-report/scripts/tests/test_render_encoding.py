"""Native file rendering under the Windows Chinese code page."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _paths


class NativeEncoding(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows code-page regression")
    def test_html_output_is_utf8_with_cp936_process_locale(self):
        fixture = Path(_paths.FIXTURES) / "report-empty.json"
        data = json.loads(fixture.read_text(encoding="utf-8"))
        # A valid empty single-session report has no period date labels.
        # This isolates file encoding from the separate Windows strftime defect.
        data["scope"]["kind"] = "session"
        data["window"]["start_pt"] = None
        data["by_day"] = []
        data["timeline"] = {"wins_by_day": [], "mistakes_by_day": []}
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "report.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            script = """
import locale, pathlib, sys
sys.path.insert(0, sys.argv[1])
from acr import render
locale.setlocale(locale.LC_CTYPE, ".936")
assert locale.getencoding().lower() == "cp936", locale.getencoding()
for print_mode in (False, True):
    path = render.render_file(sys.argv[2], sys.argv[3], print_mode=print_mode)
    text = pathlib.Path(path).read_text(encoding="utf-8")
    assert '<meta charset="utf-8">' in text
    assert '‹' in text and '›' in text
"""
            process = subprocess.run(
                [sys.executable, "-X", "utf8=0", "-c", script, _paths.SCRIPTS, str(source), folder],
                capture_output=True, env=dict(os.environ, PYTHONUTF8="0"),
            )
            self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace"))
