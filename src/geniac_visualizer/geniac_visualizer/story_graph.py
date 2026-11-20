"""Interactive DAG with routed branches, current node and traversed path."""
from collections import defaultdict
from html import escape
import json
import math
import shlex
import subprocess
from PyQt5 import QtCore,QtGui,QtWidgets

BRANCHES={'escaped':('完全退避','#23875e'),'retreated_nearby':('移動・視界内','#b97812'),
          'no_escape':('動かなかった','#be4553'),'unknown':('確認待ち・不明','#81909f')}


class StoryNode(QtWidgets.QGraphicsRectItem):
    def __init__(self,key,node,width,height,clicked):
        super().__init__(-width/2,-height/2,width,height)
        self.key=key;self.node=node;self.clicked=clicked
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip(node.get('narrative',node.get('title',key)))
        self.text=QtWidgets.QGraphicsTextItem(self)
        self.text.setFont(QtGui.QFont('Noto Sans CJK JP',18,QtGui.QFont.Bold))
        self.text.setTextWidth(width-12);self.text.setPos(-width/2+6,-height/2+4)
        self.text.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        self.paint_state(False,False,False)

    @staticmethod
    def dimensions(key,node):
        # Measure the same rich text used for rendering, including a status line.
        font=QtGui.QFont('Noto Sans CJK JP',18,QtGui.QFont.Bold)
        title=node.get('title',key)
        width=max(220,math.ceil(QtGui.QFontMetricsF(font).horizontalAdvance(title)/2+28))
        probe=StoryNode(key,node,width,80,lambda _:None)
        probe.set_caption('行動の確定待ち（自動）')
        for _ in range(20):
            if probe.text.boundingRect().height()<=90:break
            width+=24
            probe.text.setTextWidth(width-12)
        return width,max(80,math.ceil(probe.text.boundingRect().height()+12))

    def paint_state(self,current,waiting,visited):
        color='#fff1ce' if current and waiting else '#dcecff' if current else '#e4f4ec' if visited else '#ffffff'
        self.setBrush(QtGui.QBrush(QtGui.QColor(color)))
        terminal=bool(self.node.get('terminal'))
        border='#d32f2f' if terminal else '#cb8a12' if waiting and current else '#2865ba' if current else '#a9b7c6'
        self.setPen(QtGui.QPen(QtGui.QColor(border),3 if current or terminal else 1))
        label='反応を入力' if current and waiting else '再生中' if current and not self.node.get('terminal') else ''
        self.set_caption(label)

    def set_caption(self,label=''):
        title=escape(self.node.get('title',self.key))
        status=f'<br><span style="font-size:9pt;font-weight:normal">{escape(label)}</span>' if label else ''
        self.text.setHtml(f'<div style="line-height:100%">{title}{status}</div>')
        self.text.setY(-self.text.boundingRect().height()/2)


    def mousePressEvent(self,event):self.clicked(self.key);event.accept()


