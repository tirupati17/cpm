"""Listing copy, listing images and one-time product specs: the checks that run before Play sees anything."""
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services' / 'play'))
from _images import check_screenshot, parse_locale_map, png_size, select_shots, targets
from _listing import changes, problems
from _products import load_spec, money, newer_regions_version, product_body, regional_configs, show


def png(path, width, height, color=2):
    """A minimal valid PNG header (enough for the size and format checks)."""
    ihdr = struct.pack('>IIBBBBB', width, height, 8, color, 0, 0, 0)
    chunk = struct.pack('>I', len(ihdr)) + b'IHDR' + ihdr + struct.pack('>I', zlib.crc32(b'IHDR' + ihdr))
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk)
    return Path(path)


GOOD = {'title': 'Calm: Mood Journal', 'shortDescription': 'Track how you feel.', 'fullDescription': 'A journal.'}


class ListingTests(unittest.TestCase):
    def test_good_copy_passes(self):
        self.assertEqual(problems(GOOD), [])

    def test_limits(self):
        found = problems({**GOOD, 'title': 'x' * 31, 'shortDescription': ''})
        self.assertTrue(any('title is 31' in p for p in found))
        self.assertTrue(any('shortDescription is empty' in p for p in found))

    def test_ranking_and_price_words_in_the_title(self):
        for title in ('Best Mood App', 'Free Journal', '#1 Tracker', 'New Diary'):
            with self.subTest(title=title):
                self.assertTrue(any('ranking/price' in p for p in problems({**GOOD, 'title': title})))

    def test_emoji_and_all_caps_in_the_title(self):
        self.assertIn('title has an emoji', problems({**GOOD, 'title': 'Mood 🌙'}))
        self.assertIn('title has an all-caps word', problems({**GOOD, 'title': 'MOOD Journal'}))

    def test_dashes_only_when_forbidden(self):
        copy = {**GOOD, 'fullDescription': 'Calm — always.'}
        self.assertEqual(problems(copy), [])
        self.assertIn('fullDescription has an em/en dash', problems(copy, forbid_dashes=True))

    def test_changes_against_live(self):
        self.assertEqual(changes(None, GOOD), ['title', 'shortDescription', 'fullDescription'])
        self.assertEqual(changes(GOOD, dict(GOOD)), [])
        self.assertEqual(changes(GOOD, {**GOOD, 'title': 'Other'}), ['title'])


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_png_checks(self):
        self.assertEqual(png_size(png(self.dir / 'a.png', 1080, 1920)), (1080, 1920))
        with self.assertRaises(SystemExit):
            png_size(png(self.dir / 'alpha.png', 1080, 1920, color=6))
        (self.dir / 'x.png').write_bytes(b'GIF89a' + b'\0' * 30)
        with self.assertRaises(SystemExit):
            png_size(self.dir / 'x.png')

    def test_screenshot_bounds(self):
        check_screenshot(png(self.dir / 'ok.png', 1080, 1920))
        with self.assertRaises(SystemExit):
            check_screenshot(png(self.dir / 'wide.png', 3000, 1000))
        with self.assertRaises(SystemExit):
            check_screenshot(png(self.dir / 'small.png', 200, 300))
        with self.assertRaises(SystemExit):
            check_screenshot(self.dir / 'ok.png', exact=(1920, 1080))

    def test_shot_selection_order_limit_and_graphic(self):
        for i in range(3):
            png(self.dir / f'0{i}.png', 1080, 1920)
        png(self.dir / 'feature-graphic.png', 1024, 500)
        self.assertEqual([p.name for p in select_shots(self.dir, exclude={'feature-graphic.png'})],
                         ['00.png', '01.png', '02.png'])
        self.assertEqual([p.name for p in select_shots(self.dir, ['02.png', '00.png'])], ['02.png', '00.png'])
        with self.assertRaises(SystemExit):
            select_shots(self.dir, ['missing.png'])
        for i in range(3, 10):
            png(self.dir / f'0{i}.png', 1080, 1920)
        with self.assertRaises(SystemExit):
            select_shots(self.dir, exclude={'feature-graphic.png'})

    def test_per_language_layout_touches_only_listed_languages(self):
        for name in ('en', 'hi', 'de'):
            (self.dir / name).mkdir()
        mapping = parse_locale_map('en=en-US,hi=hi-IN,de=de-DE')
        plan = targets(self.dir, {'en-US', 'hi-IN'}, locale_map=mapping)
        self.assertEqual([locale for locale, _ in plan], ['en-US', 'hi-IN'])
        self.assertEqual([locale for locale, _ in targets(self.dir, set(), ['de'], mapping)], ['de-DE'])
        with self.assertRaises(SystemExit):
            targets(self.dir, set(), ['ru'], mapping)

    def test_shared_layout_goes_to_every_listed_language(self):
        png(self.dir / '01.png', 1920, 1080)
        plan = targets(self.dir, {'fr-FR', 'en-US'})
        self.assertEqual(plan, [('en-US', self.dir), ('fr-FR', self.dir)])

    def test_bad_locale_map(self):
        with self.assertRaises(SystemExit):
            parse_locale_map('en')


