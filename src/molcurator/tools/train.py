# TRAIN: train / retrain the ML property model on the growing dataset.
#
# Uses ChemProp v2 (ensemble of models, so predictions come with an uncertainty estimate).
# Also provides the screening step: predict the property for new candidates and keep the
# ones that meet the target threshold, ranked by uncertainty for VALIDATE.
