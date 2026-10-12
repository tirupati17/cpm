import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('page_artwork',Path(__file__).parents[1]/'services/appstore/page-artwork.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def placement(identifier,image='asset',group='DEFAULT_PROFILE',kind='PRODUCT_PAGE_HEADER_ASSET'):
    return {'id':identifier,'attributes':{'placementType':kind,'placementGroup':group},
            'relationships':{'image':{'data':{'id':image}},'video':{'data':None}}}

class InheritanceTests(unittest.TestCase):
    def test_same_asset_distinct_placement_is_inherited(self):
        self.assertTrue(m.inherited(placement('draft'),[placement('live')]))
    def test_shared_live_placement_is_never_removable(self):
        self.assertFalse(m.inherited(placement('live'),[placement('live')]))
    def test_custom_asset_and_other_groups_are_not_inherited(self):
        self.assertFalse(m.inherited(placement('draft',image='changed'),[placement('live')]))
        self.assertFalse(m.inherited(placement('draft',group='IPAD_13_PROFILE'),[placement('live')]))
    def test_preview_identity_is_checked(self):
        live=placement('live',kind='APP_PREVIEW');live['relationships']={'image':{'data':None},'video':{'data':{'id':'movie'}}}
        copy={**live,'id':'draft'}
        self.assertTrue(m.inherited(copy,[live]))
        copy['relationships']={'video':{'data':{'id':'different'}}}
        self.assertFalse(m.inherited(copy,[live]))

if __name__=='__main__':unittest.main()
