/* global window, document */
(function (global) {
  'use strict';

  /*
    Public API:
      PaymentModal.open(payload)
      PaymentModal.close()
      PaymentModal.addPaymentRow(type, amount, meta)
      PaymentModal.fillRemaining(type)
  */

  var root = null;
  var rowsHost = null;
  var totalEl = null;
  var enteredEl = null;
  var remainingEl = null;
  var discountEl = null;
  var warningEl = null;
  var completeBtn = null;
  var addBtn = null;
  var fillCashBtn = null;
  var fillCardBtn = null;
  var current = null;
  var disableDiscount = false;
  var bound = false;
  var rootId = 'payment-split-area';

  function formatMoney(value) {
    var num = Number(value);
    if (!Number.isFinite(num)) num = 0;
    try {
      return new Intl.NumberFormat('tr-TR', {
        style: 'currency',
        currency: 'TRY',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(num);
    } catch (err) {
      return '\u20BA' + num.toFixed(2);
    }
  }

  function ensureRoot(id) {
    var targetId = id || rootId;
    if (root && root.id === targetId) return;
    rootId = targetId;
    root = document.getElementById(targetId);
    if (!root) return;
    rowsHost = root.querySelector('#payment-rows');
    totalEl = root.querySelector('#payment-grand-total');
    enteredEl = root.querySelector('#payment-entered');
    remainingEl = root.querySelector('#payment-remaining');
    discountEl = root.querySelector('#payment-discount-note');
    warningEl = root.querySelector('#payment-warning');
    completeBtn = root.querySelector('#payment-complete');
    addBtn = root.querySelector('#payment-add');
    fillCashBtn = root.querySelector('#payment-fill-cash');
    fillCardBtn = root.querySelector('#payment-fill-card');

    if (bound) return;
    bound = true;

    if (addBtn) addBtn.addEventListener('click', function () { addPaymentRow(); });
    if (fillCashBtn) fillCashBtn.addEventListener('click', function () { fillRemaining('cash'); });
    if (fillCardBtn) fillCardBtn.addEventListener('click', function () { fillRemaining('card'); });
    if (completeBtn) completeBtn.addEventListener('click', submit);
  }

  function open(payload) {
    ensureRoot(payload && payload.containerId);
    current = payload || {};
    disableDiscount = !!(payload && payload.disableDiscount);
    if (!root) return;
    if (rowsHost) rowsHost.innerHTML = '';
    if (warningEl) warningEl.textContent = '';
    if (discountEl) discountEl.textContent = '';
    addPaymentRow('cash', '');
    recalcTotals();
    root.style.display = 'block';
  }

  function close() {
    if (root) root.style.display = 'none';
    current = null;
  }

  function getRows() {
    var rows = [];
    if (!rowsHost) return rows;
    rowsHost.querySelectorAll('.payment-row').forEach(function (row) {
      var type = row.querySelector('.payment-type');
      var amount = row.querySelector('.payment-amount');
      var meta = row.querySelector('.payment-meta');
      rows.push({
        type: type ? type.value : 'cash',
        amount: amount ? amount.value : '',
        meta: meta ? meta.value : ''
      });
    });
    return rows;
  }

  function addPaymentRow(type, amount, meta) {
    if (!rowsHost) return;
    var row = document.createElement('div');
    row.className = 'payment-row';
    row.innerHTML = ''
      + '<select class="payment-type">'
      + '<option value="cash">Nakit</option>'
      + '<option value="card">Kart</option>'
      + '<option value="qr">QR</option>'
      + '<option value="other">Diger</option>'
      + '</select>'
      + '<input class="payment-amount" type="number" min="0" step="0.01" placeholder="Tutar (TL)">'
      + '<input class="payment-meta" type="text" placeholder="Kart etiketi / banka (opsiyonel)">'
      + '<button type="button" class="payment-remove" aria-label="Sil">x</button>';
    rowsHost.appendChild(row);

    var typeEl = row.querySelector('.payment-type');
    var amountEl = row.querySelector('.payment-amount');
    var metaEl = row.querySelector('.payment-meta');
    var removeEl = row.querySelector('.payment-remove');

    if (typeEl && type) typeEl.value = type;
    if (amountEl && amount !== undefined) amountEl.value = amount;
    if (metaEl && meta !== undefined) metaEl.value = meta;

    function handleChange() {
      if (metaEl) {
        metaEl.style.display = (typeEl && typeEl.value === 'card') ? 'block' : 'none';
      }
      recalcTotals();
    }

    if (typeEl) typeEl.addEventListener('change', handleChange);
    if (amountEl) amountEl.addEventListener('input', handleChange);
    handleChange();

    if (removeEl) {
      removeEl.addEventListener('click', function () {
        if (rowsHost.childElementCount <= 1) return;
        row.remove();
        recalcTotals();
      });
    }
  }

  function getTotalDue(rows) {
    var total = Number(current && current.total) || 0;
    var cashOnly = !disableDiscount && rows.length > 0 && rows.every(function (r) { return r.type === 'cash'; });
    var due = cashOnly ? (total * 0.9) : total;
    return { total: total, due: Math.round(due * 100) / 100, cashOnly: cashOnly };
  }

  function recalcTotals() {
    var rows = getRows();
    var paid = rows.reduce(function (sum, row) {
      var val = parseFloat(String(row.amount || '').replace(',', '.'));
      if (!Number.isFinite(val)) val = 0;
      return sum + val;
    }, 0);
    var dueInfo = getTotalDue(rows);
    var remaining = dueInfo.due - paid;

    if (totalEl) totalEl.textContent = formatMoney(dueInfo.due);
    if (enteredEl) enteredEl.textContent = formatMoney(paid);
    if (remainingEl) remainingEl.textContent = formatMoney(Math.max(remaining, 0));
    if (discountEl) {
      discountEl.textContent = dueInfo.cashOnly ? 'Nakit indirimli toplam' : '';
    }

    if (warningEl) warningEl.textContent = remaining < 0 ? 'Fazla odeme girdiniz.' : '';
    if (completeBtn) {
      var valid = rows.length > 0 && remaining === 0 && paid > 0;
      completeBtn.disabled = !valid;
    }
  }

  function fillRemaining(type) {
    var rows = getRows();
    var dueInfo = getTotalDue(rows);
    var paid = rows.reduce(function (sum, row) {
      var val = parseFloat(String(row.amount || '').replace(',', '.'));
      if (!Number.isFinite(val)) val = 0;
      return sum + val;
    }, 0);
    var remaining = Math.max(dueInfo.due - paid, 0);
    if (remaining <= 0) return;
    addPaymentRow(type, remaining.toFixed(2));
    recalcTotals();
  }

  function submit() {
    if (!current) return;
    var rows = getRows();
    var payments = rows.map(function (row) {
      return {
        type: row.type,
        amount: parseFloat(String(row.amount || '').replace(',', '.')),
        meta: row.meta || ''
      };
    });
    if (!global.UI || !global.UI.Api) return;

    var promise = null;
    if (current.orderId) {
      promise = global.UI.Api.createPayments(current.orderId, payments);
    } else if (current.tableId) {
      var options = null;
      if (disableDiscount) {
        options = { discount_applied: false };
      }
      promise = global.UI.Api.closeTablePayments(current.tableId, payments, options);
    }
    if (!promise) return;

    if (completeBtn) completeBtn.disabled = true;
    promise.then(function () {
      if (global.APP && global.APP.emit) {
        global.APP.emit('order:paid', { orderId: current.orderId || null, tableId: current.tableId || null });
        global.APP.emit('tables:updated');
        global.APP.emit('toast:show', { type: 'success', message: 'Odeme alindi.' });
      }
      close();
      if (typeof global.yenile === 'function') global.yenile();
      if (typeof global.modalKapat === 'function') global.modalKapat();
    }).catch(function (err) {
      if (warningEl) warningEl.textContent = (err && err.message) ? err.message : 'Odeme alinamadi.';
    }).finally(function () {
      if (completeBtn) completeBtn.disabled = false;
    });
  }

  global.UI = global.UI || {};
  global.UI.PaymentModal = {
    open: open,
    close: close,
    addPaymentRow: addPaymentRow,
    fillRemaining: fillRemaining,
    recalcTotals: recalcTotals
  };
})(window);
