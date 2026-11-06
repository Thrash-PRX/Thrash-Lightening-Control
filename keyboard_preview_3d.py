"""Small CPU-rendered 3D laptop scene: real vertices, depth sorting and orbit controls."""
import math
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget, QSizePolicy


class LOQKeyboardPreview(QWidget):
    """Stylized 3D LOQ model based on the supplied photo, not a manufacturer CAD model."""
    DEFAULT_VIEW = (-18.0, 35.0, 1.0)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Rotatable 3D LOQ laptop lighting preview")
        self.setToolTip("Drag to rotate · Wheel to zoom · Double-click or Home to reset · Arrow keys rotate. Stylized model based on your LOQ photo; one white keyboard zone.")
        self.level, self.maximum, self.available = 0, 2, False
        self.yaw, self.pitch, self.zoom = self.DEFAULT_VIEW
        self._drag_origin = None
        self._faces = []
        self._build_model()

    def _quad(self, points, color, kind="body", label=""):
        self._faces.append((tuple(points), color, kind, label, self._group))

    def _box(self, x0,y0,z0,x1,y1,z1,color,kind="body",label=""):
        v=[(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),
           (x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
        for ids,shade in [((0,1,5,4),0.65),((1,2,6,5),0.8),((2,3,7,6),0.55),((3,0,4,7),0.7),((0,3,2,1),0.4),((4,5,6,7),1.0)]:
            top = ids == (4,5,6,7)
            rgb=tuple(int(c*shade) for c in color)
            self._quad([v[i] for i in ids],rgb,kind if top else "body",label if top else "")

    @staticmethod
    def key_layout():
        rows=[
            [("Esc",1)]+[(f"F{i}",1) for i in range(1,13)]+[("Prt",1),("Ins",1),("Del",1)],
            [("`",1)]+[(k,1) for k in "1234567890-= ".strip()]+[("Back",2)],
            [("Tab",1.5)]+[(k,1) for k in "QWERTYUIOP[]"]+[("\\",1.5)],
            [("Caps",1.8)]+[(k,1) for k in "ASDFGHJKL;'"]+[("Enter",2.2)],
            [("Shift",2.3)]+[(k,1) for k in "ZXCVBNM,./"]+[("Shift",2.7)],
            [("Ctrl",1.3),("Fn",1),("Win",1),("Alt",1),("",5.4),("Alt",1),("Ctrl",1.3),("←",1),("↑",1),("→",1)],
        ]
        result=[]
        for row,items in enumerate(rows):
            x=0
            scale=15/sum(w for _,w in items)
            for label,w in items:
                if label in ("←","→"):
                    result.append((label,x,row+0.45,w*scale,1))
                else:
                    result.append((label,x,row,w*scale,1))
                x+=w*scale
            if row==5:
                result.append(("↓",13,6,1,0.45))
        pad=[("Num",0,1,1,1),("/",1,1,1,1),("*",2,1,1,1),("-",3,1,1,1),
             ("7",0,2,1,1),("8",1,2,1,1),("9",2,2,1,1),("+",3,2,1,2),
             ("4",0,3,1,1),("5",1,3,1,1),("6",2,3,1,1),
             ("1",0,4,1,1),("2",1,4,1,1),("3",2,4,1,1),("Enter",3,4,1,2),
             ("0",0,5,2,1),(".",2,5,1,1)]
        result.extend((label,15.5+x,y,w,h) for label,x,y,w,h in pad)
        return result

    def _build_model(self):
        self._group="base"
        self._box(-3.7,-2.6,-0.2,3.7,2.6,0,(83,87,90))
        self._group="details"
        self._box(-3.45,-2.3,0.006,3.45,0.65,0.025,(31,34,36))
        self._group="keys"
        unit=6.65/19.5
        for label,x,y,w,h in self.key_layout():
            self._box(-3.32+x*unit,-2.2+y*0.43,0.03,
                      -3.32+(x+w)*unit-0.035,-2.2+(y+h)*0.43-0.035,0.085,
                      (29,32,34),"key",label)
        self._group="details"
        self._box(-1.65,1.0,0.004,1.1,2.27,0.012,(72,77,80))
        self._box(-0.18,-2.51,0.02,0.18,-2.33,0.05,(119,122,123))
        # A thick hinged lid, with separate front glass and rear shell.
        self._group="lid"
        tilt=math.radians(18)
        def lid(x,h,offset=0):
            return (x,-2.55-math.sin(tilt)*h+offset,0.12+math.cos(tilt)*h)
        front=[lid(-3.7,0),lid(3.7,0),lid(3.7,4.7),lid(-3.7,4.7)]
        back=[lid(-3.7,0,-0.14),lid(3.7,0,-0.14),lid(3.7,4.7,-0.14),lid(-3.7,4.7,-0.14)]
        self._quad(front,(23,25,27),"lid_front")
        self._quad(back,(64,69,73),"lid_back","LOQ")
        for i in range(4):
            j=(i+1)%4
            self._quad([front[i],back[i],back[j],front[j]],(83,88,92))
        self._quad([lid(-3.42,0.35,0.012),lid(3.42,0.35,0.012),lid(3.42,4.4,0.012),lid(-3.42,4.4,0.012)],(14,15,26),"screen")
        # Geometric wallpaper is part of the 3D screen plane, not a rotated photograph.
        for radius,color in [(1.45,(37,27,59)),(1.05,(65,36,87)),(0.63,(102,55,113)),(0.34,(27,23,46))]:
            self._quad([lid(math.cos(i*math.pi/16)*radius,2.4+math.sin(i*math.pi/16)*radius*0.48,0.026) for i in range(32)],color,"screen")

    def set_native_state(self,level,maximum=2,available=True):
        maximum=max(1,int(maximum))
        state=(max(0,min(maximum,int(level))),maximum,bool(available))
        if state != (self.level,self.maximum,self.available):
            self.level,self.maximum,self.available=state
            self.setAccessibleDescription(f"{self.state_name()}. Rotatable 3D model; one white keyboard zone.")
            self.update()

    def state_name(self):
        return "Unavailable" if not self.available else "Off" if not self.level else "Bright" if self.level==self.maximum else "Dim"

    def orbit(self,dx,dy):
        self.yaw=(self.yaw+dx)%360
        self.pitch=max(-65,min(78,self.pitch+dy))
        self.update()

    def reset_view(self):
        self.yaw,self.pitch,self.zoom=self.DEFAULT_VIEW
        self.update()

    def _camera(self,point):
        x,y,z=point
        a,b=math.radians(self.yaw),math.radians(self.pitch)
        x,y=x*math.cos(a)-y*math.sin(a),x*math.sin(a)+y*math.cos(a)
        z-=1.35
        vertical=z*math.cos(b)-y*math.sin(b)
        depth=-(y*math.cos(b)+z*math.sin(b))
        perspective=16/(16+depth)
        return x*perspective,-vertical*perspective,depth

    def project(self,point):
        key=(self.yaw,self.pitch,self.zoom,self.width(),self.height())
        if getattr(self,"_projection_key",None)!=key:
            corners=[(x,y,z) for x in (-3.7,3.7) for y,z in [(-2.6,-0.2),(2.6,0),(-4.01,4.59)]]
            transformed=[self._camera(p) for p in corners]
            xmin,xmax=min(p[0] for p in transformed),max(p[0] for p in transformed)
            ymin,ymax=min(p[1] for p in transformed),max(p[1] for p in transformed)
            scale=min((self.width()-48)/max(1,xmax-xmin),(self.height()-44)/max(1,ymax-ymin))*self.zoom*0.93
            self._projection=(scale,(xmin+xmax)/2,(ymin+ymax)/2)
            self._projection_key=key
        scale,cx,cy=self._projection
        x,y,depth=self._camera(point)
        return QPointF(self.width()/2+(x-cx)*scale,(self.height()-28)/2+(y-cy)*scale),depth

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            self._drag_origin=event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self,event):
        if self._drag_origin is not None:
            delta=event.position()-self._drag_origin
            self._drag_origin=event.position()
            self.orbit(delta.x()*0.5,delta.y()*0.4)
            event.accept()

    def mouseReleaseEvent(self,event):
        self._drag_origin=None
        self.setCursor(Qt.OpenHandCursor)
        event.accept()

    def mouseDoubleClickEvent(self,event):
        self.reset_view()
        event.accept()

    def wheelEvent(self,event):
        self.zoom=max(0.6,min(1.6,self.zoom*math.pow(1.12,event.angleDelta().y()/120)))
        self.update()
        event.accept()

    def keyPressEvent(self,event):
        moves={Qt.Key_Left:(-10,0),Qt.Key_Right:(10,0),Qt.Key_Up:(0,8),Qt.Key_Down:(0,-8)}
        if event.key() in moves:
            self.orbit(*moves[event.key()])
        elif event.key()==Qt.Key_Home:
            self.reset_view()
        else:
            super().keyPressEvent(event)

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        visible=[]
        for points,color,kind,label,group in self._faces:
            if self.pitch < 0 and group in ("keys","details"):
                continue
            projected=[self.project(point) for point in points]
            if kind in ("screen","lid_front","lid_back"):
                area=sum(projected[i][0].x()*projected[(i+1)%len(projected)][0].y()-projected[(i+1)%len(projected)][0].x()*projected[i][0].y() for i in range(len(projected)))
                if (kind == "lid_back" and area <= 0) or (kind != "lid_back" and area >= 0):
                    continue
            visible.append((sum(depth for _,depth in projected)/len(projected),QPolygonF([p for p,_ in projected]),color,kind,label,group))
        glow=self.level/self.maximum if self.available else 0
        # Compose coplanar detail layers explicitly so a large deck polygon cannot
        # cover raised keys merely because their average camera depths differ.
        lid_near=self._camera((0,-3.2,2.3))[2] < self._camera((0,0,0))[2]
        order={"base":1,"details":2,"keys":3,"lid":4 if lid_near else 0}
        for depth,polygon,color,kind,label,group in sorted(visible,key=lambda f:(order[f[5]],-f[0])):
            painter.setPen(QPen(QColor(10,12,14,150),0.55))
            painter.setBrush(QColor(*color))
            if kind=="key":
                painter.setPen(QPen(QColor(255,255,255,int(15+glow*150)),0.65))
                painter.setBrush(QColor(27+int(glow*16),29+int(glow*16),31+int(glow*16)))
            painter.drawPolygon(polygon)
            if label:
                bounds=polygon.boundingRect()
                if bounds.width()>9 and bounds.height()>6:
                    painter.setPen(QColor(255,255,255,int(95+160*glow) if kind=="key" else 180))
                    painter.setFont(QFont("Segoe UI",max(4,min(9,int(bounds.height()*0.3)))))
                    if painter.fontMetrics().horizontalAdvance(label) <= bounds.width()-2:
                        painter.drawText(bounds,Qt.AlignCenter,label)
        painter.setPen(QColor("#a1a1aa"))
        painter.setFont(QFont("Segoe UI",8))
        painter.drawText(QRectF(0,self.height()-23,self.width(),22),Qt.AlignCenter,
                         f"{self.state_name().upper()}  ·  SINGLE WHITE ZONE   /   Drag to rotate · Scroll to zoom · Double-click to reset")
        painter.end()
