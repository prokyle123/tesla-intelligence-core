"""Private source-bundle allowlist and secret-check regression tests."""
from pathlib import Path
import importlib.util
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('v2_export',ROOT/'scripts/v2_source_export.py')
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
class ExportTests(unittest.TestCase):
    def test_source_only(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            (p/'safe.py').write_text('print("hello")')
            (p/'private.env').write_text('token=secret')
            with patch.object(mod,'sources',return_value=(('core',p),)):
                r=mod.build(p,p/'review.zip')
            self.assertTrue(r['created'])
            import zipfile
            with zipfile.ZipFile(p/'review.zip') as z:
                self.assertEqual(set(z.namelist()),{'sources/core/safe.py','manifest.json'})
    def test_block_embedded_secret_without_creating_zip(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            (p/'safe.py').write_text('print("hello")')
            (p/'unsafe.py').write_text('access_token = "some-secret-private-value-123"\n')
            with patch.object(mod,'sources',return_value=(('core',p),)):
                r=mod.build(p,p/'review.zip')
            self.assertFalse(r['created'])
            self.assertEqual(r['blocked'][0]['path'],'core/unsafe.py')
            self.assertFalse((p/'review.zip').exists())
    def test_installed_unit_source_copied_with_no_inline_secret(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            (p/'safe.py').write_text('print(1)')
            with patch.object(mod,'sources',return_value=(('core',p),)), \
                 patch.object(mod,'installed_service_sources',
                              return_value=[('systemd-live/ghost-v66-watchdog.service.txt',
                                             b'[Service]\\nExecStart=/usr/bin/python3 /opt/ghost-intelligence/watchdog.py\\n')]):
                r=mod.build(p,p/'units.zip')
            self.assertTrue(r['created'])
            import zipfile
            with zipfile.ZipFile(p/'units.zip') as z:
                self.assertIn('sources/systemd-live/ghost-v66-watchdog.service.txt',z.namelist())

    def test_inline_unit_credential_cancels_export(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            (p/'safe.py').write_text('print(1)')
            with patch.object(mod,'sources',return_value=(('core',p),)), \
                 patch.object(mod,'installed_service_sources',
                              return_value=[('systemd-live/private.service.txt',
                                             b'Environment=TESLA_API_KEY=some_private_value\\n')]):
                r=mod.build(p,p/'blocked.zip')
            self.assertFalse(r['created'])
            self.assertFalse((p/'blocked.zip').exists())

    def test_explicit_partial_export_excludes_all_flagged_source_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            (p/'safe.py').write_text('print("approved source")')
            (p/'unsafe.py').write_text('access_token = "some-secret-private-value-123"\n')
            with patch.object(mod,'sources',return_value=(('core',p),)), \
                 patch.object(mod,'installed_service_sources',return_value=[]):
                r=mod.build(p,p/'partial.zip',allow_incomplete=True)
            self.assertTrue(r['created'])
            self.assertTrue(r['incomplete_due_to_blocked_files'])
            self.assertEqual(r['blocked_paths_not_included'][0]['path'],'core/unsafe.py')
            import json, zipfile
            with zipfile.ZipFile(p/'partial.zip') as z:
                self.assertEqual(set(z.namelist()),
                                 {'sources/core/safe.py','manifest.json'})
                self.assertNotIn('some-secret-private-value',str(z.namelist()))
                manifest=json.loads(z.read('manifest.json'))
                self.assertTrue(manifest['incomplete_due_to_blocked_files'])
                self.assertFalse('some-secret-private-value' in str(manifest))

    def test_diagnostics_only_print_category_and_line_number(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            (p/'file.py').write_text('access_token = "some-secret-private-value-123"\n')
            with patch.object(mod,'sources',return_value=(('core',p),)), \
                 patch.object(mod,'installed_service_sources',return_value=[]):
                d=mod.blocked_diagnostics(p)
            self.assertEqual(d[0]['path'],'core/file.py')
            self.assertEqual(d[0]['matches'][0]['category'],
                             'possible_hardcoded_credential')
            self.assertEqual(d[0]['matches'][0]['first_line_numbers'],[1])
            self.assertNotIn('some-secret-private-value',str(d))

    def test_no_output_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            (p/'safe.py').write_text('print(1)')
            (p/'review.zip').write_text('previous')
            with patch.object(mod,'sources',return_value=(('core',p),)):
                with self.assertRaisesRegex(ValueError,'already exists'):
                    mod.build(p,p/'review.zip')
if __name__=='__main__':
    unittest.main()
