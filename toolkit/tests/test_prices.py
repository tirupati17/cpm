"""Price ladders: App Store point picking and Play price choice. Pure logic, no network."""
import importlib.util
import json
import sys
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

TOOLKIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLKIT / 'lib'))
from cpmkit.mdsection import replace_section  # noqa: E402
from cpmkit.territories import iso2, iso3  # noqa: E402


def load(service, name, alias):
    """Both services have a _prices module: load each under its own name."""
    folder = str(TOOLKIT / 'services' / service)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    spec = importlib.util.spec_from_file_location(alias, Path(folder) / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = load('appstore', '_prices', 'appstore_prices')
P = load('play', '_prices', 'play_prices')


def point(pid, territory, price):
    return {'id': pid, 'type': 'subscriptionPricePoints', 'attributes': {'customerPrice': price},
            'relationships': {'territory': {'data': {'id': territory}}}}


def price_record(territory, point_id, start=None, plan='UPFRONT'):
    return {'attributes': {'startDate': start, 'planType': plan},
            'relationships': {'territory': {'data': {'id': territory}},
                              'subscriptionPricePoint': {'data': {'id': point_id}}}}


class SharedTests(unittest.TestCase):
    def test_territory_codes(self):
        self.assertEqual(iso2('DEU'), 'DE')
        self.assertEqual(iso2('gbr'), 'GB')
        self.assertEqual(iso3('XK'), 'XKS')
        self.assertIsNone(iso2('ZZZ'))

    def test_markdown_section_replaced_in_place(self):
        doc = replace_section('# Title\n', 'a', 'one')
        doc = replace_section(doc, 'b', 'two')
        doc = replace_section(doc, 'a', 'uno')
        self.assertIn('uno', doc)
        self.assertNotIn('one', doc)
        self.assertLess(doc.index('uno'), doc.index('two'))
        self.assertTrue(doc.startswith('# Title\n'))


class AppStorePriceTests(unittest.TestCase):
    def test_format_and_discount(self):
        self.assertEqual(A.fmt(D('199.0')), '199')
        self.assertEqual(A.fmt(D('7.99')), '7.99')
        self.assertEqual(A.discount(D('7.99'), D('39.99')), D('80.0'))
        self.assertEqual(A.discount(D('299'), D('1499')), D('80.1'))

    def test_current_price_respects_start_dates(self):
        records = [price_record('USA', 'old'), price_record('USA', 'new', '2026-01-01'),
                   price_record('USA', 'future', '2027-01-01'), price_record('USA', 'inst', plan='MONTHLY')]
        included = [point('old', 'USA', '0.99'), point('new', 'USA', '1.99'), point('future', 'USA', '9.99'),
                    point('inst', 'USA', '0.29')]
        self.assertEqual(A.current_prices(records, included, 'UPFRONT', '2026-10-08'), {'USA': (D('1.99'), 'new')})
        self.assertEqual(A.current_prices(records, included, 'MONTHLY', '2026-10-08'), {'USA': (D('0.29'), 'inst')})

    def test_exact_and_nearest(self):
        points = A.index_points([point('a', 'IND', '199.0'), point('b', 'IND', '249.0'), point('c', 'IND', '299.0')])
        self.assertEqual(A.exact(points, 'IND', D('199'), 'monthly'), 'a')
        with self.assertRaises(SystemExit):
            A.exact(points, 'IND', D('200'), 'monthly')
        self.assertEqual(A.nearest(points['IND'], D('274')), (D('249.0'), 'b'))   # tie goes low
        self.assertEqual(A.at_least(points['IND'], D('250')), (D('299.0'), 'c'))

    def spec(self, **offer):
        sub = {'productId': 'yearly', 'basePrice': {'territory': 'USA', 'price': '39.99'},
               'manualPrices': {'IND': '1499'},
               'introOffer': {'offerMode': 'PAY_UP_FRONT', 'duration': 'ONE_YEAR', 'prices': {'USA': '7.99'},
                              'fractionOfList': '0.20', 'discountRange': [78, 82], **offer},
               'instalmentPlan': {'planType': 'MONTHLY', 'months': 12}}
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
            json.dump({'appstore': {'subscriptions': [sub]}}, handle)
        return A.load_spec(handle.name)[0][0]

    def test_plan_subscription(self):
        sub = self.spec()
        points = A.index_points([
            point('u40', 'USA', '39.99'), point('u8', 'USA', '7.99'), point('u3', 'USA', '3.49'),
            point('i1499', 'IND', '1499.0'), point('i299', 'IND', '299.0'), point('i125', 'IND', '125.0'),
            point('g40', 'GBR', '39.99'), point('g8', 'GBR', '8.0'), point('g799', 'GBR', '7.99'),
            point('g339', 'GBR', '3.39'), point('j', 'JPN', '6000')])
        current = {'USA': (D('2.99'), 'u3'), 'IND': (D('299'), 'i299'), 'GBR': (D('2.99'), 'x'), 'JPN': (D('500'), 'y')}
        instalment = {'IND': (D('29'), 'i29'), 'GBR': (D('0.29'), 'g029')}
        equalized = {'GBR': (D('39.99'), 'g40'), 'IND': (D('3999'), 'i3999')}
        rows = {r['territory']: r for r in A.plan_subscription(
            sub, current, 'u40', equalized, {'USA': 'u40', 'IND': 'i1499'}, points, {'GBR': 'GBP'}, instalment)}
        self.assertEqual((rows['USA']['list'], rows['USA']['source'], rows['USA']['intro']), (D('39.99'), 'base', D('7.99')))
        self.assertEqual((rows['IND']['list'], rows['IND']['source']), (D('1499'), 'manual'))   # manual beats equalized
        self.assertEqual(rows['GBR']['intro'], D('8.0'))           # nearest to 20% of 39.99 = 7.998
        self.assertEqual(rows['GBR']['instalment'], D('3.39'))     # first point >= 39.99 / 12
        self.assertEqual(rows['IND']['instalment'], D('125.0'))
        self.assertIn('no equalized price: left as is', rows['JPN']['flags'])
        self.assertFalse(rows['JPN']['change'])

    def test_discount_outside_range_is_flagged(self):
        sub = self.spec(fractionOfList='0.30')
        points = A.index_points([point('g40', 'GBR', '39.99'), point('g12', 'GBR', '11.99')])
        rows = A.plan_subscription(sub, {'GBR': (D('2.99'), 'x')}, 'u40', {'GBR': (D('39.99'), 'g40')},
                                   {'USA': 'u40', 'IND': 'i'}, points, {})
        self.assertTrue(any('outside 78-82%' in f for f in rows[0]['flags']))

    def test_bodies(self):
        body = A.price_body('s1', 'GBR', 'p1', True)
        self.assertTrue(body['data']['attributes']['preserveCurrentPrice'])
        self.assertEqual(body['data']['attributes']['planType'], 'UPFRONT')
        intro = A.intro_body('s1', 'GBR', {'duration': 'ONE_YEAR', 'offerMode': 'PAY_UP_FRONT', 'numberOfPeriods': 1}, 'p2')
        self.assertEqual(intro['data']['relationships']['subscriptionPricePoint']['data']['id'], 'p2')
        trial = A.intro_body('s1', 'GBR', {'duration': 'ONE_WEEK', 'offerMode': 'FREE_TRIAL', 'numberOfPeriods': 1}, None)
        self.assertNotIn('subscriptionPricePoint', trial['data']['relationships'])
        schedule = A.schedule_body('i1', 'USA', {'USA': 'pu', 'IND': 'pi'})
        refs = [r['id'] for r in schedule['data']['relationships']['manualPrices']['data']]
        self.assertEqual(refs, [i['id'] for i in schedule['included']])
        self.assertEqual(schedule['data']['relationships']['baseTerritory']['data']['id'], 'USA')

    def test_iap_plan_and_export(self):
        iap = {'productId': 'lifetime', 'baseTerritory': 'USA', 'prices': {'USA': D('79.99'), 'IND': D('3999')}}
        rows = A.plan_iap(iap, {'USA': (D('14.99'), 'a'), 'DEU': (D('17.99'), 'b')},
                          {'DEU': (D('89.99'), 'c'), 'IND': (D('7900'), 'd')}, {'USA': 'pu', 'IND': 'pi'},
                          {'DEU': 'EUR', 'IND': 'INR', 'USA': 'USD'})
        by = {r['territory']: r for r in rows}
        self.assertEqual((by['DEU']['list'], by['DEU']['source']), (D('89.99'), 'automatic'))
        self.assertEqual(by['IND']['list'], D('3999'))
        out = A.export({'lifetime': rows}, iso2)
        self.assertEqual(out['DEU'], {'iso2': 'DE', 'currency': 'EUR', 'products': {'lifetime': {'list': '89.99'}}})


def m(text):
    return P.money(text)


def conversion(prices):
    return {'convertedRegionPrices': {r: {'regionCode': r, 'price': m(p)} for r, p in prices.items()}}


class PlayPriceTests(unittest.TestCase):
    def test_round_local(self):
        cases = [('7.63', False, '7.49'), ('7.80', False, '7.99'), ('0.31', False, '0.49'),
                 ('34.20', False, '33.99'), ('304.20', False, '303.99'), ('790', True, '789'),
                 ('23.8', True, '24'), ('1394', True, '1390'), ('139450', True, '139000')]
        for value, whole, want in cases:
            with self.subTest(value=value):
                self.assertEqual(P.round_local(D(value), whole), D(want))

    def test_choice_order(self):
        match = {'DE': {'currency': 'EUR', 'products': {'yearly': {'list': '44.99', 'intro': '9'}}},
                 'AZ': {'currency': 'USD', 'products': {'yearly': {'list': '39.99'}}}}
        current = {'DE': m('40.99 EUR'), 'AZ': m('60 AZN'), 'IN': m('299 INR'), 'XX': m('1 USD')}
        rows = {r['region']: r for r in P.plan_prices(
            current, conversion({'DE': '37.10 EUR', 'AZ': '67.84 AZN', 'IN': '3300 INR'}),
            {'IN': m('1499 INR')}, match, 'yearly', 'list')}
        self.assertEqual((P.show(rows['DE']['new']), rows['DE']['source']), ('44.99 EUR', 'ios'))
        self.assertEqual((P.show(rows['AZ']['new']), rows['AZ']['source']), ('67.99 AZN', 'converted'))
        self.assertEqual(rows['IN']['source'], 'set')
        self.assertEqual(rows['XX']['source'], 'kept')
        self.assertTrue(rows['XX']['flags'])

    def test_limits(self):
        rows = P.plan_prices({'DE': m('1 EUR')}, conversion({'DE': '0.10 EUR'}), {}, None, None, 'list',
                             ({'DE': {'price': m('0.20 EUR')}}, {'DE': {'price': m('0.05 EUR')}}))
        self.assertIn('above Play maximum', rows[0]['flags'][0])

    def test_offer_ratio_keeps_the_discount(self):
        rows = P.plan_prices({'PY': m('1 PYG')}, conversion({'PY': '224600 PYG'}), {})
        offer_rows = P.plan_prices({'PY': m('1 PYG')}, conversion({'PY': '44870 PYG'}), {})
        offer = {'offerId': 'o', 'discountRange': (D(78), D(82))}
        P.add_offer(rows, offer_rows, offer, D('7.99') / D('39.99'))
        self.assertEqual(rows[0]['offerSource'], 'ratio')
        self.assertEqual(rows[0]['flags'], [])
        self.assertTrue(D(78) <= rows[0]['discount'] <= D(82))

    def test_bodies(self):
        rows = [{'region': 'US', 'new': m('39.99'), 'offer': m('7.99')}, {'region': 'IN', 'new': m('1499 INR')}]
        plan = {'basePlanId': 'y', 'regionalConfigs': [{'regionCode': 'US', 'price': m('2.99'),
                                                         'newSubscriberAvailability': True}],
                'otherRegionsConfig': {'newSubscriberAvailability': False}}
        other = {'usdPrice': m('39.99'), 'eurPrice': m('36.99 EUR')}
        body = P.base_plan_body(plan, rows, other)
        self.assertEqual(body['regionalConfigs'][0]['price'], m('39.99'))
        self.assertTrue(body['regionalConfigs'][0]['newSubscriberAvailability'])
        self.assertFalse(body['otherRegionsConfig']['newSubscriberAvailability'])
        offer = P.offer_body('pkg', 'p', 'y', {'offerId': 'launch', 'duration': 'P1Y'}, rows, other)
        self.assertEqual(offer['phases'][0]['regionalConfigs'], [{'regionCode': 'US', 'price': m('7.99')}])
        self.assertEqual(offer['targeting'], {'acquisitionRule': {'scope': {'thisSubscription': {}}}})

    def test_match_file(self):
        exported = {'territories': {'DEU': {'iso2': 'DE', 'currency': 'EUR', 'products': {'monthly': {'list': '8.99'}}}}}
        self.assertEqual(P.load_match(exported)['DE']['currency'], 'EUR')


if __name__ == '__main__':
    unittest.main()
