"""Main entry point for running the EMR dummy job."""

from emr_dummy.debugging import attach_remote_debugger
from emr_dummy.job import main

if __name__ == "__main__":
    attach_remote_debugger()
    main()
