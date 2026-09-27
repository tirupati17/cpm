#!/usr/bin/env python3
"""Pause a campaign by id or exact name (dry run unless --commit).

The dry run asks Google to validate the change (validateOnly), so it also proves
the credentials can write before you commit.
"""
import _ads


def run(argv):
    return _ads.set_status(argv, 'PAUSED', __doc__)


if __name__ == '__main__':
    _ads.main(run)
