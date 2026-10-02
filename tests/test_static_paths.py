import os
from airlock.api import ConsoleAssets,STATIC


def test_static_unc_path_rejected_before_filesystem_resolution(monkeypatch):
    original=os.path.realpath;seen=[]
    def guarded(path,*args,**kwargs):
        seen.append(str(path))
        assert not str(path).startswith(('\\\\','//'))
        return original(path,*args,**kwargs)
    monkeypatch.setattr(os.path,'realpath',guarded)
    assets=ConsoleAssets(directory=STATIC)
    # No network calls are made by this test. The patched resolver would fail first.
    result=assets.lookup_path('\\\\untrusted.invalid\\share\\file.js')
    assert result==('',None)
