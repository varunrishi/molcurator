from pathlib import Path
import molcurator_property_validation
import molcurator.schemas


def test_shared_contract_and_isolated_implementation_paths():
    subproject = Path(__file__).resolve().parents[1]
    assert Path(molcurator_property_validation.__file__).resolve().is_relative_to(subproject)
    assert not Path(molcurator.schemas.__file__).resolve().is_relative_to(subproject)
