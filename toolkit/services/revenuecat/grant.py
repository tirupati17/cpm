#!/usr/bin/env python3
"""Grant an entitlement for free (promotional), for a duration or until a date.

    cpm revenuecat grant <app_user_id> <entitlement> --duration monthly            # dry run
    cpm revenuecat grant <app_user_id> <entitlement> --duration monthly --commit
    cpm revenuecat grant <app_user_id> <entitlement> --until 2027-01-31 --commit
    cpm revenuecat grant <app_user_id> <entitlement> --duration lifetime --commit  # uses v1

<entitlement> is the lookup key (the identifier you created), its entl... id,
or its display name.

Which API: v2 `POST .../customers/{id}/actions/grant_entitlement` for anything
with an end date. v2 only takes an `expires_at`, so a lifetime grant goes to v1
`POST /v1/subscribers/{id}/entitlements/{identifier}/promotional` with
`duration: lifetime`, the one call here v2 has no equal for. --api forces one.

A grant is not a purchase: no store transaction, no revenue, no webhook
INITIAL_PURCHASE, and it does not show in the store's own records. Refunds and
store-side cancellations cannot remove it; revoke it in the dashboard (customer
page > Entitlements) or with the v2 revoke_granted_entitlement action.
"""
import argparse
import calendar
import datetime

import _revenuecat as rc

MONTHS = {'monthly': 1, 'two_month': 2, 'three_month': 3, 'six_month': 6, 'yearly': 12}
DAYS = {'daily': 1, 'three_day': 3, 'weekly': 7}
DURATIONS = list(DAYS) + list(MONTHS) + ['lifetime']


def add_months(moment, months):
    month = moment.month - 1 + months
    year, month = moment.year + month // 12, month % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def expiry(duration, until, now):
    if until:
        try:
            end = datetime.datetime.strptime(until, '%Y-%m-%d').replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            raise SystemExit(f'--until wants YYYY-MM-DD, not {until!r}') from None
        end = end.replace(hour=23, minute=59, second=59)
    elif duration in DAYS:
        end = now + datetime.timedelta(days=DAYS[duration])
    else:
        end = add_months(now, MONTHS[duration])
    if end <= now:
        raise SystemExit(f'{until} is not in the future.')
    return end


def main(argv=None, now=None):
    parser = argparse.ArgumentParser(prog='cpm revenuecat grant', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('app_user_id')
    parser.add_argument('entitlement')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--duration', choices=DURATIONS)
    group.add_argument('--until', help='end date YYYY-MM-DD (UTC, end of that day)')
    parser.add_argument('--api', choices=['auto', 'v1', 'v2'], default='auto',
                        help='auto: v1 for lifetime, v2 otherwise')
    parser.add_argument('--commit', action='store_true', help='grant it; without this nothing is sent')
    args = parser.parse_args(argv)

    now = now or datetime.datetime.now(datetime.timezone.utc)
    api = args.api
    if api == 'auto':
        api = 'v1' if args.duration == 'lifetime' else 'v2'
    if api == 'v2' and args.duration == 'lifetime':
        raise SystemExit('v2 grants need an end date; use --api v1 (or auto) for lifetime, or --until.')

    entitlement = rc.resolve_entitlement(args.entitlement)
    customer = rc.quote(args.app_user_id)
    if api == 'v2':
        end = expiry(args.duration, args.until, now)
        path = f'/customers/{customer}/actions/grant_entitlement'
        body = {'entitlement_id': entitlement['id'], 'expires_at': int(end.timestamp() * 1000)}
        shown = f"POST /v2/projects/<project>{path}"
        until = end.strftime('%Y-%m-%d %H:%M UTC')
    else:
        identifier = entitlement.get('lookup_key') or args.entitlement
        path = f'/subscribers/{customer}/entitlements/{rc.quote(identifier)}/promotional'
        if args.until:
            end = expiry(None, args.until, now)
            body = {'end_time_ms': int(end.timestamp() * 1000)}
            until = end.strftime('%Y-%m-%d %H:%M UTC')
        else:
            body = {'duration': args.duration}
            until = args.duration
        shown = f'POST /v1{path}'

    print(f"grant    {entitlement.get('lookup_key') or entitlement['id']} ({entitlement['id']})")
    print(f'to       {args.app_user_id}')
    print(f'until    {until}')
    print(f'call     {shown}')
    print(f'body     {body}')
    if not args.commit:
        print('\nDRY RUN. Nothing granted. Re-run with --commit.')
        return 0
    if api == 'v2':
        rc.v2('POST', path, body=body)
    else:
        rc.v1('POST', path, body=body)
    print('\nGranted. Check it with: cpm revenuecat customer ' + args.app_user_id)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
