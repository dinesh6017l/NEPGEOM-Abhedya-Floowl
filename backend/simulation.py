import numpy as np
import rasterio
import os
import json
import sys
import math
import warnings
from datetime import datetime
from urllib import request as urlrequest
from urllib import parse as urlparse
from rasterio.transform import from_bounds
from rasterio.io import MemoryFile


def download_dem_arcgis(bounds, token=None, width=1024, height=1024):
    url = "https://elevation3d.arcgis.com/arcgis/rest/services/WorldElevation3D/Terrain3D/ImageServer/exportImage"
    params = {
        "bbox": f"{bounds['minLng']},{bounds['minLat']},{bounds['maxLng']},{bounds['maxLat']}",
        "bboxSR": "4326",
        "size": f"{width},{height}",
        "imageSR": "4326",
        "format": "tiff",
        "pixelType": "F32",
        "f": "image"
    }
    if token and token != 'YOUR_ARCGIS_API_KEY_HERE':
        params["token"] = token

    req_url = f"{url}?{urlparse.urlencode(params)}"
    req = urlrequest.Request(req_url, headers={'User-Agent': 'Mozilla/5.0'})

    with urlrequest.urlopen(req, timeout=30) as resp:
        tiff_data = resp.read()

    if tiff_data.startswith(b'{'):
        try:
            err_json = json.loads(tiff_data)
            raise ValueError(f"ArcGIS Error: {err_json.get('error', err_json)}")
        except json.JSONDecodeError:
            pass

    with MemoryFile(tiff_data) as mem:
        with mem.open() as src:
            dem = src.read(1)
            transform = src.transform

    dem_bounds = {
        'minLng': bounds['minLng'],
        'minLat': bounds['minLat'],
        'maxLng': bounds['maxLng'],
        'maxLat': bounds['maxLat']
    }

    return dem, transform, dem_bounds


def compute_flow_accumulation_mfd(dem, u_norm, v_norm):
    ny, nx = dem.shape
    abs_sum = np.abs(u_norm) + np.abs(v_norm)
    safe_sum = np.where(abs_sum == 0, 1.0, abs_sum)

    frac_x = np.abs(u_norm) / safe_sum
    frac_y = np.abs(v_norm) / safe_sum

    acc = np.ones((ny, nx), dtype=np.float64)
    order = np.argsort(dem.ravel())[::-1]

    for linear_idx in order:
        r = linear_idx // nx
        c = linear_idx % nx
        flow_out = acc[r, c]

        if u_norm[r, c] > 0 and c + 1 < nx:
            acc[r, c + 1] += flow_out * frac_x[r, c]
        elif u_norm[r, c] < 0 and c - 1 >= 0:
            acc[r, c - 1] += flow_out * frac_x[r, c]

        if v_norm[r, c] > 0 and r + 1 < ny:
            acc[r + 1, c] += flow_out * frac_y[r, c]
        elif v_norm[r, c] < 0 and r - 1 >= 0:
            acc[r - 1, c] += flow_out * frac_y[r, c]

    return acc


def compute_velocity_field(dem, nodata=None):
    if nodata is not None:
        dem = np.ma.MaskedArray(dem, mask=(dem == nodata))
        dem_filled = dem.filled(np.nan)
        mask = dem.mask.copy()
    else:
        dem_filled = dem.astype(np.float64)
        mask = np.isnan(dem_filled)

    dem_filled = np.nan_to_num(dem_filled, nan=0.0)

    dzdx = np.gradient(dem_filled, axis=1)
    dzdy = np.gradient(dem_filled, axis=0)

    u = -dzdx
    v = -dzdy

    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        mag = np.sqrt(u ** 2 + v ** 2)
        u_norm = np.where(mag > 1e-12, u / mag, 0.0)
        v_norm = np.where(mag > 1e-12, v / mag, 0.0)
    mag_max = np.max(mag)

    if nodata is not None:
        u_norm = np.ma.MaskedArray(u_norm, mask=mask)
        v_norm = np.ma.MaskedArray(v_norm, mask=mask)

    return u_norm, v_norm, mag, mag_max