SPEC = {
    'regionGroups': {'low': ['PK', 'NG']},
    'products': [{
        'productId': 'coins_100', 'price': '0.99', 'regionPrices': {'IN': '24 INR'}, 'groupPrices': {'low': '0.49'},
        'listings': [{'languageCode': 'en-US', 'title': '100 coins', 'description': 'A pack of coins.'}],
    }],
}


def converted(usd_units, usd_nanos):
    price = lambda cur: {'currencyCode': cur, 'units': str(usd_units), 'nanos': usd_nanos}
    return {'convertedRegionPrices': {r: {'price': price(c)} for r, c in
                                      (('US', 'USD'), ('IN', 'INR'), ('PK', 'PKR'), ('GB', 'GBP'))}}


class ProductTests(unittest.TestCase):
    def spec(self, data):
        handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
        json.dump(data, handle)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return handle.name

    def test_money(self):
        self.assertEqual(money('0.99'), {'currencyCode': 'USD', 'units': '0', 'nanos': 990_000_000})
        self.assertEqual(money('13.99'), {'currencyCode': 'USD', 'units': '13', 'nanos': 990_000_000})
        self.assertEqual(money('24 INR'), {'currencyCode': 'INR', 'units': '24', 'nanos': 0})
        with self.assertRaises(SystemExit):
            money('free')

    def test_show_handles_protobuf_zero_fields(self):
        self.assertEqual(show({'currencyCode': 'USD', 'nanos': 990_000_000}), '0.99 USD')

    def test_spec_loads_with_default_regions_version(self):
        version, groups, products = load_spec(self.spec(SPEC))
        self.assertEqual(version, '2025/03')
        self.assertEqual(groups, {'low': {'PK', 'NG'}})
        self.assertEqual(products[0]['productId'], 'coins_100')

    def test_bad_specs_are_refused(self):
        product = SPEC['products'][0]
        for bad in ({**product, 'productId': 'Coins-100'}, {**product, 'price': 'x'},
                    {**product, 'listings': []}, {**product, 'groupPrices': {'nope': '1'}},
                    {**product, 'listings': [{'languageCode': 'en-US', 'title': 't' * 56, 'description': 'd'}]}):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit):
                    load_spec(self.spec({**SPEC, 'products': [bad]}))
        with self.assertRaises(SystemExit):
            load_spec(self.spec({**SPEC, 'products': [product, product]}))

    def test_hand_price_beats_group_beats_conversion(self):
        _, groups, products = load_spec(self.spec(SPEC))
        configs = regional_configs(converted(0, 990_000_000), products[0]['regionPrices'],
                                   {'low': converted(0, 490_000_000)}, groups)
        by_region = {c['regionCode']: c['price'] for c in configs}
        self.assertEqual(by_region['IN'], {'currencyCode': 'INR', 'units': '24', 'nanos': 0})
        self.assertEqual(by_region['PK']['nanos'], 490_000_000)
        self.assertEqual(by_region['GB']['nanos'], 990_000_000)
        self.assertTrue(all(c['availability'] == 'AVAILABLE' for c in configs))

    def test_product_body(self):
        body = product_body('com.demo', SPEC['products'][0], [], {})
        option = body['purchaseOptions'][0]
        self.assertEqual(option['purchaseOptionId'], 'coins-100')
        self.assertEqual(option['newRegionsConfig']['usdPrice'], money('0.99'))
        self.assertTrue(option['buyOption']['legacyCompatible'])
        self.assertEqual(body['packageName'], 'com.demo')

    def test_regions_version_retry_reads_the_error(self):
        text = 'Regions version 2025/03 is outdated. Latest is 2025/09.'
        self.assertEqual(newer_regions_version(text, '2025/03'), '2025/09')
        self.assertIsNone(newer_regions_version('quota exceeded 2025/09', '2025/03'))
        self.assertIsNone(newer_regions_version('Regions version 2025/03 bad', '2025/03'))


if __name__ == '__main__':
    unittest.main()
