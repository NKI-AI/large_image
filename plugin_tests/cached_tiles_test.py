#!/usr/bin/env python
# -*- coding: utf-8 -*-

#############################################################################
#  Copyright Kitware Inc.
#
#  Licensed under the Apache License, Version 2.0 ( the "License" );
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#############################################################################

import os
import time

from girder import config
from tests import base

from . import common


# boiler plate to start and stop the server

os.environ['GIRDER_PORT'] = os.environ.get('GIRDER_TEST_PORT', '20200')
config.loadConfig()  # Must reload config to pickup correct port


def setUpModule():
    curConfig = config.getConfig()
    curConfig.setdefault('large_image', {})
    curConfig['large_image']['cache_backend'] = os.environ.get(
        'LARGE_IMAGE_CACHE_BACKEND')
    base.enabledPlugins.append('large_image')
    base.startServer(False)


def tearDownModule():
    base.stopServer()


class LargeImageCachedTilesTest(common.LargeImageCommonTest):
    def _monitorTileCounts(self):
        if hasattr(self, 'tileCounter'):
            return
        from girder.plugins.large_image.tilesource.test import TestTileSource
        originalGetTile = TestTileSource.getTile
        originalWrapKey = TestTileSource.wrapKey
        self.tileCounter = 0
        self.keyPrefix = str(time.time())

        def countGetTile(ttsself, *args, **kwargs):
            # Increment the counter after the call, so that exceptions won't
            # increment it.
            result = originalGetTile(ttsself, *args, **kwargs)
            self.tileCounter += 1
            return result

        def wrapKey(*args, **kwargs):
            # Ensure that this test has unique keys
            return self.keyPrefix + originalWrapKey(*args, **kwargs)

        TestTileSource.getTile = countGetTile
        TestTileSource.wrapKey = wrapKey

    def setUp(self):
        self._monitorTileCounts()
        common.LargeImageCommonTest.setUp(self)

    def testTilesFromTest(self):
        # Create a test tile with the default options
        params = {'encoding': 'JPEG'}
        meta = self._createTestTiles(params, {
            'tileWidth': 256, 'tileHeight': 256,
            'sizeX': 256 * 2 ** 9, 'sizeY': 256 * 2 ** 9, 'levels': 10
        })
        self._testTilesZXY('test', meta, params)
        # We should have generated tiles
        self.assertGreater(self.tileCounter, 0)
        counter1 = self.tileCounter
        # Running a second time should take entirely from cache
        self._testTilesZXY('test', meta, params)
        self.assertEqual(self.tileCounter, counter1)

        # Test most of our parameters in a single special case
        params = {
            'minLevel': 2,
            'maxLevel': 5,
            'tileWidth': 160,
            'tileHeight': 120,
            'sizeX': 5000,
            'sizeY': 3000,
            'encoding': 'JPEG'
        }
        meta = self._createTestTiles(params, {
            'tileWidth': 160, 'tileHeight': 120,
            'sizeX': 5000, 'sizeY': 3000, 'levels': 6
        })
        meta['minLevel'] = 2
        self._testTilesZXY('test', meta, params)
        # We should have generated tiles
        self.assertGreater(self.tileCounter, counter1)
        counter2 = self.tileCounter
        # Running a second time should take entirely from cache
        self._testTilesZXY('test', meta, params)
        self.assertEqual(self.tileCounter, counter2)

        # Test the fractal tiles with PNG
        params = {'fractal': 'true'}
        meta = self._createTestTiles(params, {
            'tileWidth': 256, 'tileHeight': 256,
            'sizeX': 256 * 2 ** 9, 'sizeY': 256 * 2 ** 9, 'levels': 10
        })
        self._testTilesZXY('test', meta, params, common.PNGHeader)
        # We should have generated tiles
        self.assertGreater(self.tileCounter, counter2)
        counter3 = self.tileCounter
        # Running a second time should take entirely from cache
        self._testTilesZXY('test', meta, params, common.PNGHeader)
        self.assertEqual(self.tileCounter, counter3)

    def testLargeRegion(self):
        # Create a test tile with the default options
        file = self._uploadFile(os.path.join(
            os.environ['LARGE_IMAGE_DATA'], 'sample_jp2k_33003_TCGA-CV-7242-'
            '11A-01-TS1.1838afb1-9eee-4a70-9ae3-50e3ab45e242.svs'))
        itemId = str(file['itemId'])
        # Get metadata to use in our tests
        resp = self.request(path='/item/%s/tiles' % itemId, user=self.admin)
        self.assertStatusOk(resp)
        tileMetadata = resp.json

        params = {
            'regionWidth': min(10000, tileMetadata['sizeX']),
            'regionHeight': min(10000, tileMetadata['sizeY']),
            'width': 480,
            'height': 480,
            'encoding': 'PNG'
        }
        resp = self.request(path='/item/%s/tiles/region' % itemId,
                            user=self.admin, isJson=False, params=params)
        self.assertStatusOk(resp)


class MemcachedCache(LargeImageCachedTilesTest):
    pass


class PythonCache(LargeImageCachedTilesTest):
    pass