class StoryGraph(QtWidgets.QGraphicsView):
    selected=QtCore.pyqtSignal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.setScene(QtWidgets.QGraphicsScene(self))
        self.setRenderHint(QtGui.QPainter.Antialiasing)
        self.setDragMode(self.ScrollHandDrag);self.setTransformationAnchor(self.AnchorUnderMouse)
        self.setBackgroundBrush(QtGui.QColor('#f4f7fb'));self.nodes={};self.edges={};self.current=None
        self._layouts=[];self._state=(None,False,[]);self._layout_size=QtCore.QSize()
        self._resize_timer=QtCore.QTimer(self);self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(180);self._resize_timer.timeout.connect(self._relayout)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'_resize_timer'):self._resize_timer.start()

    def _relayout(self):
        size=self.viewport().size()
        if hasattr(self,'tree') and (abs(size.width()-self._layout_size.width())>16 or
                                     abs(size.height()-self._layout_size.height())>16):
            self.set_tree(self.tree,relayout=True)

    def set_tree(self,tree,relayout=False):
        state=self._state if relayout else (None,False,[])
        captions={key:item.text.toHtml() for key,item in self.nodes.items()} if relayout else {}
        if not relayout:self._layouts=[]

        self.scene().clear();self.nodes={};self.edges={};self.tree=tree;self.current=None
        grouped=defaultdict(list)
        for key,node in tree['nodes'].items():
            for label,dest in node.get('branches',{}).items():
                # The player repeats the final scene for either visible response.
                if (label in ('no_escape','retreated_nearby') and tree['nodes'][dest].get('terminal')
                        and not node.get('escape_tail') and node.get('stage')!='withdrawal'):
                    dest=key
                grouped[key,dest].append(label)
        reachable=set();pending=[tree['root']]
        while pending:
            key=pending.pop()
            if key in reachable:continue
            reachable.add(key)
            pending.extend(dest for source,dest in grouped if source==key)
        grouped={edge:labels for edge,labels in grouped.items() if edge[0] in reachable}

        ids={key:'n'+str(i) for i,key in enumerate(tree['nodes']) if key in reachable};reverse={v:k for k,v in ids.items()}
        dot=['digraph G { graph [rankdir=TB,nodesep=0.35,ranksep=0.65]; node [shape=box,fixedsize=true,width=2.85,height=0.9]; edge [fontname="Noto Sans CJK JP",fontsize=10];']
        dimensions={key:StoryNode.dimensions(key,tree['nodes'][key]) for key in ids}
        dot += [f'{alias} [label="",width={dimensions[key][0]/72:.5f},height={dimensions[key][1]/72:.5f}];' for key,alias in ids.items()]
        for (source,dest),labels in grouped.items():
            text=' / '.join(BRANCHES[x][0] for x in labels)
            dot.append(f'{ids[source]} -> {ids[dest]} [label={json.dumps(text,ensure_ascii=False)}];')
        dot.append('}')
        positions={};routes=[]
        try:
            if not self._layouts:
                for direction in ('TB','LR'):
                    for node_gap,rank_gap in ((.35,.65),(.18,.35)):
                        source='\n'.join(dot).replace('rankdir=TB,nodesep=0.35,ranksep=0.65',
                            f'rankdir={direction},nodesep={node_gap},ranksep={rank_gap}')
                        result=subprocess.run(['dot','-Tplain'],input=source,text=True,capture_output=True,check=True,timeout=5)
                        candidate=[shlex.split(line) for line in result.stdout.splitlines()]
                        self._layouts.append((direction,candidate))
            width=max(1,self.viewport().width()-8);height=max(1,self.viewport().height()-8)
            def scale(candidate):
                header=candidate[1][0]
                return min(width/(float(header[2])*72+60),height/(float(header[3])*72+60))
            self.layout_direction,lines=max(self._layouts,key=scale)

            height=float(lines[0][3])
            point=lambda x,y:QtCore.QPointF(float(x)*72,(height-float(y))*72)
            for parts in lines:
                if parts[0]=='node':positions[reverse[parts[1]]]=(point(parts[2],parts[3]),float(parts[4])*72,float(parts[5])*72)
                if parts[0]=='edge':
                    n=int(parts[3]);points=[point(parts[4+2*i],parts[5+2*i]) for i in range(n)]
                    tail=parts[4+2*n:]
                    label_point=point(tail[1],tail[2]) if len(tail)>=5 else points[len(points)//2]
                    routes.append((reverse[parts[1]],reverse[parts[2]],points,label_point))
        except (OSError,subprocess.SubprocessError,ValueError,IndexError):
            self.layout_direction='LR' if self.viewport().width()>self.viewport().height()*1.4 else 'TB'
            horizontal=self.layout_direction=='LR'
            depths={tree['root']:0}
            for _ in tree['nodes']:
                for (source,dest) in grouped:
                    if source!=dest and source in depths:depths[dest]=max(depths.get(dest,0),depths[source]+1)
            layers=defaultdict(list)
            for key in ids:layers[depths.get(key,0)].append(key)
            column_width=max(w for w,h in dimensions.values())+190
            row_height=max(h for w,h in dimensions.values())+100
            for depth,keys in layers.items():
                for i,key in enumerate(keys):
                    pos=QtCore.QPointF(depth*column_width,i*row_height) if horizontal else QtCore.QPointF(i*column_width,depth*row_height)
                    positions[key]=(pos,*dimensions[key])
            for source,dest in grouped:
                if source==dest:
                    center,width,_=positions[source]
                    a=center+QtCore.QPointF(width/2,-18);b=center+QtCore.QPointF(width/2,18)
                    routes.append((source,dest,[a,a+QtCore.QPointF(100,-45),b+QtCore.QPointF(100,45),b],center+QtCore.QPointF(width/2+155,0)))
                    continue
                sw,sh=dimensions[source];dw,dh=dimensions[dest]
                a=positions[source][0]+(QtCore.QPointF(sw/2,0) if horizontal else QtCore.QPointF(0,sh/2))
                b=positions[dest][0]-(QtCore.QPointF(dw/2,0) if horizontal else QtCore.QPointF(0,dh/2))
                routes.append((source,dest,[a,b],(a+b)/2))
        for source,dest,points,label_point in routes:
            path=QtGui.QPainterPath(points[0])
            if (len(points)-1)%3==0:
                for i in range(1,len(points),3):path.cubicTo(points[i],points[i+1],points[i+2])
            else:
                for p in points[1:]:path.lineTo(p)
            labels=grouped[source,dest];color=BRANCHES[labels[0]][1] if len(labels)==1 else '#708195'
            item=self.scene().addPath(path,QtGui.QPen(QtGui.QColor(color),1.5));item.setZValue(-1)
            label=self.scene().addText(' / '.join(BRANCHES[x][0] for x in labels),QtGui.QFont('Noto Sans CJK JP',9))
            label.setDefaultTextColor(QtGui.QColor(color));label.setPos(label_point-label.boundingRect().center())
            delta=points[-1]-points[-2];angle=math.atan2(delta.y(),delta.x());tip=points[-1]
            arrow=QtGui.QPolygonF([tip,tip-QtCore.QPointF(9*math.cos(angle-.45),9*math.sin(angle-.45)),tip-QtCore.QPointF(9*math.cos(angle+.45),9*math.sin(angle+.45))])
            self.scene().addPolygon(arrow,QtGui.QPen(QtGui.QColor(color)),QtGui.QBrush(QtGui.QColor(color)))
            self.edges[source,dest]=(item,color)
        for key,(pos,width,height) in positions.items():
            node=StoryNode(key,tree['nodes'][key],width,height,self.selected.emit)
            node.setPos(pos);self.scene().addItem(node);self.nodes[key]=node
        self.update_state(*state)
        for key,caption in captions.items():
            if key in self.nodes:
                self.nodes[key].text.setHtml(caption)
                self.nodes[key].text.setY(-self.nodes[key].text.boundingRect().height()/2)
        self.setSceneRect(self.scene().itemsBoundingRect().adjusted(-30,-30,30,30));self.fit_all()
        self._layout_size=self.viewport().size()


    def update_state(self,current,waiting,transitions):
        self._state=(current,waiting,list(transitions))
        self.current=current;visited={t['node'] for t in transitions}
        pairs={(a['node'],b['node']) for a,b in zip(transitions,transitions[1:])}
        for key,node in self.nodes.items():node.paint_state(key==current,waiting,key in visited)
        for edge,(item,color) in self.edges.items():
            item.setPen(QtGui.QPen(QtGui.QColor('#2865ba' if edge in pairs else color),4 if edge in pairs else 1.5))

    def fit_all(self):self.fitInView(self.sceneRect(),QtCore.Qt.KeepAspectRatio)
    def focus_current(self):
        if self.current in self.nodes:
            self.resetTransform();self.centerOn(self.nodes[self.current])
    def wheelEvent(self,event):
        factor=1.15 if event.angleDelta().y()>0 else 1/1.15
        if .15<self.transform().m11()*factor<3.5:self.scale(factor,factor)
        event.accept()
