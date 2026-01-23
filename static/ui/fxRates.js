/* global window, document, localStorage, fetch */
(function (global) {
  'use strict';

  /*
    Public API:
      FxRates.render({ usd, eur }, { usdId, eurId, liveId })
  */

  function render(data, ids) {
    var usdEl = document.getElementById(ids.usdId);
    var eurEl = document.getElementById(ids.eurId);
    var liveEl = document.getElementById(ids.liveId);
    if (!usdEl || !eurEl || !liveEl) return;
    if (!data || typeof data.usd !== 'number' || typeof data.eur !== 'number') {
      usdEl.textContent = 'Kur alinamadi';
      eurEl.textContent = '--';
      liveEl.innerHTML = '<span class="fx-dot">&#9679;</span> Canl\u0131';
      return;
    }
    usdEl.textContent = data.usd.toFixed(2);
    eurEl.textContent = data.eur.toFixed(2);
    liveEl.innerHTML = '<span class="fx-dot">&#9679;</span> Canl\u0131';
  }

  global.UI = global.UI || {};
  global.UI.FxRates = {
    render: render
  };
  global.FxRates = global.UI.FxRates;

  if (global.APP && global.APP.on) {
    global.APP.on('fx:updated', function (payload) {
      var ids = (payload && payload.ids) ? payload.ids : {
        usdId: 'fx-usd',
        eurId: 'fx-eur',
        liveId: 'fx-live'
      };
      render(payload, ids);
    });
  }
})(window);
