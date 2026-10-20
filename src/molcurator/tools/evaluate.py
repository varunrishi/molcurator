# EVALUATE: score the agent's trajectories and tool calls.
#
# Reads the LangGraph traces saved in data/runs/<run_id>/traces/ and reports metrics such as:
#   - share of curated molecules that meet the target at the QM level (hit rate)
#   - number of expensive QM calls per curated molecule
#   - invalid or redundant tool calls, failed steps
