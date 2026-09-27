#!/usr/bin/env python3
"""App settings and subscriber counts, and whether iOS and Android push are configured.

    cpm onesignal app
    cpm onesignal app --json

Needs ONESIGNAL_ORG_API_KEY: viewing an app is an organization-level call, and
an app REST key is refused. `players` is every subscription ever registered;
`messageable_players` is how many can receive a push right now.
"""
import argparse

import _onesignal as os1
from cpmkit import creds, http


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cpm onesignal app', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--json', action='store_true', help='print the raw API response')
    args = parser.parse_args(argv)

    app_id = os1.app_id()
    key = creds.get('ONESIGNAL_ORG_API_KEY')
    if not key:
        raise SystemExit('`cpm onesignal app` needs the organization key: '
                         'cpm creds set ONESIGNAL_ORG_API_KEY  (OneSignal > Organization > Keys & IDs)')
    try:
        app = os1.call('GET', f'/apps/{app_id}', key=key)
    except http.ApiError as err:
        if err.status in (401, 403):
            raise SystemExit(f'{err.message}\nThe key was refused. This call needs an organization '
                             '(User Auth) key, not the app REST key.') from None
        raise
    if args.json:
        os1.dump(app)
        return 0
    ios = bool(app.get('apns_env') and (app.get('apns_certificates') or app.get('apns_p8') or app.get('apns_key_id')))
    android = bool(app.get('gcm_key') or app.get('fcm_v1_service_account_json') or app.get('android_gcm_sender_id'))
    rows = [('name', app.get('name', '')), ('id', app.get('id', app_id)),
            ('players', app.get('players', '')), ('messageable', app.get('messageable_players', '')),
            ('iOS push (APNs)', f"yes ({app.get('apns_env')})" if ios else 'NOT configured'),
            ('Android push (FCM)', 'yes' if android else 'NOT configured'),
            ('web push', 'yes' if app.get('chrome_web_origin') or app.get('site_name') else 'no'),
            ('updated', app.get('updated_at', ''))]
    for label, value in rows:
        print(f'{label:<20} {value}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
