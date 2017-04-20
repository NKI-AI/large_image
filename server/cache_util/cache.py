#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
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
###############################################################################

try:
    import resource
except ImportError:
    resource = None
import six

try:
    from girder import logger
except ImportError:
    import logging as logger
from .cachefactory import CacheFactory, pickAvailableCache


_tileCache = None
_tileLock = None


# If we have a resource module, ask to use as many file handles as the hard
# limit allows, then calculate that how may tile sources we can have open based
# on the actual limit.
MaximumTileSources = 10
if resource:
    try:
        SoftNoFile, HardNoFile = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (HardNoFile, HardNoFile))
        SoftNoFile, HardNoFile = resource.getrlimit(resource.RLIMIT_NOFILE)
        # Reserve some file handles for general use, and expect that tile
        # sources could use many handles each.  This is conservative, since
        # running out of file handles breaks the program in general.
        MaximumTileSources = max(3, (SoftNoFile - 10) / 20)
    except Exception:
        pass


CacheProperties = {
    'tilesource': {
        # Cache size is based on what the class needs, which does not include
        # individual tiles
        'cacheMaxSize': pickAvailableCache(
            1024 ** 2, maxItems=MaximumTileSources),
        # The cache timeout is not currently being used, but it is set here in
        # case we ever choose to implement it.
        'cacheTimeout': 300,
    }
}


def strhash(*args, **kwargs):
    """
    Generate a string hash value for an arbitrary set of args and kwargs.  This
    relies on the repr of each element.

    :param args: arbitrary tuple of args.
    :param kwargs: arbitrary dictionary of kwargs.
    :returns: hashed string of the arguments.
    """
    if kwargs:
        return '%r,%r' % (args, sorted(kwargs.items()))
    return '%r' % (args, )


def methodcache(key=None):
    """
    Decorator to wrap a function with a memoizing callable that saves results
    in self.cache.  This is largely taken from cachetools, but uses a cache
    from self.cache rather than a passed value.  If self.cache_lock is
    present and not none, a lock is used.

    :param key: if a function, use that for the key, otherwise use self.wrapKey.
    """
    def decorator(func):
        @six.wraps(func)
        def wrapper(self, *args, **kwargs):
            k = key(*args, **kwargs) if key else self.wrapKey(*args, **kwargs)
            lock = getattr(self, 'cache_lock', None)
            try:
                if lock:
                    with self.cache_lock:
                        return self.cache[k]
                else:
                    return self.cache[k]
            except KeyError:
                pass  # key not found
            v = func(self, *args, **kwargs)
            try:
                if lock:
                    with self.cache_lock:
                        self.cache[k] = v
                else:
                    self.cache[k] = v
            except ValueError:
                pass  # value too large
            return v
        return wrapper
    return decorator


class LruCacheMetaclass(type):
    """
    """
    namedCaches = {}
    classCaches = {}

    def __new__(metacls, name, bases, namespace, **kwargs):  # noqa - N804
        # Get metaclass parameters by finding and removing them from the class
        # namespace (necessary for Python 2), or preferentially as metaclass
        # arguments (only in Python 3).

        cacheName = namespace.get('cacheName', None)
        cacheName = kwargs.get('cacheName', cacheName)

        maxSize = CacheProperties.get(cacheName, {}).get('cacheMaxSize', None)
        maxSize = namespace.pop('cacheMaxSize', maxSize)
        maxSize = kwargs.get('cacheMaxSize', maxSize)
        if maxSize is None:
            raise TypeError('Usage of the LruCacheMetaclass requires a '
                            '"cacheMaxSize" attribute on the class %s.' % name)

        timeout = CacheProperties.get(cacheName, {}).get('cacheTimeout', None)
        timeout = namespace.pop('cacheTimeout', timeout)
        timeout = kwargs.get('cacheTimeout', timeout)

        cls = super(LruCacheMetaclass, metacls).__new__(
            metacls, name, bases, namespace)
        if not cacheName:
            cacheName = cls

        if LruCacheMetaclass.namedCaches.get(cacheName) is None:
            cache, cacheLock = CacheFactory().getCache(maxSize)
            LruCacheMetaclass.namedCaches[cacheName] = cache
            logger.info('Created LRU Cache for %r with %d maximum size' % (
                cacheName, maxSize))
        else:
            cache = LruCacheMetaclass.namedCaches[cacheName]

        # Don't store the cache in cls.__dict__, because we don't want it to be
        # part of the attribute lookup hierarchy
        # TODO: consider putting it in cls.__dict__, to inspect statistics
        # cls is hashable though, so use it to lookup the cache, in case an
        # identically-named class gets redefined
        LruCacheMetaclass.classCaches[cls] = cache

        return cls

    def __call__(cls, *args, **kwargs):  # noqa - N805

        cache = LruCacheMetaclass.classCaches[cls]

        if hasattr(cls, 'getLRUHash'):
            key = cls.getLRUHash(*args, **kwargs)
        else:
            key = strhash(args[0], kwargs)
        key = cls.__name__ + ' ' + key
        try:
            instance = cache[key]
        except KeyError:

            instance = super(LruCacheMetaclass, cls).__call__(*args, **kwargs)
            cache[key] = instance

        return instance


def getTileCache():
    """
    Get the preferred tile cache and lock.

    :returns: tileCache and tileLock.
    """
    global _tileCache, _tileLock

    if _tileCache is None:
        # Decide whether to use Memcached or cachetools
        _tileCache, _tileLock = CacheFactory().getCache()
    return _tileCache, _tileLock
