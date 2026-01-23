/* global window, document */
(function (global) {
  'use strict';

  var panelId = 'recent-closures-panel';
  var listId = 'recent-closures-list';
  var emptyId = 'recent-closures-empty';
  var refreshId = 'recent-closures-refresh';
  var openBtnId = 'recent-closures-btn';
  var initDone = false;

  function getPanel() {
    return document.getElementById(panelId);
  }

  function open() {
    var panel = getPanel();
    if (!panel) return;
    panel.classList.add('open');
    loadList();
  }

  function close() {
    var panel = getPanel();
    if (!panel) return;
    panel.classList.remove('open');
  }

  function setLoading(loading) {
    var list = document.getElementById(listId);
    if (!list) return;
    list.setAttribute('data-loading', loading ? 'true' : 'false');
  }

  function renderList(items) {
    var list = document.getElementById(listId);
    var empty = document.getElementById(emptyId);
    if (!list || !empty) return;
    list.innerHTML = '';
    if (!items || !items.length) {
      empty.style.display = 'block';
      return;
    }
    empty.style.display = 'none';
    items.forEach(function (item) {
      var row = document.createElement('div');
      row.className = 'recent-row';
      row.innerHTML = `
        <div class="recent-main">
          <div class="recent-title">${item.table_name || ('Masa ' + item.table_id)}</div>
          <div class="recent-meta">
            <span>${item.closed_time || '--:--'}</span>
            <span>${item.payment_label || '-'}</span>
            <span>${item.staff_name || '-'}</span>
          </div>
        </div>
        <div class="recent-amount">${item.total_text || '--'}</div>
        <button class="btn btn-secondary recent-reopen" data-order="${item.order_id}">Geri Al</button>
      `;
      list.appendChild(row);
    });
  }

  function loadList() {
    if (!global.UI || !global.UI.Api || !global.UI.Api.getRecentClosures) return;
    setLoading(true);
    global.UI.Api.getRecentClosures(20).then(function (items) {
      renderList(items || []);
    }).catch(function (err) {
      if (global.APP && global.APP.emit) {
        global.APP.emit('toast:show', { type: 'error', message: err && err.message ? err.message : 'Liste alinamadi.' });
      }
    }).finally(function () {
      setLoading(false);
    });
  }

  function onReopenClick(event) {
    var btn = event.target.closest('.recent-reopen');
    if (!btn) return;
    var orderId = btn.getAttribute('data-order');
    if (!orderId || !global.UI || !global.UI.Api) return;
    if (!confirm('Bu kapatma islemi geri alinsin mi? Odeme iptal edilir ve masa tekrar acilir.')) return;
    btn.disabled = true;
    btn.textContent = '...';
    global.UI.Api.reopenOrder(orderId).then(function (data) {
      if (global.APP && global.APP.emit) {
        global.APP.emit('toast:show', { type: 'success', message: 'Masa yeniden acildi.' });
        global.APP.emit('order:reopened', { orderId: orderId, tableId: data && data.table_id });
      }
      if (typeof window.yenile === 'function') {
        window.yenile();
      }
      loadList();
    }).catch(function (err) {
      if (global.APP && global.APP.emit) {
        global.APP.emit('toast:show', { type: 'error', message: err && err.message ? err.message : 'Islem basarisiz.' });
      }
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = 'Geri Al';
    });
  }

  function bindOnce() {
    if (initDone) return;
    var openBtn = document.getElementById(openBtnId);
    if (openBtn) openBtn.addEventListener('click', open);
    var panel = getPanel();
    if (panel) {
      panel.addEventListener('click', function (event) {
        if (event.target && event.target.classList.contains('recent-closures-backdrop')) close();
      });
    }
    var list = document.getElementById(listId);
    if (list) list.addEventListener('click', onReopenClick);
    var refresh = document.getElementById(refreshId);
    if (refresh) refresh.addEventListener('click', loadList);
    initDone = true;
  }

  global.UI = global.UI || {};
  global.UI.RecentClosuresPanel = {
    open: function () { bindOnce(); open(); },
    close: close,
    refresh: loadList
  };
})(window);
