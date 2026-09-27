"""Shared plumbing for the googleads commands: REST client, GAQL, campaign lookup, writes."""
import argparse
import datetime
import os
import re
import sys

from cpmkit import creds, google

# One place for the API version. Google releases a new one every few months and
# sunsets each about a year later; a 404 on every call usually means this is too old.
# GOOGLE_ADS_API_VERSION overrides it without editing code.
API_VERSION = 'v22'
HOST = 'https://googleads.googleapis.com'
SCOPE = 'https://www.googleapis.com/auth/adwords'


def version():
    return os.environ.get('GOOGLE_ADS_API_VERSION') or API_VERSION


def clean_id(value, name='customer id'):
    """'123-456-7890' -> '1234567890'. Google Ads ids are 10 digits; dashes are display only."""
    digits = re.sub(r'[\s-]', '', str(value or ''))
    if not digits.isdigit():
        raise SystemExit(f'{name} {value!r} is not a Google Ads id (10 digits, dashes optional).')
    return digits


def parser(description):
    first = (description or '').strip().splitlines()[0]
    p = argparse.ArgumentParser(description=first, formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog='\n'.join((description or '').strip().splitlines()[1:]))
    p.add_argument('--customer', help='customer id to act on (default GOOGLE_ADS_CUSTOMER_ID)')
    return p


class Client:
    def __init__(self, customer=None, token=None):
        self.developer_token = creds.get('GOOGLE_ADS_DEVELOPER_TOKEN')
        self.customer = clean_id(customer or creds.get('GOOGLE_ADS_CUSTOMER_ID'))
        login = creds.get('GOOGLE_ADS_LOGIN_CUSTOMER_ID', required=False)
        self.login = clean_id(login, 'login customer id') if login else ''
        self._token = token

    @property
    def token(self):
        if not self._token:
            self._token = google.token_from_refresh(
                creds.get('GOOGLE_ADS_CLIENT_ID'), creds.get('GOOGLE_ADS_CLIENT_SECRET'),
                creds.get('GOOGLE_ADS_REFRESH_TOKEN'))
        return self._token

    def headers(self):
        head = {'developer-token': self.developer_token}
        if self.login:
            head['login-customer-id'] = self.login
        return head

    def call(self, method, path, body=None):
        url = f'{HOST}/{version()}/{path}'
        try:
            return google.call(method, url, token=self.token, body=body, headers=self.headers())
        except google.GoogleError as err:
            raise SystemExit(explain(err)) from None

    def search(self, gaql):
        """Every row of a GAQL query (searchStream), as nested dicts in the API's camelCase."""
        chunks = self.call('POST', f'customers/{self.customer}/googleAds:searchStream', {'query': gaql})
        rows = []
        for chunk in chunks if isinstance(chunks, list) else [chunks]:
            rows.extend(chunk.get('results') or [])
        return rows

    def mutate(self, resource, operations, validate_only):
        body = {'operations': operations}
        if validate_only:
            body['validateOnly'] = True
        return self.call('POST', f'customers/{self.customer}/{resource}:mutate', body)


def explain(err):
    hints = []
    text = err.message
    if err.status == 404:
        hints.append(f'API version {version()} may be sunset. Set GOOGLE_ADS_API_VERSION to a current one.')
    if 'DEVELOPER_TOKEN_NOT_APPROVED' in text or 'only approved for use with test accounts' in text:
        hints.append('The developer token is at Test access: it only works on test accounts. '
                     'Apply for Basic access in the manager account API Center.')
    if 'USER_PERMISSION_DENIED' in text or 'login-customer-id' in text:
        hints.append('Going through a manager account? Set GOOGLE_ADS_LOGIN_CUSTOMER_ID to its id.')
    if 'CUSTOMER_NOT_ENABLED' in text:
        hints.append('The account is not enabled: cancelled, never set up with billing, or suspended.')
    if 'SERVICE_DISABLED' in text or 'has not been used in project' in text:
        hints.append('Enable the Google Ads API on the GCP project that owns the OAuth client.')
    return '\n'.join([f'Google Ads API: {err}'] + hints)


