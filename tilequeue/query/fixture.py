from collections import namedtuple
from shapely.geometry import box
from tilequeue.process import meta_for_properties


LayerInfo = namedtuple('LayerInfo', 'min_zoom_fn props_fn')


class DataFetcher(object):

    def __init__(self, layers, rows, label_placement_layers):
        """
        Expect layers to be a dict of layer name to LayerInfo. Expect rows to
        be a list of (fid, shape, properties). Label placement layers should
        be a set of layer names for which to generate label placement points.
        """

        self.layers = layers
        self.rows = rows
        self.label_placement_layers = label_placement_layers

    def __call__(self, zoom, unpadded_bounds):
        read_rows = []
        bbox = box(*unpadded_bounds)

        for (fid, shape, props) in self.rows:
            # reject any feature which doesn't intersect the given bounds
            if bbox.disjoint(shape):
                continue

            # place for assembing the read row as if from postgres
            read_row = {}

            # whether to generate a label placement centroid
            generate_label_placement = False

            for layer_name, info in self.layers.items():
                meta = meta_for_properties(props)
                min_zoom = info.min_zoom_fn(shape, props, fid, meta)

                # reject anything which isn't in the current zoom range
                if min_zoom is None or zoom < min_zoom:
                    continue

                # if the feature exists in any label placement layer, then we
                # should consider generating a centroid (if it's a polygon)
                if layer_name in self.label_placement_layers:
                    generate_label_placement = True

                layer_props = props.copy()
                layer_props['min_zoom'] = min_zoom

                # urgh, hack!
                if layer_name == 'water' and shape.geom_type == 'Point':
                    layer_props['label_placement'] = True

                if layer_props:
                    props_name = '__%s_properties__' % layer_name
                    read_row[props_name] = layer_props

            # if at least one min_zoom / properties match
            if read_row:
                read_row['__id__'] = fid
                read_row['__geometry__'] = bytes(shape.wkb)
                if shape.geom_type in ('Polygon', 'MultiPolygon') and \
                   generate_label_placement:
                    read_row['__label__'] = bytes(
                        shape.representative_point().wkb)
                read_rows.append(read_row)

        return read_rows


def make_fixture_data_fetcher(layers, rows, label_placement_layers=set()):
    return DataFetcher(layers, rows, label_placement_layers)
