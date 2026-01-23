/* global window */
(function (global) {
  'use strict';

  var hostname = (global.location && global.location.hostname) || '';
  var isDev = hostname === 'localhost'
    || hostname === '127.0.0.1'
    || hostname.indexOf('192.168.') === 0;

  var intervals = {
    clockMs: 1000,
    refreshMs: isDev ? 20000 : 60000,
    progressUpdateMs: isDev ? 5000 : 10000,
    densityMs: isDev ? 5000 : 10000,
    fxTtlMs: isDev ? 2 * 60 * 1000 : 10 * 60 * 1000
  };

  global.CONFIG = global.CONFIG || {};
  global.CONFIG.env = isDev ? 'dev' : 'prod';
  global.CONFIG.debug = !!global.CONFIG.debug || isDev;
  global.CONFIG.intervals = intervals;
  global.CONFIG.timelinePxPerMinute = 3;
  global.CONFIG.density = {
    activeTableWeight: 10,
    lastOrders5mWeight: 0,
    lowThreshold: 40,
    warnThreshold: 80,
    criticalThreshold: 150
  };

  global.APP_CONFIG = global.APP_CONFIG || {
    timelinePxPerMinute: global.CONFIG.timelinePxPerMinute,
    clockMs: intervals.clockMs,
    refreshMs: intervals.refreshMs,
    progressUpdateMs: intervals.progressUpdateMs,
    densityMs: intervals.densityMs,
    fxTtlMs: intervals.fxTtlMs,
    density: global.CONFIG.density
  };

  global.APP = global.APP || {};
  global.APP.state = global.APP.state || {
    tables: {},
    orders: [],
    rehberMasalar: {},
    tableSessions: {},
    activeTables: 0,
    lastOrders5m: 0,
    fx: { usd: null, eur: null },
    staff: [],
    staffStats: [],
    staffStatsDate: null,
    staffStatsRange: null,
    lastFetchTimes: {},
    lastError: null,
    density: null
  };

  var listeners = {};
  global.APP.on = function (event, handler) {
    if (!listeners[event]) listeners[event] = [];
    listeners[event].push(handler);
  };
  global.APP.off = function (event, handler) {
    if (!listeners[event]) return;
    listeners[event] = listeners[event].filter(function (fn) { return fn !== handler; });
  };
  global.APP.emit = function (event, payload) {
    if (!listeners[event]) return;
    listeners[event].forEach(function (fn) {
      try { fn(payload); } catch (err) { /* ignore handler errors */ }
    });
  };

  function throttleToast(message) {
    var now = Date.now();
    var last = global.APP._lastToastAt || 0;
    if (now - last < 5000) return false;
    global.APP._lastToastAt = now;
    global.APP.emit('toast:show', message);
    return true;
  }

  global.APP.safeFetch = function (url, options, opts) {
    var cfg = opts || {};
    var timeoutMs = cfg.timeoutMs || 8000;
    var retry = typeof cfg.retry === 'number' ? cfg.retry : 1;
    var cacheKey = cfg.cacheKey ? 'cache:' + cfg.cacheKey : null;
    var attempt = 0;

    function fetchOnce() {
      attempt += 1;
      var controller = new AbortController();
      var timeoutId = setTimeout(function () {
        controller.abort();
      }, timeoutMs);

      var requestOptions = Object.assign({}, options || {}, { signal: controller.signal });
      return fetch(url, requestOptions)
        .then(function (response) {
          clearTimeout(timeoutId);
          if (!response.ok) throw new Error('HTTP ' + response.status);
          return response.json();
        });
    }

    function readCache() {
      if (!cacheKey) return null;
      try {
        var raw = localStorage.getItem(cacheKey);
        return raw ? JSON.parse(raw) : null;
      } catch (err) {
        return null;
      }
    }

    function writeCache(data) {
      if (!cacheKey) return;
      try {
        localStorage.setItem(cacheKey, JSON.stringify(data));
      } catch (err) {
        // ignore cache write failures
      }
    }

    function handleError(err) {
      var cache = readCache();
      if (cache) {
        throttleToast(cfg.errorMessage || 'Veri alinamadi, son veri gosteriliyor.');
        return cache;
      }
      global.APP.state.lastError = (cfg.errorMessage || err.message || 'Veri alinamadi');
      throttleToast(cfg.errorMessage || 'Veri alinamadi.');
      throw err;
    }

    function run() {
      return fetchOnce()
        .then(function (data) {
          writeCache(data);
          return data;
        })
        .catch(function (err) {
          if (attempt <= retry) {
            return new Promise(function (resolve) { setTimeout(resolve, 300); })
              .then(run);
          }
          return handleError(err);
        });
    }

    return run();
  };
})(window);
