# CURATE: add verified molecules to the benchmark dataset.
#
# Writes CuratedEntry records (SMILES, XYZ structure, properties from every method,
# provenance) to the run folder data/runs/<run_id>/, e.g. dataset.csv + xyz/ files.
# Also handles deduplication against molecules already in the dataset.