def camel(name):
    head, *rest = name.split('_')
    return head + ''.join(part[:1].upper() + part[1:] for part in rest)


def pick(row, path):
    """pick(row, 'campaign_budget.amount_micros') reads row['campaignBudget']['amountMicros']."""
    value = row
    for part in path.split('.'):
        if not isinstance(value, dict):
            return ''
        value = value.get(camel(part), value.get(part, ''))
    return value


def selected_fields(gaql):
    match = re.search(r'\bselect\b(.*?)\bfrom\b', gaql, re.I | re.S)
    if not match:
        raise SystemExit('That does not look like GAQL: expected SELECT <fields> FROM <resource>.')
    return [f.strip() for f in match.group(1).split(',') if f.strip()]


def money(micros):
    try:
        return f'{int(micros) / 1_000_000:,.2f}'
    except (TypeError, ValueError):
        return ''


def date_range(days, today=None):
    today = today or datetime.date.today()
    end = today - datetime.timedelta(days=1)  # today is incomplete
    start = end - datetime.timedelta(days=max(days, 1) - 1)
    return start.isoformat(), end.isoformat()


def quote(text):
    return "'" + text.replace('\\', '\\\\').replace("'", "\\'") + "'"


def find_campaign(client, ref):
    """A campaign by id or exact name, with its budget. Removed campaigns are ignored."""
    fields = ('campaign.id, campaign.name, campaign.status, campaign.resource_name, '
              'campaign_budget.resource_name, campaign_budget.amount_micros, '
              'campaign_budget.explicitly_shared, campaign_budget.reference_count, customer.currency_code')
    ref = str(ref).strip()
    if re.fullmatch(r'\d+', ref):
        where = f'campaign.id = {ref}'
    else:
        where = f'campaign.name = {quote(ref)}'
    rows = client.search(f"SELECT {fields} FROM campaign WHERE {where} AND campaign.status != 'REMOVED'")
    if not rows:
        raise SystemExit(f'No campaign {ref!r} in customer {client.customer}. `cpm googleads campaigns` lists them.')
    if len(rows) > 1:
        ids = ', '.join(pick(r, 'campaign.id') for r in rows)
        raise SystemExit(f'{len(rows)} campaigns are named {ref!r} ({ids}). Pass the id instead.')
    return rows[0]


def write_args(p):
    p.add_argument('--commit', action='store_true', help='actually change the account (default: dry run)')
    p.add_argument('--no-validate', action='store_true',
                   help='dry run without asking Google to validate the change (validateOnly)')


def apply(client, resource, operation, args, summary):
    """Dry run by default: print the change and have Google validate it. --commit writes it."""
    print(summary)
    if not args.commit:
        if not args.no_validate:
            client.mutate(resource, [operation], validate_only=True)
            print('Dry run: Google validated the change (validateOnly). Nothing was changed.')
        else:
            print('Dry run: nothing was sent.')
        print('Re-run with --commit to apply it.')
        return None
    reply = client.mutate(resource, [operation], validate_only=False)
    names = [r.get('resourceName', '') for r in reply.get('results') or []]
    print(f'Done: {", ".join(names) or "applied"}')
    return reply


def set_status(argv, status, doc):
    p = parser(doc)
    p.add_argument('campaign', help='campaign id or exact name')
    write_args(p)
    args = p.parse_args(argv)
    client = Client(args.customer)
    row = find_campaign(client, args.campaign)
    current = pick(row, 'campaign.status')
    name = pick(row, 'campaign.name')
    if current == status:
        print(f'{name} ({pick(row, "campaign.id")}) is already {status}. Nothing to do.')
        return 0
    operation = {'update': {'resourceName': pick(row, 'campaign.resource_name'), 'status': status},
                 'updateMask': 'status'}
    apply(client, 'campaigns', operation, args,
          f'{name} ({pick(row, "campaign.id")}): {current} -> {status}')
    return 0


def main(fn):
    try:
        sys.exit(fn(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
