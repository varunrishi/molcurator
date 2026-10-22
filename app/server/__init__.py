"""HTTP API around the MolCurator agent (the `server` package: app/server, imported with app/ on the path).

The agent itself is unchanged: this package starts it as a separate process (the existing
`molcurator run` command) and reads the files each run writes to its folder
(`data/runs/<run_id>/`). See app/server/README.md and docs/api/.
"""

__version__ = "0.1.0"
