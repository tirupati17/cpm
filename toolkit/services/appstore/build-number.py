#!/usr/bin/env python3
"""Ask App Store Connect what the next build number is.

    cpm appstore build-number                  # prints one integer
    cpm appstore build-number --bundle-id com.example.App

Asking rather than counting, because App Store Connect is the only system that
knows. A local counter, a file in the repo, or the CI run number can all drift
from what was actually accepted, and each of them drifts silently. A project
that pins CURRENT_PROJECT_VERSION and never bumps it has every upload after the
first rejected as a duplicate, after a full archive has already run: twenty
minutes to be told a number.

Prints one integer on stdout. Exits non-zero with a reason on stderr if it
cannot find out, which is deliberate: guessing here costs an archive, and a
build number that collides is indistinguishable from a broken upload.

Credentials: ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH, ASC_BUNDLE_ID (read-only use).
"""
import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--bundle-id', help='app bundle id (default: ASC_BUNDLE_ID credential)')
    args = parser.parse_args(argv)

    import _asc
    bundle_id = _asc.resolve_bundle_id(args.bundle_id)
    asc = _asc.ASC()
    app_id, _ = asc.app(bundle_id)
    print(asc.next_build_number(app_id))


if __name__ == '__main__':
    sys.exit(main())
