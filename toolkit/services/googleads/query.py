#!/usr/bin/env python3
"""Run any GAQL query (searchStream) and print the rows as a table.

Field names are the GAQL ones (snake_case), e.g.
  cpm googleads query "SELECT campaign.name, metrics.clicks FROM campaign WHERE segments.date DURING LAST_7_DAYS"
Money fields come back in micros (1,000,000 = one unit of the account currency).
Use --json for the raw rows.
"""
import json

import _ads


def run(argv, client=None):
    p = _ads.parser(__doc__)
    p.add_argument('gaql', help='the GAQL query, quoted')
    p.add_argument('--json', action='store_true', help='print the raw rows as JSON')
    args = p.parse_args(argv)
    client = client or _ads.Client(args.customer)
    rows = client.search(args.gaql)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    fields = _ads.selected_fields(args.gaql)
    flat = [{f: _cell(_ads.pick(row, f)) for f in fields} for row in rows]
    print(_ads.google.table(flat, fields))
    print(f'\n{len(rows)} row(s)')
    return 0


def _cell(value):
    return json.dumps(value) if isinstance(value, (dict, list)) else value


if __name__ == '__main__':
    _ads.main(run)
