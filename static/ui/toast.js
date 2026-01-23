/* global window, document */
(function (global) {
  'use strict';

  /*
    Public API:
      Toast.show(message, durationMs)
  */

  function ensureHost() {
    var host = document.getElementById('toast-host');
    if (host) return host;
    host = document.createElement('div');
    host.id = 'toast-host';
    host.style.position = 'fixed';
    host.style.right = '16px';
    host.style.bottom = '16px';
    host.style.display = 'flex';
    host.style.flexDirection = 'column';
    host.style.gap = '8px';
    host.style.zIndex = '9999';
    document.body.appendChild(host);
    return host;
  }

  function show(message, durationMs) {
    var host = ensureHost();
    var toast = document.createElement('div');
    toast.textContent = message;
    toast.style.background = 'rgba(17, 24, 39, 0.95)';
    toast.style.color = '#fff';
    toast.style.padding = '10px 12px';
    toast.style.borderRadius = '10px';
    toast.style.fontSize = '0.85rem';
    toast.style.boxShadow = '0 8px 20px rgba(0,0,0,0.2)';
    host.appendChild(toast);

    var timeout = durationMs || 2200;
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, timeout);
  }

  global.UI = global.UI || {};
  global.UI.Toast = {
    show: show
  };
  global.Toast = global.UI.Toast;

  if (global.APP && global.APP.on) {
    global.APP.on('toast:show', function (payload) {
      if (!payload) return;
      var message = '';
      var duration = 2200;
      if (typeof payload === 'string') {
        message = payload;
      } else {
        message = payload.message || String(payload);
        if (payload.durationMs) duration = payload.durationMs;
      }
      show(String(message), duration);
    });
  }
})(window);
