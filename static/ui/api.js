/* global window */
(function (global) {
  'use strict';

  /*
    Public API:
      Api.getTables() -> Promise<{ orders, tables, rehber, table_sessions }>
      Api.getFxRates() -> Promise<{ usd, eur, sar }>
      Api.getDensity(orders) -> { activeTables, lastOrders5m, score, label }
      Api.getStaff() -> Promise<Array>
      Api.createStaff(name) -> Promise<Object>
      Api.updateStaff(id, payload) -> Promise<Object>
      Api.deleteStaff(id) -> Promise<Object>
      Api.getStaffStats(date) -> Promise<Array>
      Api.getMenu() -> Promise<Object>
        Api.getStaffProductBreakdown(staffId, date) -> Promise<Object>
        Api.getStaffOrders(staffId, date) -> Promise<Object>
        Api.createOrder(payload) -> Promise<Object>
        Api.createPayments(orderId, payments) -> Promise<Object>
        Api.getPayments(orderId) -> Promise<Object>
        Api.closeTablePayments(tableId, payments) -> Promise<Object>
        Api.getBillPreview(tableId, lang) -> Promise<Object>
      Api.printBill(tableId) -> Promise<Object>
      Api.applyDiscount(orderId, payload) -> Promise<Object>
      Api.removeDiscount(orderId) -> Promise<Object>
      Api.getRecentClosures(limit) -> Promise<Array>
      Api.reopenOrder(orderId) -> Promise<Object>
      Api.setBillRequested(tableId, value) -> Promise<Object>
      Api.getWeather() -> Promise<Object>
  */

  function requestJson(url, method, body, opts) {
    var options = { method: method || 'GET' };
    if (body) {
      options.headers = { 'Content-Type': 'application/json' };
      options.body = JSON.stringify(body);
    }
    return global.APP.safeFetch(url, options, opts);
  }

  function getTables() {
    var state = global.APP && global.APP.state;
    return global.APP.safeFetch('/api/kasa-init', null, {
      cacheKey: 'kasa_init',
      errorMessage: 'Masalar alinamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Yukleme hatasi');
      if (state) {
        state.lastFetchTimes.tables = Date.now();
        state.lastError = null;
      }
      return data;
    });
  }

  function getFxRates() {
    var state = global.APP && global.APP.state;
    var usdUrl = 'https://api.frankfurter.app/latest?from=USD&to=TRY';
    var eurUrl = 'https://api.frankfurter.app/latest?from=EUR&to=TRY';
    var sarUrl = 'https://open.er-api.com/v6/latest/SAR';
    return Promise.all([
      global.APP.safeFetch(usdUrl, null, { cacheKey: 'fx_usd', errorMessage: 'Kur alinamadi.' }),
      global.APP.safeFetch(eurUrl, null, { cacheKey: 'fx_eur', errorMessage: 'Kur alinamadi.' }),
      global.APP.safeFetch(sarUrl, null, { cacheKey: 'fx_sar', errorMessage: 'Kur alinamadi.' })
    ]).then(function (results) {
      var usdData = results[0];
      var eurData = results[1];
      var sarData = results[2];
      var usd = usdData && usdData.rates ? usdData.rates.TRY : null;
      var eur = eurData && eurData.rates ? eurData.rates.TRY : null;
      var sar = sarData && sarData.rates ? sarData.rates.TRY : null;
      if (!usd || !eur) throw new Error('Kur alinamadi');
      if (state) {
        state.lastFetchTimes.fx = Date.now();
        state.lastError = null;
      }
      return { usd: usd, eur: eur, sar: sar };
    });
  }

  function getDensity(orders, activeFallback, config) {
    var cfg = config || (global.CONFIG && global.CONFIG.density) || {};
    var aktifMasa = (orders || []).filter(function (o) { return o.durum === 'aktif'; })
      .map(function (o) { return String(o.masa); })
      .filter(function (v, i, a) { return a.indexOf(v) === i; }).length || activeFallback || 0;

    var now = new Date();
    var fiveMinAgo = now.getTime() - (5 * 60 * 1000);
    var son5dkSiparis = 0;
    (orders || []).forEach(function (order) {
      if (order.durum !== 'aktif') return;
      var tarih = order.tarih || '';
      var zaman = order.zaman || '00:00';
      var dt = null;
      if (tarih.indexOf('.') !== -1) {
        var parts = tarih.split('.');
        if (parts.length >= 3) {
          var gun = parseInt(parts[0], 10);
          var ay = parseInt(parts[1], 10) - 1;
          var yil = parseInt(parts[2], 10);
          var time = zaman.split(':');
          dt = new Date(yil, ay, gun, parseInt(time[0] || 0, 10), parseInt(time[1] || 0, 10));
        }
      }
      if (dt && dt.getTime() >= fiveMinAgo) {
        son5dkSiparis += 1;
      }
    });

    var score = 0;
    if (aktifMasa <= 0) {
      score = 0;
    } else if (aktifMasa < 7) {
      score = (aktifMasa / 7) * 50;
    } else if (aktifMasa < 10) {
      score = 50 + ((aktifMasa - 7) / 3) * 25;
    } else if (aktifMasa < 15) {
      score = 75 + ((aktifMasa - 10) / 5) * 25;
    } else {
      score = 100;
    }
    score = Math.min(100, Math.max(0, Math.round(score)));
    var label = 'Dusuk';
    if (aktifMasa >= 10) {
      label = 'Yogun';
    } else if (aktifMasa >= 7) {
      label = 'Artiyor';
    }

    return {
      activeTables: aktifMasa,
      lastOrders5m: son5dkSiparis,
      score: score,
      label: label
    };
  }

  function getStaff() {
    var state = global.APP && global.APP.state;
    return requestJson('/api/staff', 'GET', null, {
      cacheKey: 'staff',
      errorMessage: 'Garson listesi alinamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Yukleme hatasi');
      if (state) {
        state.lastFetchTimes.staff = Date.now();
        state.lastError = null;
        state.staff = data.staff || [];
      }
      return data.staff || [];
    });
  }

  function createStaff(name, pin) {
    var payload = { name: name };
    if (pin) payload.pin = pin;
    return requestJson('/api/staff', 'POST', payload, {
      errorMessage: 'Garson eklenemedi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Kaydetme hatasi');
      return data;
    });
  }

  function updateStaff(id, payload) {
    return requestJson('/api/staff/' + id, 'PATCH', payload || {}, {
      errorMessage: 'Garson guncellenemedi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Guncelleme hatasi');
      return data;
    });
  }

  function deleteStaff(id) {
    return requestJson('/api/staff/' + id, 'DELETE', null, {
      errorMessage: 'Garson silinemedi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Silme hatasi');
      return data;
    });
  }

  function getStaffStats(dateInput) {
    var state = global.APP && global.APP.state;
    var date = '';
    var start = '';
    var end = '';
    if (typeof dateInput === 'string') {
      date = dateInput;
    } else if (dateInput && dateInput.date) {
      date = dateInput.date;
    } else if (dateInput && (dateInput.start || dateInput.end)) {
      start = dateInput.start || '';
      end = dateInput.end || '';
    }
    var params = [];
    if (date) params.push('date=' + encodeURIComponent(date));
    if (start) params.push('start=' + encodeURIComponent(start));
    if (end) params.push('end=' + encodeURIComponent(end));
    var url = '/api/staff/stats' + (params.length ? ('?' + params.join('&')) : '');
    return requestJson(url, 'GET', null, {
      cacheKey: 'staff_stats_' + (date || (start + '_' + end) || 'today'),
      errorMessage: 'Garson istatistikleri alinamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Yukleme hatasi');
      var stats = Array.isArray(data) ? data : (data && data.stats ? data.stats : []);
      if (state) {
        state.lastFetchTimes.staffStats = Date.now();
        state.lastError = null;
        state.staffStatsDate = date || (data && data.date) || null;
        state.staffStatsRange = (start || end) ? { start: start || null, end: end || null } : null;
        state.staffStats = stats;
      }
      if (global.APP && global.APP.emit) {
        global.APP.emit('staffStats:updated', { date: date || null, stats: stats });
      }
      return stats;
    });
  }

  function createOrder(payload) {
    return requestJson('/api/siparis', 'POST', payload || {}, {
      errorMessage: 'Siparis kaydedilemedi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Kaydetme hatasi');
      return data;
    });
  }

  function createPayments(orderId, payments) {
    return requestJson('/api/orders/' + orderId + '/payments', 'POST', { payments: payments || [] }, {
      errorMessage: 'Odeme kaydedilemedi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Kaydetme hatasi');
      return data;
    });
  }

  function getPayments(orderId) {
    return requestJson('/api/orders/' + orderId + '/payments', 'GET', null, {
      errorMessage: 'Odeme listesi alinamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Yukleme hatasi');
      return data;
    });
  }

  function closeTablePayments(tableId, payments, options) {
    var payload = { payments: payments || [] };
    if (options && Object.prototype.hasOwnProperty.call(options, 'discount_applied')) {
      payload.discount_applied = options.discount_applied;
    }
    if (options && options.manual) {
      payload.manual = options.manual;
    }
    return requestJson('/api/hesap_kapat/' + tableId, 'POST', payload, {
      errorMessage: 'Odeme alinamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Kaydetme hatasi');
      return data;
    });
  }

  function printBill(tableId, lang) {
    return requestJson('/api/tables/' + tableId + '/print-bill', 'POST', { lang: lang }, {
      errorMessage: 'Hesap fisi yazdirilamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Yazdirma hatasi');
      return data;
    });
  }

  function getBillPreview(tableId, lang) {
    var url = '/api/tables/' + tableId + '/bill-preview';
    if (lang) url += '?lang=' + encodeURIComponent(lang);
    return requestJson(url, 'GET', null, {
      errorMessage: 'Hesap fisi alinamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Yukleme hatasi');
      return data;
    });
  }

  function applyDiscount(orderId, payload) {
    return requestJson('/api/orders/' + orderId + '/discount', 'POST', payload || {}, {
      errorMessage: 'Indirim uygulanamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Kaydetme hatasi');
      return data;
    });
  }

  function removeDiscount(orderId) {
    return requestJson('/api/orders/' + orderId + '/discount', 'DELETE', null, {
      errorMessage: 'Indirim kaldirilamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Silme hatasi');
      return data;
    });
  }

  function getRecentClosures(limit) {
    var url = '/api/orders/recent-closures';
    if (limit) url += '?limit=' + encodeURIComponent(limit);
    return requestJson(url, 'GET', null, {
      errorMessage: 'Son kapatilanlar alinamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Yukleme hatasi');
      return Array.isArray(data) ? data : (data && data.items ? data.items : []);
    });
  }

  function reopenOrder(orderId) {
    return requestJson('/api/orders/' + orderId + '/reopen', 'POST', {}, {
      errorMessage: 'Siparis yeniden acilamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Islem hatasi');
      return data;
    });
  }

  function setBillRequested(tableId, value) {
    return requestJson('/api/tables/' + tableId + '/bill-requested', 'POST', { value: !!value }, {
      errorMessage: 'Hesap istegi guncellenemedi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Islem hatasi');
      return data;
    });
  }

  function getWeather() {
    return requestJson('/api/weather', 'GET', null, {
      cacheKey: 'weather_current',
      errorMessage: 'Hava durumu alinamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Yukleme hatasi');
      return data || {};
    });
  }

  function getMenu() {
    return requestJson('/api/menu', 'GET', null, {
      cacheKey: 'menu',
      errorMessage: 'Menu alinamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Yukleme hatasi');
      return data;
    });
  }

  function getStaffProductBreakdown(staffId, dateInput) {
    var date = '';
    var start = '';
    var end = '';
    if (typeof dateInput === 'string') {
      date = dateInput;
    } else if (dateInput && dateInput.date) {
      date = dateInput.date;
    } else if (dateInput && (dateInput.start || dateInput.end)) {
      start = dateInput.start || '';
      end = dateInput.end || '';
    }
    var url = '/api/staff/' + staffId + '/product-breakdown';
    if (date) url += '?date=' + encodeURIComponent(date);
    if (!date && (start || end)) {
      var params = [];
      if (start) params.push('start=' + encodeURIComponent(start));
      if (end) params.push('end=' + encodeURIComponent(end));
      if (params.length) url += '?' + params.join('&');
    }
    return requestJson(url, 'GET', null, {
      cacheKey: 'staff_products_' + staffId + '_' + (date || (start + '_' + end) || 'today'),
      errorMessage: 'Urun kirilimi alinamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Yukleme hatasi');
      return data || {};
    });
  }

  function getStaffOrders(staffId, dateInput) {
    var date = '';
    var start = '';
    var end = '';
    if (typeof dateInput === 'string') {
      date = dateInput;
    } else if (dateInput && dateInput.date) {
      date = dateInput.date;
    } else if (dateInput && (dateInput.start || dateInput.end)) {
      start = dateInput.start || '';
      end = dateInput.end || '';
    }
    var url = '/api/staff/' + staffId + '/orders';
    if (date) url += '?date=' + encodeURIComponent(date);
    if (!date && (start || end)) {
      var params = [];
      if (start) params.push('start=' + encodeURIComponent(start));
      if (end) params.push('end=' + encodeURIComponent(end));
      if (params.length) url += '?' + params.join('&');
    }
    return requestJson(url, 'GET', null, {
      cacheKey: 'staff_orders_' + staffId + '_' + (date || (start + '_' + end) || 'today'),
      errorMessage: 'Siparis listesi alinamadi.'
    }).then(function (data) {
      if (data && data.success === false) throw new Error(data.message || 'Yukleme hatasi');
      return data || {};
    });
  }

  global.UI = global.UI || {};
  global.UI.Api = {
    getTables: getTables,
    getFxRates: getFxRates,
    getDensity: getDensity,
    getStaff: getStaff,
    createStaff: createStaff,
    updateStaff: updateStaff,
    deleteStaff: deleteStaff,
    getStaffStats: getStaffStats,
    getMenu: getMenu,
    getStaffProductBreakdown: getStaffProductBreakdown,
    getStaffOrders: getStaffOrders,
    createOrder: createOrder,
    createPayments: createPayments,
    getPayments: getPayments,
    closeTablePayments: closeTablePayments,
    getBillPreview: getBillPreview,
    printBill: printBill,
    applyDiscount: applyDiscount,
    removeDiscount: removeDiscount,
    getRecentClosures: getRecentClosures,
    reopenOrder: reopenOrder,
    setBillRequested: setBillRequested,
    getWeather: getWeather
  };
  global.Api = global.UI.Api;
})(window);
