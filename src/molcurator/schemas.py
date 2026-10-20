# Shared data models (Pydantic) that every tool reads and writes; the contract between steps.
#
# Planned models:
#   Candidate     - a generated molecule: SMILES, parent/seed SMILES, generator name, agent step
#   PropertyValue - one property value from one method (chemprop / xtb / dft), with uncertainty
#   CuratedEntry  - a verified molecule: canonical SMILES, XYZ geometry,
#                   properties per method, provenance
#   PropertyTarget - target property name, threshold or range, units (loaded from configs/)
