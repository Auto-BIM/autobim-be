"""DXF input path (issue #3). Until implemented, DXF jobs fail as not_implemented."""


def test_dxf_upload_is_routed_to_dxf_path(client):
    res = client.post("/api/jobs", files={"file": ("plan.dxf", b"0\nEOF\n", "application/dxf")})
    assert res.status_code == 202
    job = client.get(f"/api/jobs/{res.json()['id']}").json()
    assert job["input"]["type"] == "dxf"
    assert job["status"] == "failed" and job["error"]["code"] == "not_implemented"
