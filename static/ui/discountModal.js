(function (global) {
  'use strict';

  var modalId = 'discount-modal';
  var typePercentId = 'discount-type-percent';
  var typeAmountId = 'discount-type-amount';
  var valueId = 'discount-value';
  var reasonId = 'discount-reason';
  var noteId = 'discount-note';
  var noteWrapId = 'discount-note-wrap';
  var applyId = 'discount-apply';
  var hintId = 'discount-hint';

  var state = {
    orderId: null,
    subtotal: 0,
    existing: null
  };

  function showToast(type, message) {
    if (global.APP && global.APP.emit) {
      global.APP.emit('toast:show', { type: type, message: message });
      return;
    }
    alert(message);
  }

  function open(orderId, subtotal, existing) {
    state.orderId = orderId;
    state.subtotal = subtotal || 0;
    state.existing = existing || null;
    var modal = document.getElementById(modalId);
    if (!modal) return;
    resetForm();
    if (existing) {
      if (existing.type === 'amount') {
        document.getElementById(typeAmountId).checked = true;
      } else {
        document.getElementById(typePercentId).checked = true;
      }
      document.getElementById(valueId).value = existing.value || '';
      document.getElementById(reasonId).value = existing.reason || 'tanidik';
      document.getElementById(noteId).value = existing.note || '';
    }
    toggleNote();
    modal.style.display = 'block';
    bindOnce();
  }

  function close() {
    var modal = document.getElementById(modalId);
    if (modal) modal.style.display = 'none';
    state.orderId = null;
  }

  function resetForm() {
    var percent = document.getElementById(typePercentId);
    if (percent) percent.checked = true;
    var value = document.getElementById(valueId);
    if (value) value.value = '';
    var reason = document.getElementById(reasonId);
    if (reason) reason.value = 'tanidik';
    var note = document.getElementById(noteId);
    if (note) note.value = '';
    var hint = document.getElementById(hintId);
    if (hint) hint.textContent = '';
  }

  function toggleNote() {
    var reason = document.getElementById(reasonId);
    var wrap = document.getElementById(noteWrapId);
    if (!reason || !wrap) return;
    wrap.style.display = reason.value === 'diger' ? 'block' : 'none';
  }

  function submit() {
    if (!state.orderId || !global.UI || !global.UI.Api) return;
    var type = document.getElementById(typeAmountId).checked ? 'amount' : 'percent';
    var value = parseFloat(document.getElementById(valueId).value || 0);
    var reason = document.getElementById(reasonId).value;
    var note = document.getElementById(noteId).value.trim();
    var hint = document.getElementById(hintId);
    if (hint) hint.textContent = '';

    if (!value || value <= 0) {
      if (hint) hint.textContent = 'Indirim degeri gerekli.';
      return;
    }
    if (type === 'percent' && (value < 1 || value > 100)) {
      if (hint) hint.textContent = 'Indirim yuzdesi 1-100 araliginda olmali.';
      return;
    }
    if (reason === 'diger' && !note) {
      if (hint) hint.textContent = 'Aciklama gerekli.';
      return;
    }

    var payload = { type: type, value: value, reason: reason, note: note };
    global.UI.Api.applyDiscount(state.orderId, payload).then(function () {
      showToast('success', 'Indirim uygulandi.');
      close();
      if (global.APP && global.APP.emit) {
        global.APP.emit('order:updated', { orderId: state.orderId });
        global.APP.emit('tables:updated');
      }
      if (global.refreshHesapModal) {
        global.refreshHesapModal();
      }
    }).catch(function (err) {
      showToast('error', err && err.message ? err.message : 'Indirim uygulanamadi.');
    });
  }

  var bound = false;
  function bindOnce() {
    if (bound) return;
    var reason = document.getElementById(reasonId);
    if (reason) {
      reason.addEventListener('change', toggleNote);
    }
    var apply = document.getElementById(applyId);
    if (apply) {
      apply.addEventListener('click', submit);
    }
    bound = true;
  }

  global.UI = global.UI || {};
  global.UI.DiscountModal = {
    open: open,
    close: close
  };
})(window);
