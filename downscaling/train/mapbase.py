"""지도 배경: Natural Earth 서버가 막혀 있어 basemap(GSHHS 고해상도) 해안선·국경을 추출해 그린다."""
import numpy as np
from functools import lru_cache


@lru_cache(None)
def segments(box=(122.5, 32.5, 132.5, 44.0), res="h"):
    from mpl_toolkits.basemap import Basemap
    m = Basemap(llcrnrlon=box[0], llcrnrlat=box[1], urcrnrlon=box[2], urcrnrlat=box[3],
                resolution=res, projection="cyl")
    coast = [np.array(s) for s in m.coastsegs]
    m.drawcountries(linewidth=0)
    border = [np.array(s) for s in m.cntrysegs]
    return coast, border


def draw(ax, box=(122.5, 32.5, 132.5, 44.0), color="#333", lw=0.5):
    coast, border = segments(box)
    for s in coast:
        ax.plot(s[:, 0], s[:, 1], color=color, lw=lw)
    for s in border:
        ax.plot(s[:, 0], s[:, 1], color=color, lw=lw * 0.8, ls="--")
    ax.set_xlim(box[0], box[2]); ax.set_ylim(box[1], box[3])
    ax.set_aspect(1 / np.cos(np.deg2rad(38)))
