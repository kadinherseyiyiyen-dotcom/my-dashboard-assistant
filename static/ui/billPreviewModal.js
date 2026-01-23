(function (global) {
  'use strict';

  var modalId = 'bill-preview-modal';
  var textId = 'bill-preview-text';
  var titleId = 'bill-preview-title';
  var confirmId = 'bill-preview-confirm';
  var hintId = 'bill-lang-hint';
  var langWrapId = 'bill-lang-select';
  var langInputName = 'bill-lang';
  var currentTableId = null;
  var selectedLang = null;
  var initDone = false;

  function showToast(type, message) {
    if (global.APP && global.APP.emit) {
      global.APP.emit('toast:show', { type: type, message: message });
      return;
    }
    alert(message);
  }

  function getModal() {
    return document.getElementById(modalId);
  }

  function open(tableId) {
    if (!global.UI || !global.UI.Api) return;
    currentTableId = tableId;
    var modal = getModal();
    var textNode = document.getElementById(textId);
    var titleNode = document.getElementById(titleId);
    var confirmBtn = document.getElementById(confirmId);
    if (!modal || !textNode || !titleNode) return;
    titleNode.textContent = 'Hesap Fi\u015fi \u00d6nizleme \u2014 Masa ' + tableId;
    textNode.textContent = 'Yukleniyor...';
    modal.style.display = 'block';

    bindOnce();
    selectedLang = null;
    setSelectedLang(localStorage.getItem('BILL_LANG') || '');
    if (confirmBtn) confirmBtn.disabled = !selectedLang;
    updateHint();
    loadPreview();
  }

  function close() {
    var modal = getModal();
    if (modal) modal.style.display = 'none';
    currentTableId = null;
    selectedLang = null;
  }

  function confirmAndPrint() {
    if (!currentTableId || !global.UI || !global.UI.Api) return;
    if (!selectedLang) {
      showToast('error', 'Lutfen dil secin');
      updateHint();
      return;
    }
    global.UI.Api.printBill(currentTableId, selectedLang).then(function () {
      showToast('success', 'Hesap fi\u015fi yazdirildi.');
      close();
    }).catch(function (err) {
      showToast('error', err && err.message ? err.message : 'Yazdirma basarisiz.');
    });
  }

  function bindOnce() {
    if (initDone) return;
    var btn = document.getElementById(confirmId);
    if (btn) {
      btn.addEventListener('click', confirmAndPrint);
    }
    var wrap = document.getElementById(langWrapId);
    if (wrap) {
      wrap.addEventListener('change', function (event) {
        var target = event.target;
        if (!target || target.name !== langInputName) return;
        setSelectedLang(target.value);
        loadPreview();
      });
    }
    initDone = true;
  }

  function setSelectedLang(lang) {
    selectedLang = (lang === 'tr' || lang === 'en') ? lang : null;
    var inputs = document.querySelectorAll('input[name="' + langInputName + '"]');
    inputs.forEach(function (input) {
      input.checked = selectedLang === input.value;
    });
    if (selectedLang) {
      localStorage.setItem('BILL_LANG', selectedLang);
    }
    var btn = document.getElementById(confirmId);
    if (btn) {
      btn.textContent = selectedLang === 'en' ? 'Confirm & Print' : 'Onayla ve Yazd\u0131r';
    }
  }

  function updateHint() {
    var hint = document.getElementById(hintId);
    var btn = document.getElementById(confirmId);
    if (btn) btn.disabled = !selectedLang;
    if (!hint) return;
    hint.style.display = selectedLang ? 'none' : 'block';
  }

  function loadPreview() {
    if (!currentTableId || !global.UI || !global.UI.Api) return;
    var textNode = document.getElementById(textId);
    if (!textNode) return;
    if (!selectedLang) {
      textNode.textContent = 'Lutfen dil secin';
      updateHint();
      return;
    }
    textNode.textContent = 'Yukleniyor...';
    global.UI.Api.getBillPreview(currentTableId, selectedLang).then(function (data) {
      if (data && data.text) {
        textNode.textContent = data.text;
      } else {
        textNode.textContent = 'Onizleme hazirlanamadi.';
      }
      updateHint();
    }).catch(function (err) {
      textNode.textContent = 'Onizleme alinamadi.';
      updateHint();
      showToast('error', err && err.message ? err.message : 'Yazdirma basarisiz.');
    });
  }

  global.UI = global.UI || {};
  global.UI.BillPreviewModal = {
    open: open,
    close: close,
    confirmAndPrint: confirmAndPrint
  };
})(window);
