#!/usr/bin/env python3
"""List the customer ids these OAuth credentials can reach, with names and manager flags.

Use it to find GOOGLE_ADS_CUSTOMER_ID and, when access runs through a manager
(MCC), GOOGLE_ADS_LOGIN_CUSTOMER_ID. Needs the developer token and OAuth only.
"""
import _ads


def run(argv, client=None):
    p = _ads.parser(__doc__)
    args = p.parse_args(argv)
    # listAccessibleCustomers needs no customer id, so none is asked for.
    client = client or _ads.Client(args.customer or '0')
    reply = client.call('GET', 'customers:listAccessibleCustomers')
    rows = []
    for resource in reply.get('resourceNames') or []:
        cid = resource.rsplit('/', 1)[-1]
        row = {'id': cid, 'name': '', 'manager': '', 'currency': '', 'status': ''}
        client.customer = cid
        try:
            found = client.search('SELECT customer.descriptive_name, customer.manager, '
                                  'customer.currency_code, customer.status FROM customer')
        except SystemExit as err:
            row['status'] = str(err).splitlines()[0][:60]
            found = []
        if found:
            info = found[0]
            row.update(name=_ads.pick(info, 'customer.descriptive_name'),
                       manager='yes' if _ads.pick(info, 'customer.manager') is True else '',
                       currency=_ads.pick(info, 'customer.currency_code'),
                       status=_ads.pick(info, 'customer.status'))
        rows.append(row)
    print(_ads.google.table(rows, ['id', 'name', 'manager', 'currency', 'status'],
                            ['ID', 'NAME', 'MANAGER', 'CURRENCY', 'STATUS']))
    return 0


if __name__ == '__main__':
    _ads.main(run)
