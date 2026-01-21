(function () {
  function parseMinutes(text) {
    if (!text) return 0;
    var match = String(text).match(/(\d+)\s*dk/i);
    return match ? parseInt(match[1], 10) : 0;
  }

  function applyTableProgressBorder(cardEl, minutes) {
    if (!cardEl) return;
    var overlay = cardEl.querySelector('.table-progress');
    if (!overlay) return;
    var mins = Number(minutes || 0);
    if (!mins || mins <= 0) {
      overlay.classList.add('hidden');
      overlay.classList.remove('pulse');
      return;
    }
    overlay.classList.remove('hidden');
    var percent = Math.min(mins / 30, 1);
    var angle = Math.round(percent * 360);
    var color = '#22c55e';
    var pulse = false;
    if (mins >= 60) {
      color = '#ef4444';
      pulse = true;
    } else if (mins >= 30) {
      color = '#f59e0b';
    }
    overlay.style.setProperty('--prog-angle', angle + 'deg');
    overlay.style.setProperty('--prog-color', color);
    overlay.classList.toggle('pulse', pulse);
  }

  function getMinutesFromCard(cardEl) {
    if (!cardEl) return 0;
    var dataMinutes = cardEl.getAttribute('data-minutes');
    if (dataMinutes) {
      var parsed = parseInt(dataMinutes, 10);
      return Number.isFinite(parsed) ? parsed : 0;
    }
    var meta = cardEl.querySelector('.table-meta');
    if (!meta) return 0;
    return parseMinutes(meta.textContent || '');
  }

  function initTableProgressBorders(rootEl, getMinutesByTableIdFn) {
    var root = rootEl || document;

    function update() {
      var cards = root.querySelectorAll('.table-card');
      cards.forEach(function (card) {
        var id = card.getAttribute('data-masa') || card.getAttribute('data-table-id');
        var minutes = null;
        if (typeof getMinutesByTableIdFn === 'function') {
          minutes = getMinutesByTableIdFn(id, card);
        }
        if (minutes == null) {
          minutes = getMinutesFromCard(card);
        }
        applyTableProgressBorder(card, minutes);
      });
    }

    update();
    var interval = setInterval(update, 10000);
    return {
      update: update,
      destroy: function () { clearInterval(interval); }
    };
  }

  window.TableProgressBorder = {
    applyTableProgressBorder: applyTableProgressBorder,
    initTableProgressBorders: initTableProgressBorders
  };
})();
