"""Tests for src/molcurator/chem/audit.py.

The 8 candidates below are from subprojects/property_validation_v1/examples/
iteration1_validation.csv (columns molecule_id, smiles), which has since been
deleted from the working tree. The SMILES are quoted from that file verbatim.

The real qm9_0023 seed SMILES is NOT in the repo (it lives in an external
qm9_100/molecules.csv data file). design_0001 has similarity_to_seed=1.0000
in the original results, so we use design_0001's SMILES as the seed stand-in
for the seed-identity tests only.
"""
import pytest

from molcurator.chem.audit import audit_candidates

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CANDIDATES = {
    "design_0009": "O=C1OC[C@H]1NN1CC1",
    "design_0001": "O=C1OCC1NC1CC1",
    "design_0005": "O=C1OC[C@H]1NC1CN1",
    "design_0058": "O=C1OC[C@H]1OC1CN1",
    "design_0015": "O=C1ON[C@H]1NC1CC1",
    "design_0037": "O=C1ON[C@H]1NC1CO1",
    "design_0012": "O=C1OC[C@H]1NN1CN1",
    "design_0004": "O=C1OC[C@H]1NC1NN1",
}

# Stand-in seed: design_0001's own SMILES (similarity_to_seed=1.0 in the
# original results). The real qm9_0023 SMILES is not in the repo.
SEED_SMILES = CANDIDATES["design_0001"]


@pytest.fixture
def result():
    return audit_candidates(SEED_SMILES, CANDIDATES)


# ---------------------------------------------------------------------------
# Validity and parse
# ---------------------------------------------------------------------------


def test_all_eight_parse(result):
    for cid, r in result["candidates"].items():
        assert r["valid"], f"{cid} should parse"


def test_invalid_smiles_flagged():
    out = audit_candidates(SEED_SMILES, {"bad": "C1CC"})
    assert not out["candidates"]["bad"]["valid"]
    assert out["candidates"]["bad"]["canonical_smiles"] is None
    assert out["candidates"]["bad"]["tanimoto_to_seed"] is None
    assert out["summary"]["n_invalid"] == 1


# ---------------------------------------------------------------------------
# Seed identity
# ---------------------------------------------------------------------------


def test_seed_identical_exact(result):
    # design_0001 IS the seed stand-in, so exact and stereo-free both match.
    assert result["candidates"]["design_0001"]["same_as_seed_exact"]
    assert result["candidates"]["design_0001"]["same_as_seed_ignoring_stereo"]


def test_others_not_seed_identical_exact(result):
    for cid, r in result["candidates"].items():
        if cid != "design_0001":
            assert not r["same_as_seed_exact"], f"{cid} should not be exact seed"


def test_others_not_seed_identical_ignoring_stereo(result):
    # None of the other 7 should share the seed's stereo-free scaffold.
    for cid, r in result["candidates"].items():
        if cid != "design_0001":
            assert not r["same_as_seed_ignoring_stereo"], (
                f"{cid} unexpectedly matches seed ignoring stereo"
            )


def test_stereoisomer_of_seed_flagged():
    # design_0001 has no stereocentre; construct an explicit stereoisomer of
    # O=C1OCC1NC1CC1 by using its @-marked variant. We confirm it matches
    # ignoring stereo but not as an exact match.
    seed = "O=C1OCC1NC1CC1"
    stereo_variant = "O=C1OC[C@@H]1NC1CC1"
    out = audit_candidates(seed, {"stereo": stereo_variant})
    r = out["candidates"]["stereo"]
    assert r["valid"]
    assert r["same_as_seed_ignoring_stereo"]
    assert not r["same_as_seed_exact"]


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------


def test_no_intra_batch_duplicates(result):
    for cid, r in result["candidates"].items():
        assert r["duplicate_of"] is None, f"{cid} flagged as duplicate"