def compute_river_proximity_and_hand(river_mask, dem, max_dist_pixels=120):
    ny, nx = river_mask.shape
    INF = 1e10

    dist = np.full((ny, nx), INF, dtype=np.float64)
    river_elev = np.zeros((ny, nx), dtype=np.float64)

    dist[river_mask] = 0.0
    river_elev[river_mask] = dem[river_mask]

    updated = river_mask.copy()

    for iteration in range(max_dist_pixels + 1):
        if not updated.any():
            break

        pad_updated = np.pad(updated, 1, mode='constant', constant_values=False)
        pad_dist = np.pad(dist, 1, mode='constant', constant_values=INF)
        pad_relev = np.pad(river_elev, 1, mode='edge')

        next_updated = np.zeros_like(updated, dtype=bool)

        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue

                nbr_upd = pad_updated[1+dr:1+dr+ny, 1+dc:1+dc+nx]
                nbr_dist = pad_dist[1+dr:1+dr+ny, 1+dc:1+dc+nx]
                nbr_relev = pad_relev[1+dr:1+dr+ny, 1+dc:1+dc+nx]

                step = 1.0 if dr == 0 or dc == 0 else np.sqrt(2)
                candidate_dist = nbr_dist + step

                closer = nbr_upd & (candidate_dist < dist)
                dist = np.where(closer, candidate_dist, dist)
                river_elev = np.where(closer, nbr_relev, river_elev)
                next_updated = next_updated | closer

        updated = next_updated

    hand = dem - river_elev
    return dist, hand


