import numpy as np
import pytest
from sensor_msgs.msg import PointCloud2,PointField
from std_msgs.msg import Header
from geniac_visualizer.cloud_preview import decimate


def test_preview_preserves_points_fields_stamp_and_row_padding():
    a=np.arange(12,dtype='<f4').reshape(4,3)
    data=a[:2].tobytes()+b'padding!'+a[2:].tobytes()+b'padding!'
    msg=PointCloud2(header=Header(frame_id='livox_frame'),height=2,width=2,
        fields=[PointField(name=n,offset=i*4,datatype=7,count=1) for i,n in enumerate('xyz')],
        point_step=12,row_step=32,data=data)
    msg.header.stamp.sec=123
    out=decimate(msg,2)
    assert out.width==2 and out.height==1 and out.row_step==24
    assert out.header==msg.header and out.fields==msg.fields
    np.testing.assert_array_equal(np.frombuffer(bytes(out.data),dtype='<f4').reshape(-1,3),a[::2])
    assert bytes(msg.data)==data


def test_preview_bounds_large_input():
    msg=PointCloud2(height=1,width=45001,point_step=4,row_step=180004,data=bytes(180004))
    out=decimate(msg)
    assert out.width<=5000 and len(out.data)<=20000
    msg.row_step=1
    with pytest.raises(ValueError):decimate(msg)
