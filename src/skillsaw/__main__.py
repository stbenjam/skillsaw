"""Entry point for skillsaw (and claudelint backward-compat shim)"""

from .cli import main, claudelint_shim

if __name__ == "__main__":
    main()
