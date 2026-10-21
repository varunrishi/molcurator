import pathlib, py_compile, csv
R=pathlib.Path(__file__).resolve().parents[1]
def test_all_python_compile():
    for f in R.glob('workflows/**/*.py'):py_compile.compile(str(f),doraise=True)
    for f in (R/'scripts').glob('*.py'):py_compile.compile(str(f),doraise=True)
def test_example_valid():
    with (R/'examples/iteration1_validation.csv').open() as f:
        rows=list(csv.DictReader(f))
    assert len(rows)==8
    assert all(float(r['orca_s1_ev'])>4.7 for r in rows)
def test_external_function_fixed():
    s=(R/'workflows/multifidelity_next/benchmark_next.py').read_text()
    assert "validate_external(a.external,a.training,a.frozen,a.benchmark,a.benchmark,a.out/'external48')" in s
