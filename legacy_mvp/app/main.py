from __future__ import annotations
import base64, hmac, html, io, json, os, re, secrets, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

BASE = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('STUDIO_DATA_DIR', str(BASE/'data'))).resolve()
MEDIA = DATA/'media'; MEDIA.mkdir(parents=True,exist_ok=True)
DB = DATA/'studio.db'
JINJA = Environment(loader=FileSystemLoader(str(BASE/'app'/'templates')),autoescape=select_autoescape(['html']))
app = FastAPI(title='Alien Time Listing Studio', docs_url=None, redoc_url=None)
app.mount('/static',StaticFiles(directory=str(BASE/'app'/'static')),name='static')
CHANNELS = ('shopify','instagram','facebook_page','chrono24','whatsapp','carousell','facebook_groups','reddit','ebay')
CHANNEL_NAMES = {'shopify':'Shopify','instagram':'Instagram','facebook_page':'Facebook Page','chrono24':'Chrono24','whatsapp':'WhatsApp','carousell':'Carousell','facebook_groups':'FB dealer groups','reddit':'Reddit','ebay':'eBay'}

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def connect():
    c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c

def init_db():
    with connect() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS watches (id TEXT PRIMARY KEY, sku TEXT NOT NULL UNIQUE, brand TEXT NOT NULL, model TEXT NOT NULL, reference TEXT, year TEXT, price TEXT, currency TEXT DEFAULT 'SGD', condition TEXT, set_details TEXT, custody TEXT, notes TEXT, status TEXT NOT NULL DEFAULT 'draft', revision INTEGER NOT NULL DEFAULT 1, approved_revision INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, watch_id TEXT NOT NULL REFERENCES watches(id), filename TEXT NOT NULL, original TEXT NOT NULL, prepared TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS channel_drafts (watch_id TEXT NOT NULL REFERENCES watches(id), channel TEXT NOT NULL, copy TEXT NOT NULL, revision INTEGER NOT NULL, PRIMARY KEY (watch_id,channel));
        CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, watch_id TEXT, action TEXT NOT NULL, detail TEXT, at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS publish_jobs (watch_id TEXT NOT NULL,channel TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'not_connected',external_url TEXT,PRIMARY KEY(watch_id,channel));''')
init_db()

# Dev-only password protection. Deploy behind HTTPS and identity-aware access in production.
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        pw=os.environ.get('STUDIO_PASSWORD','')
        if pw:
            header=request.headers.get('authorization','')
            try:
                scheme,token=header.split(' ',1)
                raw=base64.b64decode(token,validate=True).decode() if scheme.lower()=='basic' else ''
                user,provided=raw.split(':',1)
            except (ValueError,UnicodeError): user=provided=''
            if not (hmac.compare_digest(user,'admin') and hmac.compare_digest(provided,pw)):
                return Response(status_code=401,headers={'WWW-Authenticate':'Basic realm="Alien Time Studio"'})
        return await call_next(request)
app.add_middleware(AuthMiddleware)

def page(request,title,**kwargs):
    return HTMLResponse(JINJA.get_template('base.html').render(request=request,title=title,channels=CHANNELS,channel_names=CHANNEL_NAMES,**kwargs))
def detail_or_404(wid):
    with connect() as c:
        w=c.execute('SELECT * FROM watches WHERE id=?',(wid,)).fetchone()
        if not w: raise HTTPException(404,'Watch not found')
        return dict(w)
def flash_redirect(url,msg=''):
    return RedirectResponse(url+('?notice='+quote(msg) if msg else ''),status_code=303)
def audit(c,wid,action,detail=''):
    c.execute('INSERT INTO audit(watch_id,action,detail,at) VALUES(?,?,?,?)',(wid,action,detail,now()))
def safe_sku(value):
    s=re.sub('[^A-Za-z0-9_-]+','-',value).strip('-')[:50]
    if not s: raise HTTPException(400,'Invalid SKU')
    return s

def validated_text(x,maxlen=3000): return x.strip()[:maxlen]

@app.get('/',response_class=HTMLResponse)
def dashboard(request:Request):
    with connect() as c:
        watches=[dict(x) for x in c.execute('SELECT w.*,(SELECT count(*) FROM assets a WHERE a.watch_id=w.id) asset_count FROM watches w ORDER BY updated_at DESC')]
    return page(request,'Watch dashboard',view='dashboard',watches=watches)

@app.post('/watches')
def create_watch(sku:str=Form(...),brand:str=Form(...),model:str=Form(...),reference:str=Form(''),year:str=Form(''),price:str=Form(''),condition:str=Form(''),custody:str=Form(''),set_details:str=Form(''),notes:str=Form('')):
    wid=uuid.uuid4().hex[:12]; sku=safe_sku(sku)
    if not brand.strip() or not model.strip():raise HTTPException(400,'Brand and model required')
    try:
        with connect() as c:
            c.execute('INSERT INTO watches(id,sku,brand,model,reference,year,price,condition,custody,set_details,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(wid,sku,*[validated_text(x) for x in [brand,model,reference,year,price,condition,custody,set_details,notes]],now(),now()))
            audit(c,wid,'created','Watch created')
    except sqlite3.IntegrityError: raise HTTPException(400,'SKU already exists')
    return flash_redirect(f'/watches/{wid}','Watch created')

def get_bundle(wid):
    w=detail_or_404(wid)
    with connect() as c:
        images=[dict(x) for x in c.execute('SELECT * FROM assets WHERE watch_id=? ORDER BY created_at',(wid,))]
        drafts={x['channel']:dict(x) for x in c.execute('SELECT * FROM channel_drafts WHERE watch_id=?',(wid,))}
        jobs={x['channel']:dict(x) for x in c.execute('SELECT * FROM publish_jobs WHERE watch_id=?',(wid,))}
        history=[dict(x) for x in c.execute('SELECT * FROM audit WHERE watch_id=? ORDER BY id DESC LIMIT 15',(wid,))]
    return w,images,drafts,jobs,history

@app.get('/watches/{wid}',response_class=HTMLResponse)
def watch_detail(request:Request,wid:str):
    w,images,drafts,jobs,history=get_bundle(wid)
    return page(request,f'{w["brand"]} {w["model"]}',view='detail',watch=w,images=images,drafts=drafts,jobs=jobs,history=history)

@app.post('/watches/{wid}/update')
def update_watch(wid:str,brand:str=Form(...),model:str=Form(...),reference:str=Form(''),year:str=Form(''),price:str=Form(''),condition:str=Form(''),custody:str=Form(''),set_details:str=Form(''),notes:str=Form('')):
    detail_or_404(wid)
    with connect() as c:
        c.execute('UPDATE watches SET brand=?,model=?,reference=?,year=?,price=?,condition=?,custody=?,set_details=?,notes=?,revision=revision+1,approved_revision=NULL,status="draft",updated_at=? WHERE id=?',(*[validated_text(x) for x in [brand,model,reference,year,price,condition,custody,set_details,notes]],now(),wid))
        audit(c,wid,'edited','Approval cleared after editing product facts')
    return flash_redirect(f'/watches/{wid}','Saved. Prior approval cleared.')

@app.post('/watches/{wid}/images')
async def upload_images(wid:str,files:list[UploadFile]=File(...)):
    detail_or_404(wid)
    if len(files)>25: raise HTTPException(400,'Maximum 25 photos at once')
    added=0
    for f in files:
        payload=await f.read(16*1024*1024+1)
        if len(payload)>16*1024*1024: raise HTTPException(413,'File exceeds 16MB')
        try:
            im=Image.open(io.BytesIO(payload));im.verify()
            im=Image.open(io.BytesIO(payload));im=ImageOps.exif_transpose(im)
            if im.width*im.height>40_000_000: raise ValueError('Image too large')
            im=im.convert('RGB')
        except (UnidentifiedImageError,OSError,ValueError) as e:raise HTTPException(400,'Invalid image') from e
        aid=uuid.uuid4().hex[:16]
        folder=MEDIA/wid;folder.mkdir(exist_ok=True)
        # Re-encode to remove untrusted metadata and avoid exposing source filenames.
        original=folder/f'{aid}_original.jpg';prepared=folder/f'{aid}_prepared.jpg'
        im.save(original,'JPEG',quality=94)
        # Local-only starter preparation: contain watch inside neutral canvas, no generated/watch pixels.
        canvas=Image.new('RGB',(1200,1200),(245,245,243))
        thumb=im.copy();thumb.thumbnail((1100,1100),Image.Resampling.LANCZOS)
        canvas.paste(thumb,((1200-thumb.width)//2,(1200-thumb.height)//2))
        canvas.save(prepared,'JPEG',quality=94)
        with connect() as c:
            c.execute('INSERT INTO assets VALUES(?,?,?,?,?,?)',(aid,wid,validated_text(f.filename or 'image.jpg',180),str(original),str(prepared),now()))
        added+=1
    if added:
        with connect() as c:
            c.execute('UPDATE watches SET revision=revision+1,approved_revision=NULL,status="draft",updated_at=? WHERE id=?',(now(),wid))
            audit(c,wid,'images_added',f'{added} photo(s) uploaded. Not AI-enhanced or serial-checked.')
    return flash_redirect(f'/watches/{wid}',f'{added} photos uploaded')

@app.get('/assets/{wid}/{aid}/{variant}')
def asset(wid:str,aid:str,variant:str):
    detail_or_404(wid)
    with connect() as c: row=c.execute('SELECT * FROM assets WHERE id=? AND watch_id=?',(aid,wid)).fetchone()
    if not row or variant not in ('original','prepared'):raise HTTPException(404)
    path=Path(row[variant] or '')
    if not path.is_file() or MEDIA not in path.resolve().parents: raise HTTPException(404)
    return FileResponse(path,media_type='image/jpeg',headers={'Cache-Control':'private, no-store'})

def make_copy(w,channel):
    head=f"{w['brand']} {w['model']}"+(f" | Ref. {w['reference']}" if w['reference'] else '')
    bullets=[]
    for k,label in [('year','Year'),('condition','Condition'),('set_details','Set'),('custody','Availability')]:
        if w[k]: bullets.append(f'{label}: {w[k]}')
    if w['price']: bullets.append(f"Price: {w['price']} {w['currency']}")
    body='\n'.join(bullets)
    if channel=='instagram': return f'{head}\n\n{body}\n\nEnquire for more information.\n\n#LuxuryWatches #AlienTime'
    if channel=='whatsapp':return f'*{head}*\n{body}\nDM for availability.'
    if channel=='shopify':return f'{head}\n\n{body}\n\nPlease contact us to confirm details and availability.'
    return f'{head}\n{body}\n\nContact Alien Time for enquiries.'

@app.post('/watches/{wid}/drafts')
def draft_copy(wid:str):
    w=detail_or_404(wid)
    with connect() as c:
        c.execute('UPDATE watches SET revision=revision+1,approved_revision=NULL,status="draft",updated_at=? WHERE id=?',(now(),wid))
        r=c.execute('SELECT revision FROM watches WHERE id=?',(wid,)).fetchone()['revision']
        for ch in CHANNELS:
            c.execute('INSERT OR REPLACE INTO channel_drafts(watch_id,channel,copy,revision) VALUES(?,?,?,?)',(wid,ch,make_copy(w,ch),r))
        audit(c,wid,'drafts_generated','Template drafts only; no AI or verification')
    return flash_redirect(f'/watches/{wid}','Draft copy created from product fields')

@app.post('/watches/{wid}/drafts/{channel}')
def edit_copy(wid:str,channel:str,copy:str=Form(...)):
    if channel not in CHANNELS: raise HTTPException(404)
    detail_or_404(wid)
    with connect() as c:
        c.execute('UPDATE watches SET revision=revision+1,approved_revision=NULL,status="draft",updated_at=? WHERE id=?',(now(),wid))
        r=c.execute('SELECT revision FROM watches WHERE id=?',(wid,)).fetchone()['revision']
        c.execute('INSERT OR REPLACE INTO channel_drafts VALUES(?,?,?,?)',(wid,channel,validated_text(copy,10000),r))
        audit(c,wid,'copy_updated',f'Edited {channel} copy; prior approval cleared')
    return flash_redirect(f'/watches/{wid}','Copy updated')

@app.post('/watches/{wid}/approve')
def approve(wid:str,confirm:str=Form('')):
    w,images,drafts,jobs,history=get_bundle(wid)
    if confirm!='yes': raise HTTPException(400,'Confirmation is required')
    if not images or not drafts: raise HTTPException(400,'Upload photos and create drafts first')
    with connect() as c:
        c.execute('UPDATE watches SET approved_revision=revision,status="approved",updated_at=? WHERE id=?',(now(),wid))
        audit(c,wid,'approved',f'Approved revision {w["revision"]} for preparation only; images not verified for serial safety')
    return flash_redirect(f'/watches/{wid}','Approved internally. Live publishing is disabled.')

@app.post('/watches/{wid}/lifecycle')
def lifecycle(wid:str,status:str=Form(...)):
    if status not in ('draft','reserved','sold','withdrawn'):raise HTTPException(400,'Invalid status')
    detail_or_404(wid)
    with connect() as c:
        c.execute('UPDATE watches SET status=?,updated_at=? WHERE id=?',(status,now(),wid))
        audit(c,wid,'status_changed',f'Set to {status}. No external platforms updated.')
    return flash_redirect(f'/watches/{wid}',f'Status: {status}. External channels not updated.')

@app.get('/watches/{wid}/export')
def export_pack(wid:str):
    import zipfile
    w,images,drafts,jobs,history=get_bundle(wid)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('product.json',json.dumps({k:v for k,v in w.items() if k not in ('id',)},indent=2))
        z.writestr('README.txt','DRAFT PACK ONLY. Check serials, watch accuracy, prices and platform rules before publishing. No live posting has happened.\n')
        for ch,d in drafts.items(): z.writestr(f'copy/{ch}.txt',d['copy'])
        for i,a in enumerate(images,1):z.write(a['prepared'],f'images/image_{i:02d}.jpg')
    return Response(out.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{w["sku"]}_draft_pack.zip"','Cache-Control':'no-store'})

@app.get('/health')
def health():return {'status':'ok','mode':'local-mvp','publishing':'disabled','ai':'not_configured'}
