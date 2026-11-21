from geniac_visualizer.camera_selector import CameraSelector

def test_hysteresis_and_stable_intervals():
    s=CameraSelector()
    for t in range(3):s.update(20,t)
    assert s.desired=='usb'
    s.update(20,3);assert s.desired=='ir'
    for t in range(4,10):s.update(50,t)
    assert s.desired=='ir'
    for t in range(10,15):s.update(75,t)
    assert s.desired=='ir'
    s.update(75,15);assert s.desired=='usb'

def test_gap_and_invalid_values_do_not_trigger_switch():
    s=CameraSelector();s.update(10,0);s.update(10,10)
    assert s.desired=='usb'
    s.update(float('nan'),11);s.update(300,12)
    assert s.luminance==10 and s.desired=='usb'

def test_missing_selected_camera_falls_back():
    s=CameraSelector();s.desired='ir'
    assert s.choose(10,{'usb':9,'ir':1})=='usb'
    assert s.choose(10,{'usb':1,'ir':9})=='ir'
    assert s.choose(10,{'usb':1,'ir':1}) is None
