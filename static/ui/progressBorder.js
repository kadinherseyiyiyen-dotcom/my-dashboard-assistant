/* global window */
(function (global) {
  'use strict';

  /*
    Public API:
      ProgressBorder.init(root)
  */

  var instance = null;

  function init(root) {
    if (!global.TableProgressBorder) return null;
    instance = global.TableProgressBorder.initTableProgressBorders(root || document);
    return instance;
  }

  global.UI = global.UI || {};
  global.UI.ProgressBorder = {
    init: init
  };
  global.ProgressBorder = global.UI.ProgressBorder;

  if (global.APP && global.APP.on) {
    global.APP.on('tables:updated', function () {
      if (instance && instance.update) {
        instance.update();
      }
    });
  }
})(window);
