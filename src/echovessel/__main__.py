"""Entry point for `python -m echovessel` and the `echovessel` console script."""

from echovessel.runtime.launcher import main

__all__ = ["main"]


if __name__ == "__main__":
    main()
