import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from molcurator.visualization import read_xyz, render_xyz_html, export_prediction_gallery

XYZ = "2\nH2\nH 0 0 0\nH 0 0 0.74\n"


class FakeView:
    def addModel(self, text, fmt):
        assert fmt == "xyz" and text == XYZ
    def setStyle(self, style):
        assert "stick" in style
    def setBackgroundColor(self, color):
        assert color == "white"
    def zoomTo(self):
        pass
    def _make_html(self):
        return "<div>MOCKED-3DMOL-VIEWER</div>"


def fake_py3dmol(monkeypatch):
    monkeypatch.setitem(sys.modules, "py3Dmol", SimpleNamespace(view=lambda **kwargs: FakeView()))


def test_xyz_validation(tmp_path):
    xyz = tmp_path / "h2.xyz"
    xyz.write_text(XYZ)
    assert read_xyz(xyz) == XYZ
    for invalid in ("", "two\nwrong", "1\nH\nH nan 0 0\n", "1\nH\nXx 0 0 0\n"):
        xyz.write_text(invalid)
        with pytest.raises(ValueError):
            read_xyz(xyz)


def test_html_export_escapes_title_and_uses_xyz(tmp_path, monkeypatch):
    fake_py3dmol(monkeypatch)
    xyz = tmp_path / "h2.xyz"
    xyz.write_text(XYZ)
    output = render_xyz_html(xyz, tmp_path / "viewer.html", title="<test>")
    html = output.read_text()
    assert "MOCKED-3DMOL-VIEWER" in html
    assert "&lt;test&gt;" in html
    assert "<test>" not in html


def test_gallery_keeps_failed_candidates_and_ids(tmp_path, monkeypatch):
    fake_py3dmol(monkeypatch)
    xyz = tmp_path / "h2.xyz"
    xyz.write_text(XYZ)
    predictions = [
        {"candidate_id":"good", "status":"ok", "value":3.2, "xyz_path":str(xyz)},
        {"candidate_id":"bad", "status":"failed", "value":None, "error":"embedding"},
        {"candidate_id":"missing", "status":"ok", "value":2.3, "xyz_path":str(tmp_path/'none.xyz')},
    ]
    result = export_prediction_gallery(predictions, tmp_path / "gallery")
    assert result["total"] == 3 and result["viewers_generated"] == 1
    assert [x["candidate_id"] for x in result["records"]] == ["good", "bad", "missing"]
    assert result["records"][0]["viewer_file"] == "molecule_0000.html"
    assert result["records"][1]["viewer_file"] is None
    assert "viewer_error" in result["records"][2]
    assert json.loads((tmp_path / "gallery/index.json").read_text())["total"] == 3
