# VALIDATE: confirm screened candidates with higher-accuracy quantum chemistry.
#
# Backends: PySCF (default) or ORCA (optional, external binary).
#   - DFT for HOMO / LUMO / gap
#   - TD-DFT for S1 and T1 energies (S1-T1 gap for the TADF use case)
# Input geometries come from PREDICT (xTB-optimised).
# Output: PropertyValue entries with method "dft" / "tddft".
