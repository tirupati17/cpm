#!/usr/bin/env python3
"""Enable a paused campaign by id or exact name (dry run unless --commit).

Enabling starts spending at the campaign's current budget. Check it first with
`cpm googleads campaigns`.
"""
import _ads


def run(argv):
    return _ads.set_status(argv, 'ENABLED', __doc__)


if __name__ == '__main__':
    _ads.main(run)