def test_duplicate_detected():
    # Pass the same non-seed SMILES twice; the second entry should be flagged.
    # Use a seed that differs from the duplicated SMILES so the duplicate logic
    # is exercised independently of seed-identity logic.
    seed = "c1ccccc1"          # benzene as seed
    smi = "O=C1OCC1NC1CC1"    # not the seed
    out = audit_candidates(seed, {"a": smi, "b": smi})
    assert out["candidates"]["a"]["duplicate_of"] is None
    assert out["candidates"]["b"]["duplicate_of"] == "a"
    assert out["summary"]["n_duplicate"] == 1


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------


def test_summary_counts(result):
    s = result["summary"]
    assert s["n_total"] == 8
    assert s["n_invalid"] == 0
    # n_seed_identical counts same_as_seed_ignoring_stereo; design_0001 qualifies
    assert s["n_seed_identical"] == 1
    assert s["n_duplicate"] == 0
    # 7 valid, not seed-identical (ignoring stereo), not duplicate
    assert s["n_unique_new"] == 7
    # partition: n_total == sum of four categories
    assert s["n_total"] == s["n_invalid"] + s["n_seed_identical"] + s["n_duplicate"] + s["n_unique_new"]


def test_tanimoto_range(result):
    for cid, r in result["candidates"].items():
        t = r["tanimoto_to_seed"]
        assert 0.0 <= t <= 1.0, f"{cid} tanimoto out of range: {t}"


def test_tanimoto_seed_to_itself():
    smi = "O=C1OCC1NC1CC1"
    out = audit_candidates(smi, {"self": smi})
    assert out["candidates"]["self"]["tanimoto_to_seed"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Stereo seed vs stereo-free candidate (new Change 1 test)
# ---------------------------------------------------------------------------


def test_stereo_seed_noiso_match_counted_in_seed_identical():
    # Seed has a stereocentre; candidate is the same scaffold without stereo.
    # same_as_seed_ignoring_stereo must be True, counted in n_seed_identical.
    seed = "O=C1OC[C@H]1NC1CC1"       # stereo seed
    candidate = "O=C1OCC1NC1CC1"       # same scaffold, no stereocentre
    out = audit_candidates(seed, {"flat": candidate})
    r = out["candidates"]["flat"]
    assert r["valid"]
    assert r["same_as_seed_ignoring_stereo"]
    assert not r["same_as_seed_exact"]
    assert out["summary"]["n_seed_identical"] == 1
    # partition holds for this single-candidate result
    s = out["summary"]
    assert s["n_total"] == s["n_invalid"] + s["n_seed_identical"] + s["n_duplicate"] + s["n_unique_new"]


# ---------------------------------------------------------------------------
# Invalid inputs: non-str, empty, whitespace (new Change 2 tests)
# ---------------------------------------------------------------------------


def test_none_flagged_invalid():
    out = audit_candidates(SEED_SMILES, {"null": None})
    r = out["candidates"]["null"]
    assert not r["valid"]
    assert r["canonical_smiles"] is None
    assert r["tanimoto_to_seed"] is None
    assert out["summary"]["n_invalid"] == 1


def test_empty_string_flagged_invalid():
    out = audit_candidates(SEED_SMILES, {"empty": ""})
    assert not out["candidates"]["empty"]["valid"]
    assert out["summary"]["n_invalid"] == 1


def test_whitespace_string_flagged_invalid():
    out = audit_candidates(SEED_SMILES, {"ws": "   "})
    assert not out["candidates"]["ws"]["valid"]
    assert out["summary"]["n_invalid"] == 1


def test_mixed_invalid_valid():
    # Counts accumulate correctly when some candidates are invalid.
    out = audit_candidates(SEED_SMILES, {"ok": SEED_SMILES, "bad": "", "null": None})
    s = out["summary"]
    assert s["n_invalid"] == 2
    assert s["n_seed_identical"] == 1
    assert s["n_total"] == s["n_invalid"] + s["n_seed_identical"] + s["n_duplicate"] + s["n_unique_new"]


# ---------------------------------------------------------------------------
# Invalid seed values (parametrized)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_seed", ["", "   ", None, "not_a_smiles"])
def test_bad_seed_raises(bad_seed):
    with pytest.raises(ValueError):
        audit_candidates(bad_seed, {"c": "c1ccccc1"})
