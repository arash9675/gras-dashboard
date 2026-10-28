"""UI building blocks shared by the pages.

  theme    - Material 3 styling, colours and small drawing helpers (card, kpi, ...)
  state    - chosen polygon set and datasets, cached data, filters
  mapview  - the MapLibre map component (components/maplibre/index.html)

Pages just `import ui` and call ui.card(...), ui.polygons(), ui.filter_bar(...);
this file re-exports theme and state so they don't need to know which is which.
"""
from ui.state import *  # noqa: F401,F403
from ui.theme import *  # noqa: F401,F403
