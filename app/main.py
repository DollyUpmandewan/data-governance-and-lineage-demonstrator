"""FastAPI application and role-aware catalogue API."""
import asyncio
import copy
import logging
import secrets
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text, update, or_
from sqlalchemy.exc import IntegrityError
from .config import Settings
from .db import database, User, LoginSession, Asset, MetadataVersion, AccessRequest, QualityRun, Audit, Source, audit, now
from .bootstrap import seed, initialize_sources
from .security import identity, hash_password, verify, DUMMY, digest, future, manages, require_manager, can_read
from .pipeline import run_pipeline, affected, SALES_MAPPING
from .purview import PurviewClient
from .purview_routes import router as purview_router, run_sync

log = logging.getLogger(__name__)

class Login(BaseModel):
    username: str = Field(min_length=1,max_length=80)
    password: str = Field(min_length=1,max_length=200)
class RequestAccess(BaseModel):
    purpose: str = Field(min_length=10,max_length=1000)
class Decision(BaseModel):
    action: str
    note: str = Field(min_length=5,max_length=1000)
class MetadataEdit(BaseModel):
    revision: int
    description: str = Field(min_length=10,max_length=3000)
    classification: str
    definitions: dict[str,str]
class CSVSource(BaseModel):
    asset_id: str = Field(pattern=r'^[a-z][a-z0-9_]{2,59}$')
    name: str = Field(min_length=3,max_length=100)
    description: str = Field(min_length=10,max_length=3000)
    owner_team: str = Field(min_length=2,max_length=100)
    key_column: str = Field(min_length=1,max_length=80)
    csv_content: str = Field(min_length=1,max_length=5_000_000)

class SchemaReview(BaseModel):
    revision: int
    definitions: dict[str,str]

class NewUser(BaseModel):
    username: str = Field(pattern=r'^[a-zA-Z0-9_.-]{3,80}$')
    password: str = Field(min_length=12,max_length=200)
    role: str
    team: str = Field(min_length=1,max_length=100)
class PasswordChange(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=12,max_length=200)


