from shapely import geometry
from shapely.wkb import dumps
from tilequeue.format import json_format
from tilequeue.format import mvt_format
from tilequeue.format import topojson_format
from tilequeue.format import vtm_format
from TileStache.Goodies.VecTiles.ops import transform
from TileStache.Goodies.VecTiles.server import tolerances
import math


half_circumference_meters = 20037508.342789244


def mercator_point_to_wgs84(point):
    x, y = point

    x /= half_circumference_meters
    y /= half_circumference_meters

    y = (2 * math.atan(math.exp(y * math.pi)) - (math.pi / 2)) / math.pi

    x *= 180
    y *= 180

    return x, y


def rescale_point(bounds, scale):
    minx, miny, maxx, maxy = bounds

    def fn(point):
        x, y = point

        xfac = scale / (maxx - minx)
        yfac = scale / (maxy - miny)
        x = x * xfac - minx * xfac
        y = y * yfac - miny * yfac

        return x, y

    return fn


def apply_to_all_coords(fn):
    return lambda shape: transform(shape, fn)


def transform_feature_layers_shape(feature_layers, format, scale,
                                   unpadded_bounds, padded_bounds, coord):
    if format in (json_format, topojson_format):
        transform_fn = apply_to_all_coords(mercator_point_to_wgs84)
    elif format in (mvt_format, vtm_format):
        transform_fn = apply_to_all_coords(
            rescale_point(unpadded_bounds, scale))
    else:
        # in case we add a new format, default to no transformation
        transform_fn = lambda shape: shape

    is_vtm_format = format == vtm_format
    shape_bounds = geometry.box(
        *(padded_bounds if is_vtm_format else unpadded_bounds))

    transformed_feature_layers = []
    for feature_layer in feature_layers:
        features = feature_layer['features']
        transformed_features = []

        layer_datum = feature_layer['layer_datum']
        is_clipped = layer_datum['is_clipped']

        for shape, props, feature_id in features:
            # perform any simplification as necessary
            tolerance = tolerances[coord.zoom]
            simplify_until = layer_datum['simplify_until']
            suppress_simplification = layer_datum['suppress_simplification']
            should_simplify = coord.zoom not in suppress_simplification and \
                coord.zoom < simplify_until

            simplify_before_intersect = feature_layer['name'] in ['water', 'earth']

            if should_simplify and simplify_before_intersect:
                min_x, min_y, max_x, max_y = shape_bounds
                gutter_bbox_size = (max_x - min_x) * 0.1
                gutter_bbox = geometry.box(
                    min_x - gutter_bbox_size,
                    min_y - gutter_bbox_size,
                    max_x + gutter_bbox_size,
                    max_y + gutter_bbox_size)
                shape = shape.intersection(gutter_bbox).simplify(
                    tolerance, preserve_topology=True)
                shape = shape.buffer(0)

            if is_vtm_format:
                if is_clipped:
                    shape = shape.intersection(shape_bounds)
            else:
                # for non vtm formats, we need to explicitly check if
                # the geometry intersects with the unpadded bounds
                if not shape_bounds.intersects(shape):
                    continue
                # now we know that we should include the geometry, but
                # if the geometry should be clipped, we'll clip to the
                # unpadded bounds
                if is_clipped:
                    shape = shape.intersection(shape_bounds)

            if should_simplify and not simplify_before_intersect:
                shape = shape.simplify(tolerance, preserve_topology=True)

            # perform the format specific geometry transformations
            shape = transform_fn(shape)

            # the formatters all expect wkb
            wkb = dumps(shape)

            transformed_features.append((wkb, props, feature_id))

        transformed_feature_layer = dict(
            name=feature_layer['name'],
            features=transformed_features,
            layer_datum=layer_datum,
        )
        transformed_feature_layers.append(transformed_feature_layer)

    return transformed_feature_layers
