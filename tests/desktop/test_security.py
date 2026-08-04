import importlib
import sys


def test_objectid_has_no_bson_dependency(monkeypatch):
    sys.modules.pop("app.utils.objectid", None)
    monkeypatch.setitem(sys.modules, "bson", None)
    mod = importlib.import_module("app.utils.objectid")
    value = mod.new_id()
    assert len(value) == 24
    assert mod.validate_id(value) == value


def test_storage_package_does_not_import_imagekitio_on_local_import(monkeypatch):
    sys.modules.pop("app.services.storage", None)
    sys.modules.pop("app.services.storage.local", None)
    monkeypatch.setitem(sys.modules, "imagekitio", None)
    from app.services.storage.local import LocalImageStorage

    assert LocalImageStorage