def run(bounds, token, output_dir=None, zoom=None, expand_factor=2.0):
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'cache')
    os.makedirs(output_dir, exist_ok=True)

    center_lng = (bounds['minLng'] + bounds['maxLng']) / 2
    center_lat = (bounds['minLat'] + bounds['maxLat']) / 2
    half_lng = (bounds['maxLng'] - bounds['minLng']) / 2
    half_lat = (bounds['maxLat'] - bounds['minLat']) / 2

    expanded_bounds = {
        'minLng': center_lng - expand_factor * half_lng,
        'maxLng': center_lng + expand_factor * half_lng,
        'minLat': center_lat - expand_factor * half_lat,
        'maxLat': center_lat + expand_factor * half_lat,
    }

    dem, transform, dem_bounds = download_dem_arcgis(expanded_bounds)

    u_norm, v_norm, mag, _ = compute_velocity_field(dem)
    flow_acc = compute_flow_accumulation_mfd(dem, u_norm, v_norm)

    river_threshold = np.percentile(flow_acc, 95)
    river_mask = flow_acc >= river_threshold

    if not river_mask.any():
        river_mask = np.zeros_like(flow_acc, dtype=bool)
        river_mask[flow_acc == flow_acc.max()] = True

    max_river_pixels = 120
    river_dist, hand = compute_river_proximity_and_hand(
        river_mask, dem, max_dist_pixels=max_river_pixels
    )

    inv_transform = ~transform
    col0, row0 = inv_transform * (bounds['minLng'], bounds['maxLat'])
    col1, row1 = inv_transform * (bounds['maxLng'], bounds['minLat'])
    col0 = max(0, int(math.floor(col0)))
    col1 = min(dem.shape[1], int(math.ceil(col1)))
    row0 = max(0, int(math.floor(row0)))
    row1 = min(dem.shape[0], int(math.ceil(row1)))

    if col1 > col0 and row1 > row0:
        dem_crop = dem[row0:row1, col0:col1].astype(np.float64)
        mag_crop = mag[row0:row1, col0:col1].astype(np.float64)
        river_dist_crop = river_dist[row0:row1, col0:col1]
        hand_crop = hand[row0:row1, col0:col1]

        near_river = river_dist_crop <= max_river_pixels
        flood_score = np.zeros_like(dem_crop)

        if near_river.any():
            max_hand = min(np.percentile(hand_crop[near_river], 90), 50.0)
            if max_hand < 0.5:
                max_hand = 0.5

            hand_score = np.clip(1.0 - hand_crop / max_hand, 0, 1)

            max_dist = float(max_river_pixels)
            dist_score = np.clip(1.0 - river_dist_crop / max_dist, 0, 1)

            slope_max = max(np.percentile(mag_crop[near_river], 90), 1e-4)
            inv_slope = np.clip(1.0 - mag_crop / slope_max, 0, 1)

            flood_score = np.where(
                near_river,
                0.50 * hand_score + 0.30 * dist_score + 0.20 * inv_slope,
                -1.0
            )

        MARGIN = 2
        flood_score[:MARGIN, :] = -1
        flood_score[-MARGIN:, :] = -1
        flood_score[:, :MARGIN] = -1
        flood_score[:, -MARGIN:] = -1

        valid = flood_score >= 0
        fsv = flood_score[valid]
        if fsv.size > 0:
            threshold = np.percentile(fsv, 75)
        else:
            threshold = 0.5

        display = np.where(flood_score >= threshold, flood_score, -1)
        dmax = display.max()
        if dmax > threshold:
            normed = np.clip((display - threshold) / (dmax - threshold + 1e-10), 0, 1)
        else:
            normed = np.zeros_like(display)

        R = np.where(normed > 0, (255 - 116 * normed).astype(np.uint8), 0)
        G = np.where(normed > 0, (150 * (1 - normed)).astype(np.uint8), 0)
        B = np.where(normed > 0, (150 * (1 - normed)).astype(np.uint8), 0)
        alpha = np.where(normed > 0, (100 + 155 * normed).astype(np.uint8), 0)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        png_filename = f'susceptibility_{timestamp}.png'
        png_path = os.path.join(output_dir, png_filename)

        png_profile = {
            'driver': 'PNG', 'height': flood_score.shape[0],
            'width': flood_score.shape[1], 'count': 4, 'dtype': 'uint8'
        }
        with rasterio.open(png_path, 'w', **png_profile) as dst:
            dst.write(R, 1)
            dst.write(G, 2)
            dst.write(B, 3)
            dst.write(alpha, 4)

        tl_lng, tl_lat = transform * (col0, row0)
        br_lng, br_lat = transform * (col1, row1)
        png_bounds = {
            'minLng': tl_lng, 'maxLat': tl_lat,
            'maxLng': br_lng, 'minLat': br_lat
        }
    else:
        png_filename = None
        png_bounds = None
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    meta = {
        'depth_png': f'/cache/{png_filename}' if png_filename else None,
        'png_bounds': png_bounds,
        'bounds': bounds,
        'expanded_bounds': expanded_bounds,
        'shape': list(dem.shape) if png_filename else None,
        'method': 'riverine_hand_susceptibility',
        'river_threshold_percentile': 95,
        'max_river_distance_pixels': max_river_pixels,
        'weights': {'hand': 0.50, 'river_distance': 0.30, 'slope': 0.20},
        'expand_factor': expand_factor,
        'velocity_range': {
            'u_min': float(np.min(u_norm)),
            'u_max': float(np.max(u_norm)),
            'v_min': float(np.min(v_norm)),
            'v_max': float(np.max(v_norm)),
            'mag_max': float(np.max(mag))
        }
    }
    meta_path = os.path.join(output_dir, f'susceptibility_{timestamp}.json')
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)

    return meta


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python simulation.py <minLng> <minLat> <maxLng> <maxLat> [zoom]')
        sys.exit(1)

    bounds = {
        'minLng': float(sys.argv[1]),
        'minLat': float(sys.argv[2]),
        'maxLng': float(sys.argv[3]),
        'maxLat': float(sys.argv[4])
    }

    result = run(bounds, None, zoom=int(sys.argv[5]) if len(sys.argv) > 5 else None)
    print(json.dumps(result, indent=2))
