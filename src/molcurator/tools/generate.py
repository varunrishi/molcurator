# GENERATE: create new candidate molecules from a seed molecule.
#
# Backends:
#   - STONED SELFIES (default): random SELFIES mutations and interpolation around the seed
#   - Mol2Mol (REINVENT4, optional): pretrained model that samples similar molecules
# Output: list of Candidate (schemas.py), sanitised and deduplicated with RDKit.
