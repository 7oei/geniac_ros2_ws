"""Decode PointCloud2 without rosbag readers or ROS-specific conversion loops."""
import numpy as np

TYPES = {1: 'i1', 2: 'u1', 3: 'i2', 4: 'u2', 5: 'i4', 6: 'u4', 7: 'f4', 8: 'f8'}


def decode_cloud(msg, max_points=200000):
    height, width = int(msg.height), int(msg.width)
    if height < 0 or width < 0 or height * width > max_points:
        raise ValueError('Point count is invalid or exceeds max_points')
    if height * width == 0:
        return np.empty((0, 4), np.float32)
    step, row = int(msg.point_step), int(msg.row_step)
    if step <= 0 or row < width * step or len(msg.data) < row * height:
        raise ValueError('PointCloud2 buffer or strides are inconsistent')
    fields = {f.name: f for f in msg.fields}
    if len(fields) != len(msg.fields):
        raise ValueError('Duplicate field names')
    names = ['x', 'y', 'z', 'intensity']
    formats, offsets = [], []
    for name in names:
        f = fields.get(name)
        if f is None or f.count != 1 or f.datatype not in TYPES:
            raise ValueError('Scalar x/y/z/intensity fields are required')
        dtype = np.dtype(('>' if msg.is_bigendian else '<') + TYPES[f.datatype])
        if f.offset < 0 or f.offset + dtype.itemsize > step:
            raise ValueError('Field lies outside point_step')
        formats.append(dtype); offsets.append(f.offset)
    dtype = np.dtype(dict(names=names, formats=formats, offsets=offsets, itemsize=step))
    a = np.ndarray((height, width), dtype=dtype, buffer=msg.data, strides=(row, step))
    return np.column_stack([a[n].reshape(-1) for n in names]).astype(np.float32)
