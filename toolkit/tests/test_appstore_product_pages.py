import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('pages', Path(__file__).parents[1] / 'services/appstore/product-pages.py')
pages = importlib.util.module_from_spec(spec); spec.loader.exec_module(pages)

class ProductPageSafetyTests(unittest.TestCase):
    def test_validates_campaign_language_and_promo_limit(self):
        x = {'sourceVersion':'1.2.3','pages':[{'name':'German','campaignLocale':'de-DE','localizations':[
            {'locale':'de-DE','promotionalText':'Test','screenshots':[{'display':'APP_IPHONE_67','folder':'shots'}]}]}]}
        pages.validate_spec(x)
        x['pages'][0]['campaignLocale'] = 'en-US'
        with self.assertRaises(ValueError): pages.validate_spec(x)
        x['pages'][0]['campaignLocale'] = 'de-DE'
        x['pages'][0]['localizations'][0]['promotionalText'] = 'x'*171
        with self.assertRaises(ValueError): pages.validate_spec(x)

    def test_create_request_includes_version_and_localizations_atomically(self):
        planned = {'name':'Campaign','localizations':[{'locale':'en-US','promotionalText':'English'},
                                                     {'locale':'de-DE','promotionalText':'Deutsch'}]}
        body = pages.page_create_body('app', 'version', planned)
        included = {(r['type'],r['id']):r for r in body['included']}
        version_ref = body['data']['relationships']['appCustomProductPageVersions']['data'][0]
        version = included[(version_ref['type'],version_ref['id'])]
        locales = [included[(r['type'],r['id'])]['attributes']['locale']
                   for r in version['relationships']['appCustomProductPageLocalizations']['data']]
        self.assertEqual(locales,['en-US','de-DE'])
        self.assertEqual(body['data']['relationships']['appStoreVersionTemplate']['data']['id'],'version')

    def test_only_prepare_drafts_are_editable(self):
        pages.require_draft({'attributes':{'state':'PREPARE_FOR_SUBMISSION'}})
        for state in ['APPROVED','WAITING_FOR_REVIEW','IN_REVIEW','READY_FOR_REVIEW']:
            with self.assertRaises(ValueError): pages.require_draft({'attributes':{'state':state}})

    def test_replaces_only_proven_inherited_copies(self):
        shot = {'id':'source','attributes':{'fileName':'old.png','sourceFileChecksum':'old','fileSize':3,'assetDeliveryState':{'state':'COMPLETE'}}}
        copied = {**shot,'id':'draft'}
        files = [{'name':'new.png','md5':'new','bytes':4}]
        kept,remove,resume = pages.inspect_reconciliation([copied],files,[shot])
        self.assertEqual(remove,[copied]); self.assertEqual(kept,{})
        with self.assertRaises(ValueError): pages.inspect_reconciliation([shot],files,[shot])
        with self.assertRaises(ValueError): pages.inspect_reconciliation([copied],files,[])

    def test_reuses_processing_assets_and_recovers_only_matching_reservations(self):
        files = [{'name':'01.png','md5':'abc','bytes':3}]
        s = {'id':'draft','attributes':{'fileName':'01.png','sourceFileChecksum':None,'fileSize':3,'assetDeliveryState':{'state':'UPLOAD_COMPLETE'}}}
        kept,remove,resume = pages.inspect_reconciliation([s],files,[])
        self.assertEqual(list(kept),['01.png']); self.assertFalse(remove or resume)
        s['attributes']['assetDeliveryState']['state']='AWAITING_UPLOAD'
        self.assertEqual(pages.inspect_reconciliation([s],files,[])[2],[s])
        s['attributes']['fileSize']=4
        with self.assertRaises(ValueError): pages.inspect_reconciliation([s],files,[])

if __name__ == '__main__': unittest.main()
