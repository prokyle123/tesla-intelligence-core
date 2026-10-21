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
