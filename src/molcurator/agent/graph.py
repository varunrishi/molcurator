# LangGraph graph definition: nodes, edges and stopping conditions.
#
# Loop: GENERATE -> PREDICT / screen (ML + threshold + uncertainty) -> VALIDATE (QM)
#       -> CURATE -> TRAIN (retrain on the grown dataset) -> back to GENERATE
# The LLM decides the next step and its arguments; the loop stops when the target dataset
# size or the compute budget is reached.
