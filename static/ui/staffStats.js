/* global window, document */
(function (global) {
  'use strict';

  /*
    Public API:
      StaffStats.render(containerId, stats)
      StaffStats.init(containerId)
      StaffStats.bind(containerId)
      StaffStats.setSort(key)
  */

  var containerId = null;
  var sortKey = 'revenue';
  var sortDir = 'desc';
  var rowCache = {};
  var rowNodes = {};
  var detailNodes = {};
  var tableHost = null;
  var headNode = null;
  var expandedTables = {};
  var expandedProducts = {};
  var expandedOrders = {};
  var productFilters = {};
  var productMenu = null;
  var productMenuPromise = null;
  var productCache = {};
  var productLoading = {};
  var orderCache = {};
  var orderLoading = {};
  var latestItems = {};
  var latestSnapshots = {};
  var isBound = false;
  var boundHandler = null;

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

  function minutesAgo(ts) {
    if (!ts) return null;
    var dt = new Date(ts);
    if (Number.isNaN(dt.getTime())) return null;
    var diffMs = Date.now() - dt.getTime();
    var mins = Math.max(0, Math.floor(diffMs / 60000));
    return mins;
  }

  function getAvgBasket(revenue, orderCount) {
    if (!orderCount) return 0;
    return revenue / orderCount;
  }

  function normalizeList(stats) {
    return (stats || []).map(function (item) {
      var orderCount = Number(item.order_count || item.orders_count || 0);
      var revenue = Number(item.revenue || 0);
      var serpme = Number(item.serpme_count || 0);
      var tables = Array.isArray(item.tables) ? item.tables : [];
      var avgBasket = Number(item.avg_basket || getAvgBasket(revenue, orderCount));
      return {
        staff_id: item.staff_id,
        name: item.name || 'Bilinmiyor',
        order_count: orderCount,
        revenue: revenue,
        avg_basket: avgBasket,
        serpme_count: serpme,
        tables: tables,
        active_table_count: Number(item.active_table_count || 0),
        last_order_ts: item.last_order_ts || null
      };
    });
  }

  function normalizeMenuList(data) {
    var menu = data && data.menu ? data.menu : data;
    if (!menu || typeof menu !== 'object') return [];
    var items = [];
    Object.keys(menu).forEach(function (group) {
      var list = menu[group];
      if (!Array.isArray(list)) return;
      list.forEach(function (entry) {
        if (!entry) return;
        var name = entry.name || entry.title;
        if (!name) return;
        items.push({
          name: String(name),
          category: String(entry.category || group || '')
        });
      });
    });
    var seen = {};
    return items.filter(function (item) {
      var key = item.name.toLowerCase();
      if (seen[key]) return false;
      seen[key] = true;
      return true;
    });
  }

  function ensureMenuList() {
    if (productMenu) return Promise.resolve(productMenu);
    if (productMenuPromise) return productMenuPromise;
    if (!global.UI || !global.UI.Api || !global.UI.Api.getMenu) {
      productMenuPromise = Promise.resolve([]);
      return productMenuPromise;
    }
    productMenuPromise = global.UI.Api.getMenu().then(function (data) {
      productMenu = normalizeMenuList(data);
      return productMenu;
    }).catch(function () {
      productMenu = [];
      return productMenu;
    });
    return productMenuPromise;
  }

  function getProductKey(key, date) {
    if (date && typeof date === 'object') {
      var start = date.start || '';
      var end = date.end || '';
      return key + '|' + (start + '_' + end || 'today');
    }
    return key + '|' + (date || 'today');
  }

  function getDateKey() {
    if (!global.APP || !global.APP.state) return null;
    if (global.APP.state.staffStatsRange) return global.APP.state.staffStatsRange;
    return global.APP.state.staffStatsDate || null;
  }

  function ensureProductBreakdown(key, item) {
    var date = getDateKey();
    var cacheKey = getProductKey(key, date);
    if (productCache[cacheKey]) return Promise.resolve(productCache[cacheKey]);
    if (productLoading[cacheKey]) return productLoading[cacheKey];
    if (!global.UI || !global.UI.Api || !global.UI.Api.getStaffProductBreakdown) {
      productCache[cacheKey] = { product_counts: {} };
      return Promise.resolve(productCache[cacheKey]);
    }
    var staffId = item && item.staff_id != null ? item.staff_id : 0;
    productLoading[cacheKey] = global.UI.Api.getStaffProductBreakdown(staffId, date)
      .then(function (data) {
        productCache[cacheKey] = data || { product_counts: {} };
        return productCache[cacheKey];
      })
      .catch(function () {
        productCache[cacheKey] = { product_counts: {} };
        return productCache[cacheKey];
      });
    return productLoading[cacheKey];
  }

  function ensureStaffOrders(key, item) {
    var date = getDateKey();
    var cacheKey = getProductKey(key, date);
    if (orderCache[cacheKey]) return Promise.resolve(orderCache[cacheKey]);
    if (orderLoading[cacheKey]) return orderLoading[cacheKey];
    if (!global.UI || !global.UI.Api || !global.UI.Api.getStaffOrders) {
      orderCache[cacheKey] = { orders: [] };
      return Promise.resolve(orderCache[cacheKey]);
    }
    var staffId = item && item.staff_id != null ? item.staff_id : 0;
    orderLoading[cacheKey] = global.UI.Api.getStaffOrders(staffId, date)
      .then(function (data) {
        orderCache[cacheKey] = data || { orders: [] };
        return orderCache[cacheKey];
      })
      .catch(function () {
        orderCache[cacheKey] = { orders: [] };
        return orderCache[cacheKey];
      });
    return orderLoading[cacheKey];
  }

  function getFilterState(key) {
    if (!productFilters[key]) {
      productFilters[key] = { query: '', category: '', showAll: false };
    }
    return productFilters[key];
  }

  function formatDateLabel(dateValue) {
    if (!dateValue) return '';
    if (typeof dateValue === 'object') {
      var start = dateValue.start || '';
      var end = dateValue.end || '';
      if (start && end) return formatDateLabel(start) + ' - ' + formatDateLabel(end);
      return formatDateLabel(start || end);
    }
    if (dateValue.indexOf('-') !== -1) {
      var parts = dateValue.split('-');
      if (parts.length >= 3) {
        return parts[2] + '.' + parts[1] + '.' + parts[0];
      }
    }
    return dateValue;
  }

  function updateDateLabel(list) {
    var node = document.getElementById('staff-stats-date');
    if (!node) return;
    var date = getDateKey();
    if (!date) {
      node.textContent = '';
      return;
    }
    node.textContent = 'Tarih: ' + formatDateLabel(date);
  }

  function sortRows(rows) {
    var key = sortKey;
    var dir = sortDir === 'asc' ? 1 : -1;
    return rows.slice().sort(function (a, b) {
      var av = Number(a[key] || 0);
      var bv = Number(b[key] || 0);
      if (av !== bv) return (av - bv) * dir;
      return String(a.name || '').localeCompare(String(b.name || '')) * dir;
    });
  }

  function getTopRanks(rows) {
    var sorted = rows.slice().sort(function (a, b) {
      if (b.revenue !== a.revenue) return b.revenue - a.revenue;
      return (b.order_count || 0) - (a.order_count || 0);
    });
    var ranks = {};
    sorted.forEach(function (item, idx) {
      ranks[item.staff_id != null ? String(item.staff_id) : ('unknown:' + item.name)] = idx + 1;
    });
    return ranks;
  }

  function ensureTable(container) {
    if (tableHost) return;
    tableHost = document.createElement('div');
    tableHost.className = 'staff-stats-table';

    headNode = document.createElement('div');
    headNode.className = 'staff-stats-row staff-stats-head';
    headNode.innerHTML = ''
      + '<div class="staff-head-cell">'
      + '<button class="staff-sort" data-key="name">Garson</button>'
      + '</div>'
      + '<div class="staff-head-cell">'
      + '<button class="staff-sort" data-key="order_count">Siparis</button>'
      + '</div>'
      + '<div class="staff-head-cell">'
      + '<button class="staff-sort" data-key="revenue">Ciro</button>'
      + '<button class="staff-sort staff-sort-sub" data-key="avg_basket">Ort. Sepet</button>'
      + '</div>'
      + '<div class="staff-head-cell">'
      + '<button class="staff-sort" data-key="serpme_count">Serpme Kahvalt\u0131</button>'
      + '</div>';
    headNode.addEventListener('click', function (event) {
      var target = event.target;
      if (!target || !target.dataset) return;
      var key = target.dataset.key;
      if (!key) return;
      setSort(key);
    });

    tableHost.appendChild(headNode);
    container.appendChild(tableHost);
  }

  function setSort(key) {
    if (sortKey === key) {
      sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      sortKey = key;
      sortDir = 'desc';
    }
    updateSortState();
    if (global.APP && global.APP.state && Array.isArray(global.APP.state.staffStats)) {
      updateDiff(global.APP.state.staffStats);
    }
  }

  function updateSortState() {
    if (!headNode) return;
    var buttons = headNode.querySelectorAll('.staff-sort');
    buttons.forEach(function (btn) {
      var key = btn.dataset.key;
      if (key === sortKey) {
        btn.classList.add('active');
        btn.dataset.dir = sortDir;
      } else {
        btn.classList.remove('active');
        btn.dataset.dir = '';
      }
    });
  }

  function buildRow(key) {
    var row = document.createElement('div');
    row.className = 'staff-stats-row staff-row';
    row.dataset.key = key;
    row.innerHTML = ''
      + '<div class="staff-cell staff-name-cell">'
      + '  <span class="density-dot" aria-hidden="true"></span>'
      + '  <span class="staff-name-text"></span>'
      + '  <span class="staff-badge"></span>'
      + '</div>'
      + '<div class="staff-cell staff-orders-cell">'
      + '  <div class="metric-value staff-orders"></div>'
      + '  <div class="metric-bar"><span></span></div>'
      + '</div>'
      + '<div class="staff-cell staff-revenue-cell">'
      + '  <div class="metric-value staff-revenue"></div>'
      + '  <div class="metric-sub staff-avg"></div>'
      + '  <div class="metric-bar"><span></span></div>'
      + '</div>'
      + '<div class="staff-cell staff-serpme-cell">'
      + '  <div class="metric-value staff-serpme"></div>'
      + '</div>';
    var detail = document.createElement('div');
    detail.className = 'staff-stats-detail-row';
    rowNodes[key] = row;
    detailNodes[key] = detail;
    return { row: row, detail: detail };
  }

  function getDensityClass(count) {
    if (count >= 3) return 'density-high';
    if (count >= 1) return 'density-mid';
    return 'density-low';
  }

  function renderProductPanel(panel, key, menuList, counts) {
    var filter = getFilterState(key);
    var categories = [];
    menuList.forEach(function (item) {
      var cat = item.category || '';
      if (cat && categories.indexOf(cat) === -1) categories.push(cat);
    });
    categories.sort();

    var list = menuList.map(function (item) {
      return {
        name: item.name,
        category: item.category || '',
        count: Number((counts && counts[item.name]) || 0)
      };
    });

    if (filter.category) {
      list = list.filter(function (item) { return item.category === filter.category; });
    }
    if (filter.query) {
      var q = filter.query.toLowerCase();
      list = list.filter(function (item) { return item.name.toLowerCase().indexOf(q) !== -1; });
    }
    list.sort(function (a, b) {
      if (b.count !== a.count) return b.count - a.count;
      return a.name.localeCompare(b.name);
    });

    var display = filter.showAll ? list : list.slice(0, 5);

    panel.innerHTML = '';

    var toolbar = document.createElement('div');
    toolbar.className = 'staff-products-toolbar';

    var search = document.createElement('input');
    search.type = 'search';
    search.placeholder = 'Urun ara...';
    search.value = filter.query;
    search.className = 'staff-products-search';
    search.addEventListener('input', function () {
      filter.query = search.value;
      renderProductPanel(panel, key, menuList, counts);
    });
    toolbar.appendChild(search);

    if (categories.length > 1) {
      var select = document.createElement('select');
      select.className = 'staff-products-filter';
      var allOpt = document.createElement('option');
      allOpt.value = '';
      allOpt.textContent = 'Tum kategoriler';
      select.appendChild(allOpt);
      categories.forEach(function (cat) {
        var opt = document.createElement('option');
        opt.value = cat;
        opt.textContent = cat;
        select.appendChild(opt);
      });
      select.value = filter.category;
      select.addEventListener('change', function () {
        filter.category = select.value;
        renderProductPanel(panel, key, menuList, counts);
      });
      toolbar.appendChild(select);
    }

    panel.appendChild(toolbar);

    if (!list.length) {
      var empty = document.createElement('div');
      empty.className = 'staff-products-empty';
      empty.textContent = 'Urun bulunamadi.';
      panel.appendChild(empty);
      return;
    }

    var listWrap = document.createElement('div');
    listWrap.className = 'staff-products-list';
    display.forEach(function (item) {
      var row = document.createElement('div');
      row.className = 'staff-product-row';
      var name = document.createElement('span');
      name.className = 'staff-product-name';
      name.textContent = item.name;
      var count = document.createElement('span');
      count.className = 'staff-product-count';
      count.textContent = String(item.count || 0);
      row.appendChild(name);
      row.appendChild(count);
      listWrap.appendChild(row);
    });
    panel.appendChild(listWrap);

    if (list.length > 5) {
      var toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'staff-products-more';
      toggle.textContent = filter.showAll ? 'Kucult' : 'Tumunu goster';
      toggle.addEventListener('click', function () {
        filter.showAll = !filter.showAll;
        renderProductPanel(panel, key, menuList, counts);
      });
      panel.appendChild(toggle);
    }
  }

  function updateDetail(detailEl, item, snapshot) {
    if (!detailEl) return;
    detailEl.innerHTML = '';
    var line = document.createElement('div');
    line.className = 'staff-stats-detail';

    var tables = item.tables || [];
    var expanded = expandedTables[snapshot.key];
    var displayTables = expanded ? tables : tables.slice(0, 5);
    var more = tables.length - displayTables.length;

    if (tables.length === 1) {
      var single = document.createElement('span');
      single.textContent = 'Masa: ' + tables[0];
      line.appendChild(single);
    } else if (tables.length > 1) {
      var label = document.createElement('span');
      label.textContent = 'Masalar: ';
      line.appendChild(label);

      displayTables.forEach(function (t, idx) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'badge badge-chip';
        if (item.active_table_count > 0 && idx < item.active_table_count) {
          chip.className += ' badge-active';
        }
        chip.textContent = String(t);
        line.appendChild(chip);
      });

      if (more > 0) {
        var moreChip = document.createElement('button');
        moreChip.type = 'button';
        moreChip.className = 'badge badge-muted badge-toggle';
        moreChip.textContent = expanded ? 'Kucult' : ('+' + more + ' more');
        moreChip.addEventListener('click', function () {
          expandedTables[snapshot.key] = !expandedTables[snapshot.key];
          updateDetail(detailEl, item, snapshot);
        });
        line.appendChild(moreChip);
      }
    }

    var activeText = document.createElement('span');
    activeText.className = 'staff-meta';
    activeText.textContent = 'Aktif masa: ' + (item.active_table_count || 0);
    line.appendChild(activeText);

    var lastText = document.createElement('span');
    lastText.className = 'staff-meta staff-last-order';
    var minutes = minutesAgo(item.last_order_ts);
    if (minutes === null) {
      lastText.textContent = 'Son siparis: \u2014';
    } else {
      lastText.textContent = 'Son siparis: ' + minutes + ' dk \u00F6nce';
      if (minutes <= 5) lastText.classList.add('last-hot');
      if (minutes >= 60) lastText.classList.add('last-cold');
    }
    line.appendChild(lastText);

    var productButton = document.createElement('button');
    productButton.type = 'button';
    productButton.className = 'staff-products-toggle';
    if (expandedProducts[snapshot.key]) productButton.className += ' is-open';
    var totalTypes = productMenu ? productMenu.length : (item.product_total_types || null);
    productButton.textContent = totalTypes ? ('Urunler (' + totalTypes + ')') : 'Urunler';
    productButton.addEventListener('click', function () {
      expandedProducts[snapshot.key] = !expandedProducts[snapshot.key];
      if (expandedProducts[snapshot.key]) {
        ensureMenuList().then(function () {
          return ensureProductBreakdown(snapshot.key, item);
        }).then(function () {
          updateDetail(detailEl, item, snapshot);
        });
      } else {
        updateDetail(detailEl, item, snapshot);
      }
    });
    line.appendChild(productButton);

    var ordersButton = document.createElement('button');
    ordersButton.type = 'button';
    ordersButton.className = 'staff-products-toggle';
    if (expandedOrders[snapshot.key]) ordersButton.className += ' is-open';
    ordersButton.textContent = 'Siparisler (' + (item.order_count || 0) + ')';
    ordersButton.addEventListener('click', function () {
      expandedOrders[snapshot.key] = !expandedOrders[snapshot.key];
      if (expandedOrders[snapshot.key]) {
        ensureStaffOrders(snapshot.key, item).then(function () {
          updateDetail(detailEl, item, snapshot);
        });
      } else {
        updateDetail(detailEl, item, snapshot);
      }
    });
    line.appendChild(ordersButton);

    detailEl.appendChild(line);

    if (expandedProducts[snapshot.key]) {
      var panel = document.createElement('div');
      panel.className = 'staff-products-panel is-open';
      detailEl.appendChild(panel);
      Promise.all([ensureMenuList(), ensureProductBreakdown(snapshot.key, item)]).then(function (results) {
        var menuList = results[0] || [];
        var data = results[1] || {};
        var counts = data.product_counts || {};
        renderProductPanel(panel, snapshot.key, menuList, counts);
      }).catch(function () {
        panel.textContent = 'Urunler yuklenemedi.';
      });
    }

    if (expandedOrders[snapshot.key]) {
      var ordersPanel = document.createElement('div');
      ordersPanel.className = 'staff-orders-panel is-open';
      detailEl.appendChild(ordersPanel);
      ensureStaffOrders(snapshot.key, item).then(function (data) {
        var list = (data && data.orders) ? data.orders : [];
        if (!list.length) {
          var empty = document.createElement('div');
          empty.className = 'staff-orders-empty';
          empty.textContent = 'Siparis yok.';
          ordersPanel.appendChild(empty);
          return;
        }
        var wrap = document.createElement('div');
        wrap.className = 'staff-orders-list';
        list.forEach(function (order) {
          var row = document.createElement('div');
          row.className = 'staff-order-row';
          var head = document.createElement('div');
          head.className = 'staff-order-head';
          head.textContent = 'Masa ' + (order.masa || '-') + ' · ' + (order.zaman || '--:--') + ' · ' + formatMoney(order.toplam || 0);
          var items = document.createElement('div');
          items.className = 'staff-order-items';
          var summary = (order.items || []).map(function (it) {
            var name = it.name || '';
            var adet = it.adet || 0;
            return name + ' x' + adet;
          }).join(', ');
          items.textContent = summary || 'Urun yok';
          row.appendChild(head);
          row.appendChild(items);
          wrap.appendChild(row);
        });
        ordersPanel.appendChild(wrap);
      }).catch(function () {
        ordersPanel.textContent = 'Siparisler yuklenemedi.';
      });
    }
  }

  function updateRowContent(row, detail, item, snapshot) {
    var last = rowCache[snapshot.key] || {};
    var densityDot = row.querySelector('.density-dot');
    var nameEl = row.querySelector('.staff-name-text');
    var badgeEl = row.querySelector('.staff-badge');
    var ordersEl = row.querySelector('.staff-orders');
    var revenueEl = row.querySelector('.staff-revenue');
    var avgEl = row.querySelector('.staff-avg');
    var serpmeEl = row.querySelector('.staff-serpme');
    var orderBar = row.querySelector('.staff-orders-cell .metric-bar span');
    var revenueBar = row.querySelector('.staff-revenue-cell .metric-bar span');

    if (snapshot.name !== last.name && nameEl) nameEl.textContent = snapshot.name;
    if (snapshot.order_count !== last.order_count && ordersEl) ordersEl.textContent = String(snapshot.order_count);
    if (snapshot.revenue !== last.revenue && revenueEl) revenueEl.textContent = formatMoney(snapshot.revenue);
    if (snapshot.avg_basket !== last.avg_basket && avgEl) avgEl.textContent = 'Ort: ' + formatMoney(snapshot.avg_basket);
    if (snapshot.serpme_count !== last.serpme_count && serpmeEl) serpmeEl.textContent = String(snapshot.serpme_count);

    if (densityDot) {
      densityDot.className = 'density-dot ' + getDensityClass(snapshot.active_table_count);
      densityDot.setAttribute('title', 'Yogun: ' + snapshot.active_table_count + ' aktif masa');
      densityDot.setAttribute('aria-label', 'Yogun: ' + snapshot.active_table_count + ' aktif masa');
    }

    if (badgeEl) {
      badgeEl.textContent = snapshot.rankBadge || '';
      badgeEl.className = 'staff-badge' + (snapshot.rankBadge ? ' badge-top' : '');
    }

    if (orderBar) orderBar.style.width = snapshot.order_percent + '%';
    if (revenueBar) revenueBar.style.width = snapshot.revenue_percent + '%';

    if (snapshot.isTop) {
      row.classList.add('row-highlight');
    } else {
      row.classList.remove('row-highlight');
    }

    if (snapshot.tables !== last.tables || snapshot.active_table_count !== last.active_table_count || snapshot.last_order_ts !== last.last_order_ts) {
      updateDetail(detail, item, snapshot);
    }

    rowCache[snapshot.key] = snapshot;
  }

  function updateDiff(stats) {
    var container = document.getElementById(containerId);
    if (!container) return;

    var list = normalizeList(stats);
    updateDateLabel(list);

    if (!list.length) {
      container.textContent = 'Bugun veri yok.';
      return;
    }

    if (tableHost && !container.contains(tableHost)) {
      tableHost = null;
      headNode = null;
    }
    if (container.childNodes.length === 1 && container.firstChild.nodeType === 3) {
      container.textContent = '';
    }
    ensureTable(container);
    updateSortState();

    var topRanks = getTopRanks(list);
    var maxRevenue = Math.max.apply(null, list.map(function (x) { return x.revenue || 0; }).concat([0]));
    var maxOrders = Math.max.apply(null, list.map(function (x) { return x.order_count || 0; }).concat([0]));

    var before = {};
    Object.keys(rowNodes).forEach(function (key) {
      if (rowNodes[key] && rowNodes[key].parentNode) {
        before[key] = rowNodes[key].getBoundingClientRect();
      }
    });

    var ordered = sortRows(list);
    var seen = {};
    var fragment = document.createDocumentFragment();

    ordered.forEach(function (item, idx) {
      var key = item.staff_id != null ? String(item.staff_id) : ('unknown:' + item.name);
      seen[key] = true;
      var nodes = rowNodes[key] ? { row: rowNodes[key], detail: detailNodes[key] } : buildRow(key);
      var rank = topRanks[key] || (idx + 1);
      var rankBadge = '';
      if (rank === 1) rankBadge = '\uD83C\uDFC6';
      else if (rank === 2) rankBadge = '\uD83E\uDD47';
      else if (rank === 3) rankBadge = '\uD83E\uDD48';

      var snapshot = {
        key: key,
        name: item.name,
        order_count: item.order_count,
        revenue: item.revenue,
        avg_basket: item.avg_basket,
        serpme_count: item.serpme_count,
        tables: (item.tables || []).join('|'),
        active_table_count: item.active_table_count,
        last_order_ts: item.last_order_ts || '',
        revenue_percent: maxRevenue ? Math.round((item.revenue / maxRevenue) * 100) : 0,
        order_percent: maxOrders ? Math.round((item.order_count / maxOrders) * 100) : 0,
        isTop: rank === 1,
        rankBadge: rankBadge
      };

      latestItems[key] = item;
      latestSnapshots[key] = snapshot;
      updateRowContent(nodes.row, nodes.detail, item, snapshot);
      fragment.appendChild(nodes.row);
      fragment.appendChild(nodes.detail);
    });

    Object.keys(rowNodes).forEach(function (key) {
      if (seen[key]) return;
      if (rowNodes[key] && rowNodes[key].parentNode) {
        rowNodes[key].parentNode.removeChild(rowNodes[key]);
      }
      if (detailNodes[key] && detailNodes[key].parentNode) {
        detailNodes[key].parentNode.removeChild(detailNodes[key]);
      }
      delete rowNodes[key];
      delete detailNodes[key];
      delete rowCache[key];
    });

    while (tableHost.childNodes.length > 1) {
      tableHost.removeChild(tableHost.lastChild);
    }
    tableHost.appendChild(fragment);

    requestAnimationFrame(function () {
      Object.keys(rowNodes).forEach(function (key) {
        var row = rowNodes[key];
        var first = before[key];
        if (!row || !first) return;
        var last = row.getBoundingClientRect();
        var dx = first.left - last.left;
        var dy = first.top - last.top;
        if (dx || dy) {
          row.animate([
            { transform: 'translate(' + dx + 'px,' + dy + 'px)' },
            { transform: 'translate(0,0)' }
          ], { duration: 250, easing: 'ease-out' });
        }
      });

      var topRow = ordered[0] && rowNodes[(ordered[0].staff_id != null ? String(ordered[0].staff_id) : ('unknown:' + ordered[0].name))];
      if (topRow) {
        topRow.classList.add('row-pulse');
        setTimeout(function () {
          topRow.classList.remove('row-pulse');
        }, 600);
      }
    });

    if (!productMenu && !productMenuPromise) {
      ensureMenuList().then(function () {
        Object.keys(detailNodes).forEach(function (key) {
          var item = latestItems[key];
          var snapshot = latestSnapshots[key];
          if (item && snapshot) {
            updateDetail(detailNodes[key], item, snapshot);
          }
        });
      });
    }
  }

  function render(targetId, stats) {
    containerId = targetId;
    rowCache = {};
    rowNodes = {};
    detailNodes = {};
    updateDiff(stats);
  }

  function bind(targetId) {
    containerId = targetId;
    if (!global.APP || !global.APP.on) return;
    if (isBound && boundHandler) {
      if (global.APP.off) global.APP.off('staffStats:updated', boundHandler);
    }
    boundHandler = function (payload) {
      var stats = payload && payload.stats ? payload.stats : payload;
      updateDiff(stats || []);
    };
    global.APP.on('staffStats:updated', boundHandler);
    isBound = true;
  }

  global.UI = global.UI || {};
  global.UI.StaffStats = {
    init: bind,
    render: render,
    bind: bind,
    setSort: setSort
  };
})(window);