def create_app(settings=None):
    settings = settings or Settings.from_env()
    engine, factory = database(settings.database_url)

    def sync_after_scan():
        if settings.purview.enabled and settings.purview.sync_after_scan:
            try:
                return run_sync(factory, settings.purview, 'scheduler', app.state.purview_client_factory)
            except HTTPException:
                return {'status': 'skipped', 'summary': 'Purview is busy or its configuration is invalid'}
        return None

    async def scheduler():
        while True:
            await asyncio.sleep(settings.scan_interval)
            try:
                await asyncio.to_thread(run_pipeline,factory,settings.data_dir,'scheduler')
                await asyncio.to_thread(sync_after_scan)
            except HTTPException: pass
            except Exception: log.exception('Scheduled pipeline failed')

    @asynccontextmanager
    async def lifespan(app):
        if settings.auto_migrate:
            from alembic.config import Config
            from alembic import command
            cfg = Config(str(Path(__file__).resolve().parent.parent/'alembic.ini'))
            cfg.set_main_option('sqlalchemy.url',settings.database_url.replace('%','%%'))
            command.upgrade(cfg,'head')
        initialize_sources(settings.data_dir)
        with factory() as db: seed(db)
        task = asyncio.create_task(scheduler()) if settings.scan_interval else None
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError): await task
        engine.dispose()

    app = FastAPI(title='Atlas • Data Governance',version='2.0.0',lifespan=lifespan)
    app.state.factory, app.state.settings = factory, settings
    app.state.purview_client_factory = lambda: PurviewClient(settings.purview)
    app.include_router(purview_router(factory, settings.purview))

    @app.exception_handler(IntegrityError)
    async def conflict(request, error):
        return JSONResponse({'detail':'A concurrent change conflicts with this request; reload and retry'},status_code=409)

    @app.middleware('http')
    async def headers(request, call_next):
        if request.method in {'POST','PUT','PATCH','DELETE'}:
            length=request.headers.get('content-length')
            if length is None: return JSONResponse({'detail':'Content-Length required'},status_code=411)
            if not length.isdigit() or int(length)>8_000_000: return JSONResponse({'detail':'Request exceeds 8 MB limit'},status_code=413)
            origin = request.headers.get('origin')
            if origin and origin != settings.origin: return JSONResponse({'detail':'Origin not allowed'},status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['Cache-Control']='no-store'
        return response

    @app.get('/health/live')
    def live(): return {'status':'ok'}

    @app.get('/health/ready')
    def ready():
        try:
            with engine.connect() as conn: conn.execute(text('SELECT 1'))
            return {'status':'ready'}
        except Exception: return JSONResponse({'status':'unavailable'},status_code=503)

    @app.post('/api/login')
    def login(body:Login):
        with factory.begin() as db:
            user = db.get(User,body.username)
            if user and user.locked_until > now(): raise HTTPException(429,'Account temporarily locked; retry in 15 minutes')
            valid = verify(body.password,user.password if user else DUMMY)
            if not user or not valid:
                if user:
                    user.failed += 1
                    if user.failed >= 5: user.locked_until = future(900)
                audit(db,body.username,'login.failed','session')
                # Return rather than raise so failed-attempt state is committed.
                return JSONResponse({'detail':'Invalid username or password'},status_code=401)
            user.failed, user.locked_until = 0, ''
            token = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            db.add(LoginSession(token_hash=digest(token),user_id=user.id,csrf=csrf,expires=future(28800)))
            audit(db,user.id,'login.success','session')
            response = JSONResponse({'username':user.id,'role':user.role,'team':user.team,'csrf':csrf})
            response.set_cookie('catalogue_session',token,httponly=True,secure=settings.secure_cookies,samesite='strict',max_age=28800,path='/')
            return response

    @app.get('/api/me')
    def me(request:Request):
        with factory() as db:
            user, session = identity(request,db)
            return {'username':user.id,'role':user.role,'team':user.team,'csrf':session.csrf}

    @app.post('/api/logout')
    def logout(request:Request):
        with factory.begin() as db:
            user, session = identity(request,db,True)
            db.delete(session)
            audit(db,user.id,'logout','session')
        response=JSONResponse({'status':'signed out'})
        response.delete_cookie('catalogue_session')
        return response

    @app.post('/api/password')
    def password(body:PasswordChange,request:Request):
        with factory.begin() as db:
            user,_ = identity(request,db,True)
            if not verify(body.current_password,user.password): raise HTTPException(400,'Current password is incorrect')
            user.password=hash_password(body.new_password)
            db.query(LoginSession).filter_by(user_id=user.id).delete()
            audit(db,user.id,'password.changed',user.id)
        response=JSONResponse({'status':'Password changed; sign in again'})
        response.delete_cookie('catalogue_session')
        return response

    def get_asset(db,id):
        a=db.get(Asset,id)
        if not a: raise HTTPException(404,'Asset not found')
        return a

    def asset_response(db,a,user):
        return {**a.metadata_doc,'status':a.status,'revision':a.revision,'scanned_at':a.scanned_at,'observed_columns':a.observed_columns,'can_manage':manages(user,a),'can_preview':can_read(db,user,a),'downstream':affected(db.query(Asset).all(),a.id)}

    @app.get('/api/assets')
    def assets(request:Request,q:str=''):
        with factory() as db:
            user,_ = identity(request,db)
            return [asset_response(db,a,user) for a in db.query(Asset).order_by(Asset.id) if q.lower() in str(a.metadata_doc).lower()]

    @app.get('/api/assets/{id}')
    def asset(id:str,request:Request):
        with factory() as db:
            user,_=identity(request,db)
            return asset_response(db,get_asset(db,id),user)

    @app.get('/api/assets/{id}/preview')
    def preview(id:str,request:Request):
        with factory.begin() as db:
            user,_ = identity(request,db)
            a=get_asset(db,id)
            if not can_read(db,user,a): raise HTTPException(403,'Request and receive access before viewing data')
            if a.status!='ready': raise HTTPException(409,'Preview blocked until the dataset passes a fresh scan')
            audit(db,user.id,'data.preview',id,rows=min(len(a.records),25))
            return {'rows':a.records[:25],'total_rows':len(a.records)}

    @app.put('/api/assets/{id}')
    def edit(id:str,body:MetadataEdit,request:Request):
        with factory.begin() as db:
            user,_=identity(request,db,True)
            a=get_asset(db,id)
            require_manager(user,a)
            if body.classification not in {'internal','confidential'}: raise HTTPException(422,'Invalid classification')
            if body.revision != a.revision: raise HTTPException(409,'Metadata changed; reload before editing')
            doc=copy.deepcopy(a.metadata_doc)
            names={c['name'] for c in doc['columns']}
            if set(body.definitions)!=names or any(not v.strip() for v in body.definitions.values()): raise HTTPException(422,'Provide a definition for every column')
            doc.update(description=body.description,classification=body.classification)
            for c in doc['columns']: c['definition']=body.definitions[c['name']]
            changed=db.execute(update(Asset).where(Asset.id==id,Asset.revision==body.revision).values(metadata_doc=doc,revision=body.revision+1)).rowcount
            if changed!=1: raise HTTPException(409,'Metadata changed; reload before editing')
            db.add(MetadataVersion(asset_id=id,revision=body.revision+1,document=doc,actor=user.id))
            audit(db,user.id,'metadata.updated',id,revision=body.revision+1)
            return {'revision':body.revision+1}

    @app.post('/api/assets/{id}/schema/accept')
    def accept_schema(id:str,body:SchemaReview,request:Request):
        with factory.begin() as db:
            user,_=identity(request,db,True)
            a=get_asset(db,id)
            require_manager(user,a)
            if a.status!='schema_drift' or body.revision!=a.revision: raise HTTPException(409,'Schema or revision changed; reload')
            old={c['name'] for c in a.metadata_doc['columns']}
            observed=set(a.observed_columns)
            if not old<=observed: raise HTTPException(409,'Removed or renamed fields need a transformation and quality-rule migration; restore the source schema first')
            if set(body.definitions)!=observed or any(not v.strip() for v in body.definitions.values()): raise HTTPException(422,'Define every observed field')
            doc=copy.deepcopy(a.metadata_doc)
            previous={c['name']:c for c in doc['columns']}
            doc['columns']=[{**previous.get(name,{'name':name,'type':'string','classification':'personal'}),'definition':body.definitions[name]} for name in a.observed_columns]
            doc['classification']='confidential'
            updated=db.execute(update(Asset).where(Asset.id==id,Asset.revision==body.revision,Asset.status=='schema_drift').values(metadata_doc=doc,revision=body.revision+1,status='unscanned')).rowcount
            if updated!=1: raise HTTPException(409,'Concurrent update; reload')
            # A changed schema invalidates all existing preview grants for this asset.
            db.query(AccessRequest).filter_by(asset_id=id,status='approved').update({'status':'revoked','note':'Schema changed; request fresh access'})
            db.add(MetadataVersion(asset_id=id,revision=body.revision+1,document=doc,actor=user.id))
            audit(db,user.id,'schema.accepted',id,revision=body.revision+1,observed=a.observed_columns)
            return {'status':'unscanned','message':'Schema accepted. New fields marked personal; existing grants revoked. Run a fresh scan.'}

    @app.get('/api/assets/{id}/versions')
    def versions(id:str,request:Request):
        with factory() as db:
            identity(request,db)
            get_asset(db,id)
            return [{'revision':v.revision,'actor':v.actor,'at':v.at,'document':v.document} for v in db.query(MetadataVersion).filter_by(asset_id=id).order_by(MetadataVersion.revision.desc()).limit(30)]

    @app.post('/api/assets/{id}/requests')
    def request_access(id:str,body:RequestAccess,request:Request):
        with factory.begin() as db:
            user,_=identity(request,db,True)
            a=get_asset(db,id)
            if can_read(db,user,a): raise HTTPException(409,'You already have active access')
            if db.query(AccessRequest).filter_by(asset_id=id,user_id=user.id,status='pending').first(): raise HTTPException(409,'An access request is already pending')
            record=AccessRequest(asset_id=id,user_id=user.id,purpose=body.purpose)
            db.add(record)
            db.flush()
            audit(db,user.id,'access.requested',id,request_id=record.id)
            return {'id':record.id,'status':'pending'}

    @app.get('/api/requests')
    def requests(request:Request):
        with factory() as db:
            user,_=identity(request,db)
            output=[]
            query=db.query(AccessRequest)
            if user.role!='admin':
                owned=[a.id for a in db.query(Asset) if manages(user,a)]
                query=query.filter(or_(AccessRequest.user_id==user.id,AccessRequest.asset_id.in_(owned)))
            for r in query.order_by(AccessRequest.id.desc()).limit(200):
                manager=manages(user,get_asset(db,r.asset_id))
                if r.user_id==user.id or manager:
                    output.append({k:getattr(r,k) for k in ['id','asset_id','user_id','purpose','status','requested_at','decided_by','expires','note']} | {'can_decide':manager and r.user_id!=user.id,'effective_status':'expired' if r.status=='approved' and r.expires<=now() else r.status})
            return output

    @app.post('/api/requests/{id}/decision')
    def decide(id:int,body:Decision,request:Request):
        with factory.begin() as db:
            user,_=identity(request,db,True)
            r=db.get(AccessRequest,id)
            if not r: raise HTTPException(404,'Request not found')
            a=get_asset(db,r.asset_id)
            require_manager(user,a)
            if user.id==r.user_id: raise HTTPException(403,'You cannot approve your own request')
            if body.action not in {'approve','reject','revoke'}: raise HTTPException(422,'Invalid decision')
            expected='approved' if body.action=='revoke' else 'pending'
            values={'status':{'approve':'approved','reject':'rejected','revoke':'revoked'}[body.action],'decided_by':user.id,'decided_at':now(),'note':body.note,'expires':future(604800) if body.action=='approve' else None}
            changed=db.execute(update(AccessRequest).where(AccessRequest.id==id,AccessRequest.status==expected).values(**values)).rowcount
            if changed!=1: raise HTTPException(409,'Request already decided or not revocable')
            audit(db,user.id,'access.'+body.action,r.asset_id,request_id=id,note=body.note)
            return values

    @app.get('/api/sources')
    def sources(request:Request):
        with factory() as db:
            identity(request,db)
            return [{'asset_id':s.asset_id,'kind':s.kind,'location':s.location,'table_name':s.table_name} for s in db.query(Source).order_by(Source.asset_id)]

    @app.post('/api/sources/csv',status_code=201)
    def connect_csv(body:CSVSource,request:Request):
        import re
        from .connectors import read_csv
        with factory() as db:
            user,_=identity(request,db,True)
            if user.role!='admin': raise HTTPException(403,'Administrator access required')
            actor=user.id
        path=settings.data_dir/('upload-'+secrets.token_hex(16)+'.csv')
        committed=False
        try:
            with path.open('x',encoding='utf-8',newline='') as stream: stream.write(body.csv_content)
            columns,records=read_csv(path)
            if not records or len(columns)>100 or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}',c) for c in columns): raise HTTPException(422,'Provide nonempty CSV with up to 100 simple column names')
            if body.key_column not in columns: raise HTTPException(422,'Key column must exist in the CSV')
            doc={'id':body.asset_id,'name':body.name,'description':body.description,'source':'CSV • managed upload','path':path.name,'owner':{'team':body.owner_team,'contact':'Contact your workspace administrator'},'classification':'confidential','access':{'approved_roles':['owner approval required'],'approval_owner':body.owner_team,'purpose':'Purpose must be reviewed by the owner','retention':'Owner must define and approve a retention schedule','controls':['Owner-approved previews only; source permissions remain separate']},'columns':[{'name':c,'definition':'Owner review required: '+c,'type':'string','classification':'personal'} for c in columns],'quality_rules':[{'id':body.asset_id+'-key','type':'unique','column':body.key_column},{'id':body.asset_id+'-required','type':'not_null','column':body.key_column}],'inputs':[]}
            with factory.begin() as db:
                if db.get(Asset,body.asset_id): raise HTTPException(409,'Asset ID already exists')
                db.add(Asset(id=body.asset_id,metadata_doc=doc,records=[],observed_columns=[],status='unscanned'))
                db.flush()
                db.add(Source(asset_id=body.asset_id,kind='csv',location=path.name))
                db.add(MetadataVersion(asset_id=body.asset_id,revision=1,document=doc,actor=actor))
                audit(db,actor,'source.connected',body.asset_id,kind='csv',columns=len(columns))
            committed=True
            return {'asset_id':body.asset_id,'status':'unscanned','message':'Connected. Review definitions and run a scan before previewing.'}
        except ValueError as error: raise HTTPException(422,str(error))
        finally:
            if not committed: path.unlink(missing_ok=True)

    @app.post('/api/scans')
    def scan(request:Request):
        with factory() as db:
            user,_=identity(request,db,True)
            if user.role!='admin': raise HTTPException(403,'Only administrators can scan configured sources')
            actor=user.id
        result = run_pipeline(factory,settings.data_dir,actor)
        if settings.purview.enabled and settings.purview.sync_after_scan:
            try:
                result['purview'] = run_sync(factory, settings.purview, actor, app.state.purview_client_factory)
            except HTTPException:
                result['purview'] = {'status': 'skipped', 'summary': 'Purview is busy or its configuration is invalid'}
        return result

    @app.get('/api/runs')
    def runs(request:Request):
        with factory() as db:
            identity(request,db)
            return [{k:getattr(r,k) for k in ['id','at','actor','status','results','lineage','summary']} for r in db.query(QualityRun).order_by(QualityRun.id.desc()).limit(30)]

    @app.get('/api/lineage')
    def lineage(request:Request):
        with factory() as db:
            identity(request,db)
            last=next((r for r in db.query(QualityRun).order_by(QualityRun.id.desc()).limit(100) if r.lineage),None)
            return {'declared':SALES_MAPPING,'last_captured':last.lineage if last else [],'run_id':last.id if last else None,'captured_at':last.at if last else None}

    @app.get('/api/audit')
    def events(request:Request):
        with factory() as db:
            user,_=identity(request,db)
            if user.role!='admin': raise HTTPException(403,'Administrator access required')
            return [{k:getattr(r,k) for k in ['id','at','actor','action','resource','details']} for r in db.query(Audit).order_by(Audit.id.desc()).limit(200)]

    @app.post('/api/users')
    def users(body:NewUser,request:Request):
        with factory.begin() as db:
            user,_=identity(request,db,True)
            if user.role!='admin': raise HTTPException(403,'Administrator access required')
            if body.role not in {'admin','steward','analyst'}: raise HTTPException(422,'Invalid role')
            if db.get(User,body.username): raise HTTPException(409,'Username already exists')
            db.add(User(id=body.username,password=hash_password(body.password),role=body.role,team=body.team))
            audit(db,user.id,'user.created',body.username,role=body.role,team=body.team)
            return {'username':body.username}

    static=Path(__file__).parent/'static'
    app.mount('/static',StaticFiles(directory=static),name='static')
    @app.get('/')
    def home(): return FileResponse(static/'index.html')
    return app

app=create_app()
