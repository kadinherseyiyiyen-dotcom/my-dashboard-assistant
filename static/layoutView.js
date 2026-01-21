(function () {
  function showToast(message) {
    var toast = document.createElement('div');
    toast.className = 'layout-toast';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(function () {
      toast.remove();
    }, 2000);
  }

  function normalizeTables(tables) {
    var list = [];
    if (Array.isArray(tables)) {
      return tables;
    }
    if (tables && typeof tables === 'object') {
      Object.keys(tables).forEach(function (key) {
        list.push({ id: Number(key), name: tables[key] });
      });
    }
    list.sort(function (a, b) { return a.id - b.id; });
    return list;
  }

  function normalizeLayout(data) {
    if (!data) return {};
    if (Array.isArray(data)) {
      var map = {};
      data.forEach(function (item) {
        if (!item) return;
        var key = String(item.table_id);
        map[key] = {
          pos_x: Number(item.pos_x || 0),
          pos_y: Number(item.pos_y || 0),
          width: Number(item.width || 120),
          height: Number(item.height || 90),
          rotation: Number(item.rotation || 0),
          area: item.area || 'salon'
        };
      });
      return map;
    }
    return data;
  }

  function defaultLayoutFor(id) {
    var cols = 5;
    var width = 120;
    var height = 90;
    var gap = 16;
    var idx = id - 1;
    var col = idx % cols;
    var row = Math.floor(idx / cols);
    return {
      pos_x: 16 + col * (width + gap),
      pos_y: 16 + row * (height + gap),
      width: width,
      height: height,
      rotation: 0,
      area: 'salon'
    };
  }

  function createLayoutView(opts) {
    var state = {
      area: opts.area || 'salon',
      viewMode: 'grid',
      editMode: false,
      layoutMap: {},
      tables: [],
      occupied: {},
      meta: {},
      canvas: null,
      grid: null,
      viewGridBtn: null,
      viewLayoutBtn: null,
      editToggle: null,
      editToggleWrapper: null,
      saveBtn: null,
      onTableClick: null,
      interactReady: false
    };

    function applyViewMode() {
      if (!state.canvas || !state.grid) return;
      if (state.viewMode === 'layout') {
        state.grid.classList.add('layout-hidden');
        state.canvas.classList.remove('layout-hidden');
      } else {
        state.grid.classList.remove('layout-hidden');
        state.canvas.classList.add('layout-hidden');
      }
      if (state.editToggleWrapper) {
        state.editToggleWrapper.style.display = state.viewMode === 'layout' ? 'flex' : 'none';
      }
      if (state.saveBtn) {
        state.saveBtn.style.display = state.viewMode === 'layout' && state.editMode ? 'inline-flex' : 'none';
      }
    }

    function setViewMode(mode) {
      state.viewMode = mode === 'layout' ? 'layout' : 'grid';
      localStorage.setItem('viewMode', state.viewMode);
      if (state.viewMode === 'grid') {
        setEditMode(false);
      }
      applyViewMode();
    }

    function setEditMode(enabled) {
      state.editMode = !!enabled;
      if (state.editToggle) {
        if (state.editToggle.tagName === 'INPUT') {
          state.editToggle.checked = state.editMode;
        } else {
          var input = state.editToggle.querySelector('input');
          if (input) input.checked = state.editMode;
        }
      }
      if (state.saveBtn) {
        state.saveBtn.style.display = state.viewMode === 'layout' && state.editMode ? 'inline-flex' : 'none';
      }
      setupInteract();
    }

    function fetchLayout() {
      return fetch('/api/tables-layout?area=' + encodeURIComponent(state.area))
        .then(function (res) { return res.json(); })
        .then(function (data) {
          state.layoutMap = normalizeLayout(data);
          localStorage.setItem('tablesLayout_' + state.area, JSON.stringify(state.layoutMap));
          renderLayout();
        })
        .catch(function () {
          try {
            var cached = localStorage.getItem('tablesLayout_' + state.area);
            if (cached) state.layoutMap = JSON.parse(cached);
          } catch (e) {
            state.layoutMap = {};
          }
          renderLayout();
        });
    }

    function saveLayout() {
      var tables = [];
      Object.keys(state.layoutMap).forEach(function (key) {
        var item = state.layoutMap[key];
        tables.push({
          table_id: Number(key),
          pos_x: Math.round(item.pos_x),
          pos_y: Math.round(item.pos_y),
          width: Math.round(item.width),
          height: Math.round(item.height),
          rotation: Math.round(item.rotation || 0)
        });
      });

      return fetch('/api/tables-layout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ area: state.area, tables: tables })
      })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (!data || data.success === false) {
            throw new Error('save failed');
          }
          showToast('Kaydedildi');
        })
        .catch(function () {
          try {
            localStorage.setItem('tablesLayout_' + state.area, JSON.stringify(state.layoutMap));
          } catch (e) {}
          showToast("API yok, localStorage'a kaydedildi");
        });
    }

    function renderLayout() {
      if (!state.canvas) return;
      state.canvas.innerHTML = '';
      state.tables.forEach(function (table) {
        var id = table.id;
        var key = String(id);
        if (!state.layoutMap[key]) {
          state.layoutMap[key] = defaultLayoutFor(id);
        }
        var pos = state.layoutMap[key];
        var card = document.createElement('div');
        card.className = 'table-card layout-table' + (state.occupied[key] ? ' occupied' : '');
        card.dataset.tableId = key;
        card.style.left = pos.pos_x + 'px';
        card.style.top = pos.pos_y + 'px';
        card.style.width = pos.width + 'px';
        card.style.height = pos.height + 'px';
        card.style.transform = 'rotate(' + (pos.rotation || 0) + 'deg)';
        var meta = state.meta[key] || {};
        var kisi = meta.kisi || 0;
        var sure = meta.sure || '--';
        var toplam = meta.toplam || (state.occupied[key] ? '' : 'Bos');
        var minutes = meta.minutes || 0;
        if (!minutes && typeof sure === 'string') {
          var match = sure.match(/(\d+)\s*dk/i);
          minutes = match ? parseInt(match[1], 10) : 0;
        }
        card.innerHTML = '' +
          '<div class="table-progress" aria-hidden="true"></div>' +
          '<div class="table-name">' + (table.name || ('Masa ' + id)) + '</div>' +
          '<div class="table-amount">' + toplam + '</div>' +
          '<div class="table-meta">' +
          '<span>&#x1F464; ' + kisi + ' kisi &#x23F1;&#xFE0F; ' + sure + '</span>' +
          '</div>';
        if (minutes) {
          card.dataset.minutes = minutes;
        }
        card.addEventListener('click', function (e) {
          if (state.editMode) {
            e.preventDefault();
            return;
          }
          if (typeof state.onTableClick === 'function') {
            state.onTableClick(id, card);
          }
        });
        state.canvas.appendChild(card);
      });
      setupInteract();
    }

    function setupInteract() {
      if (!window.interact) return;
      if (!state.canvas) return;
      if (!state.interactReady) {
        state.interactReady = true;
        window.interact('.layout-table')
          .draggable({
            modifiers: [
              window.interact.modifiers.restrictRect({ restriction: 'parent', endOnly: true }),
              window.interact.modifiers.snap({ targets: [window.interact.snappers.grid({ x: 10, y: 10 })], range: 5 })
            ],
            listeners: {
              move: function (event) {
                if (!state.editMode) return;
                var target = event.target;
                var id = target.dataset.tableId;
                var x = (parseFloat(target.dataset.x) || parseFloat(target.style.left) || 0) + event.dx;
                var y = (parseFloat(target.dataset.y) || parseFloat(target.style.top) || 0) + event.dy;
                target.style.left = x + 'px';
                target.style.top = y + 'px';
                target.dataset.x = x;
                target.dataset.y = y;
                if (state.layoutMap[id]) {
                  state.layoutMap[id].pos_x = x;
                  state.layoutMap[id].pos_y = y;
                }
              }
            }
          })
          .resizable({
            edges: { left: true, right: true, bottom: true, top: true },
            modifiers: [
              window.interact.modifiers.restrictEdges({ outer: 'parent' }),
              window.interact.modifiers.restrictSize({ min: { width: 90, height: 70 } })
            ],
            listeners: {
              move: function (event) {
                if (!state.editMode) return;
                var target = event.target;
                var id = target.dataset.tableId;
                var x = (parseFloat(target.dataset.x) || parseFloat(target.style.left) || 0) + event.deltaRect.left;
                var y = (parseFloat(target.dataset.y) || parseFloat(target.style.top) || 0) + event.deltaRect.top;
                target.style.width = event.rect.width + 'px';
                target.style.height = event.rect.height + 'px';
                target.style.left = x + 'px';
                target.style.top = y + 'px';
                target.dataset.x = x;
                target.dataset.y = y;
                if (state.layoutMap[id]) {
                  state.layoutMap[id].pos_x = x;
                  state.layoutMap[id].pos_y = y;
                  state.layoutMap[id].width = event.rect.width;
                  state.layoutMap[id].height = event.rect.height;
                }
              }
            }
          });
      }
      window.interact('.layout-table').draggable(state.editMode).resizable(state.editMode);
    }

    function setData(tables, occupied, onTableClick, meta) {
      state.tables = normalizeTables(tables);
      state.occupied = occupied || {};
      state.onTableClick = onTableClick;
      state.meta = meta || {};
      renderLayout();
    }

    function init() {
      state.canvas = document.getElementById(opts.canvasId);
      state.grid = document.getElementById(opts.gridId);
      state.viewGridBtn = document.getElementById(opts.viewGridBtnId);
      state.viewLayoutBtn = document.getElementById(opts.viewLayoutBtnId);
      state.editToggle = document.getElementById(opts.editToggleId);
      if (state.editToggle) {
        state.editToggleWrapper = state.editToggle.tagName === 'INPUT'
          ? state.editToggle.parentElement
          : state.editToggle;
      }
      state.saveBtn = document.getElementById(opts.saveBtnId);

      var stored = localStorage.getItem('viewMode');
      if (stored === 'layout' || stored === 'grid') {
        state.viewMode = stored;
      }

      if (state.viewGridBtn) {
        state.viewGridBtn.addEventListener('click', function () { setViewMode('grid'); });
      }
      if (state.viewLayoutBtn) {
        state.viewLayoutBtn.addEventListener('click', function () { setViewMode('layout'); });
      }
      if (state.editToggle) {
        state.editToggle.addEventListener('change', function (e) {
          setEditMode(e.target.checked);
        });
      }
      if (state.saveBtn) {
        state.saveBtn.addEventListener('click', function () { saveLayout(); });
      }

      applyViewMode();
      fetchLayout();
      return {
        setData: setData,
        setViewMode: setViewMode,
        setEditMode: setEditMode
      };
    }

    return { init: init, setData: setData };
  }

  window.LayoutView = {
    init: function (opts) {
      return createLayoutView(opts).init();
    }
  };
})();
