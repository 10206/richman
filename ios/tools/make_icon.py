from PIL import Image, ImageDraw
import math

SS = 4
S = 1024 * SS
GREEN_TOP=(172,224,94); GREEN_BOTTOM=(126,190,40); WHITE=(255,255,255)
def s(v): return v*SS
def norm(v):
    m=math.hypot(*v) or 1.0; return (v[0]/m, v[1]/m)
def centers_of(pts, r):
    n=len(pts); out=[]
    for i in range(n):
        V=pts[i]; A=pts[(i-1)%n]; B=pts[(i+1)%n]
        u=norm((A[0]-V[0],A[1]-V[1])); w=norm((B[0]-V[0],B[1]-V[1]))
        bis=norm((u[0]+w[0],u[1]+w[1]))
        half=math.acos(max(-1,min(1,u[0]*bis[0]+u[1]*bis[1])))
        d=r/max(math.sin(half),1e-3)
        out.append((V[0]+bis[0]*d, V[1]+bis[1]*d))
    return out
def rmask(pts, r):
    m=Image.new("L",(S,S),0); d=ImageDraw.Draw(m); c=centers_of(pts,r)
    d.polygon(c,fill=255)
    for i in range(len(c)): d.line([c[i],c[(i+1)%len(c)]],fill=255,width=int(2*r))
    for p in c: d.ellipse([p[0]-r,p[1]-r,p[0]+r,p[1]+r],fill=255)
    return m
def vgrad(a,b):
    g=Image.new("RGB",(S,S),a); px=g.load()
    for y in range(S):
        t=y/(S-1); col=tuple(int(a[i]+(b[i]-a[i])*t) for i in range(3))
        for x in range(S): px[x,y]=col
    return g

img=Image.new("RGB",(S,S),WHITE)
apex=(s(512),s(196)); bl=(s(250),s(758)); br=(s(774),s(758))
img=Image.composite(vgrad(GREEN_TOP,GREEN_BOTTOM), img, rmask([apex,bl,br], s(70)))
d=ImageDraw.Draw(img)
line=[(s(362),s(688)), (s(500),s(610)), (s(622),s(508))]
d.line(line, fill=WHITE, width=int(s(30)), joint="curve")
p=line[0]; rr=s(15); d.ellipse([p[0]-rr,p[1]-rr,p[0]+rr,p[1]+rr], fill=WHITE)
nx,ny,nr=s(622),s(508),s(33); d.ellipse([nx-nr,ny-nr,nx+nr,ny+nr], fill=WHITE)
final=img.resize((1024,1024), Image.LANCZOS)
final.save("icon_final.png")
# 홈 화면 프리뷰용: iOS 스퀘어클 마스크 근사(라운드 사각형)로 잘라 확인
prev=final.copy()
mask=Image.new("L",(1024,1024),0); ImageDraw.Draw(mask).rounded_rectangle([0,0,1023,1023],radius=225,fill=255)
out=Image.new("RGBA",(1024,1024),(0,0,0,0)); out.paste(prev,(0,0),mask)
out.resize((240,240),Image.LANCZOS).save("icon_final_preview.png")
print("done", final.size, final.mode)
