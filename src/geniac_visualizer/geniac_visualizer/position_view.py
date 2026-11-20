"""Live draggable deer locations; outside the dashed sensor area means undetected."""
import math
from PyQt5 import QtCore,QtGui,QtWidgets

NAMES={'no_escape':'動かなかった','retreated_nearby':'移動・視界内','escaped':'完全退避','observing':'観測中／退避確認中','unknown':'判定不明'}
COLORS={'no_escape':'#ef4444','retreated_nearby':'#f59e0b','observing':'#60a5fa','unknown':'#94a3b8','escaped':'#22c55e'}

class PositionView(QtWidgets.QWidget):
    RANGE_M=40.
    HALF_FOV_DEG=60.
    def __init__(self,model,interactive=False):
        super().__init__();self.model=model;self.interactive=interactive;self.dragging=None
        self.positions={1:[15.,0.],2:[20.,6.],3:[25.,-6.]};self.count=1;self.enabled=True
        self.setMinimumSize(340,280);self.setMouseTracking(True)
    def geometry_values(self):
        return min((self.width()-44)/88,(self.height()-72)/50),QtCore.QPointF(self.width()/2,self.height()-30)
    def to_screen(self,x,y):
        scale,origin=self.geometry_values();return QtCore.QPointF(origin.x()-y*scale,origin.y()-x*scale)
    def from_screen(self,point):
        scale,origin=self.geometry_values()
        return [max(0.,min(48.,(origin.y()-point.y())/scale)),max(-43.,min(43.,(origin.x()-point.x())/scale))]
    def detected(self,p):
        x,y=p
        return (self.enabled and x>=0 and math.hypot(x,y)<=self.RANGE_M+1e-9
                and abs(math.degrees(math.atan2(y,x)))<=self.HALF_FOV_DEG+1e-9)
    def sector_points(self,radius):
        return [self.to_screen(radius*math.cos(math.radians(degrees)),radius*math.sin(math.radians(degrees)))
                for degrees in range(-60,61,2)]
    def tracks(self):
        return [{'track_id':key,'center':[p[0],p[1],1.],'size':[1.,.5,1.5],'score':1.} for key,p in self.positions.items() if key<=self.count and self.detected(p)]
    def mousePressEvent(self,e):
        if not self.interactive or e.button()!=QtCore.Qt.LeftButton:return
        for key,p in self.positions.items():
            if key<=self.count and (self.to_screen(*p)-e.localPos()).manhattanLength()<25:
                self.dragging=key;self.positions[key]=self.from_screen(e.localPos());self.update();return
    def mouseMoveEvent(self,e):
        if self.dragging is not None:self.positions[self.dragging]=self.from_screen(e.localPos());self.update()
    def mouseReleaseEvent(self,e):
        if self.dragging is not None:
            self.positions[self.dragging]=self.from_screen(e.localPos());self.dragging=None;self.update()
    def paintEvent(self,event):
        p=QtGui.QPainter(self);p.setRenderHint(QtGui.QPainter.Antialiasing);p.fillRect(self.rect(),QtGui.QColor('#132130'))
        state=self.model.behavior.get('state','unknown')
        p.setPen(QtGui.QPen(QtGui.QColor('#22c55e' if state=='escaped' else '#334155'),5 if state=='escaped' else 1))
        p.drawRect(self.rect().adjusted(3,3,-3,-3))
        p.setPen(QtGui.QColor('#e2e8f0'));p.drawText(12,23,'2D位置・状態：'+NAMES.get(state,state))
        if self.interactive:p.drawText(12,43,'ドラッグで移動／破線の外へ出すと未検出')
        origin=self.to_screen(0,0)
        sector=QtGui.QPainterPath(origin)
        for at in self.sector_points(self.RANGE_M):sector.lineTo(at)
        sector.closeSubpath()
        p.setPen(QtGui.QPen(QtGui.QColor('#94a3b8'),1,QtCore.Qt.DashLine))
        p.setBrush(QtGui.QColor(45,100,145,45));p.drawPath(sector);p.setBrush(QtCore.Qt.NoBrush)
        for radius in (10,20,30,40):
            points=self.sector_points(radius);arc=QtGui.QPainterPath(points[0])
            for at in points[1:]:arc.lineTo(at)
            p.setPen(QtGui.QPen(QtGui.QColor('#4b647b'),1));p.drawPath(arc)
            p.setPen(QtGui.QColor('#a8bdcf'));p.drawText(self.to_screen(radius,0)+QtCore.QPointF(5,-3),f'{radius}m')
        for degrees in (-60,0,60):
            angle=math.radians(degrees);end=self.to_screen(self.RANGE_M*math.cos(angle),self.RANGE_M*math.sin(angle))
            p.setPen(QtGui.QPen(QtGui.QColor('#64748b'),1,QtCore.Qt.DashLine));p.drawLine(origin,end)
        p.setPen(QtGui.QColor('#cbd5e1'));p.drawText(12,self.height()-12,'視野120°（左右60°）／最大距離40m')
        p.setPen(QtGui.QPen(QtGui.QColor('#67e8f9'),2));p.setBrush(QtGui.QColor('#0891b2'))
        p.drawEllipse(origin,7,7)
        p.drawLine(origin+QtCore.QPointF(0,-8),origin+QtCore.QPointF(0,-27))
        p.drawLine(origin+QtCore.QPointF(0,-27),origin+QtCore.QPointF(-4,-21))
        p.drawLine(origin+QtCore.QPointF(0,-27),origin+QtCore.QPointF(4,-21))
        p.drawText(origin+QtCore.QPointF(12,4),'LiDAR (0, 0)')
        labels={t['id'].split(':')[-1]:t for t in self.model.behavior.get('targets',[])}
        for path in self.model.paths.values():
            p.setPen(QtGui.QPen(QtGui.QColor('#64748b'),1))
            for a,b in zip(list(path),list(path)[1:]):p.drawLine(self.to_screen(*a),self.to_screen(*b))
        rows=[(k,v) for k,v in self.positions.items() if k<=self.count] if self.interactive else [(t['track_id'],t['center'][:2]) for t in self.model.tracks]
        for key,xy in rows:
            info=labels.get(str(key),{});label=info.get('label','observing');at=self.to_screen(*xy)
            p.setPen(QtGui.QPen(QtGui.QColor('white'),2));p.setBrush(QtGui.QColor(COLORS.get(label,'gray')))
            p.drawEllipse(at,13,13);p.drawLine(at+QtCore.QPointF(-7,-11),at+QtCore.QPointF(-11,-21));p.drawLine(at+QtCore.QPointF(7,-11),at+QtCore.QPointF(11,-21))
            p.setPen(QtGui.QColor('white'));p.drawText(at+QtCore.QPointF(18,0),f"鹿{key} {NAMES.get(label,label)}")
            extra=f"{xy[0]:.1f}, {xy[1]:.1f} m"
            if info.get('stationary_seconds',0)>=2:extra+=' ／2秒停止'
            if info.get('present') is False and label=='observing':extra+=f" ／未検出 {info.get('missing_elapsed_seconds',0):.1f}/5秒"
            p.drawText(at+QtCore.QPointF(18,17),extra)
        p.end()
