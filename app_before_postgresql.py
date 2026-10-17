import os, sqlite3, secrets, json, io
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, g, request, redirect, url_for, session, flash, render_template, abort, send_file
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('DATABASE_PATH', os.path.join(BASE, 'fan_platform.db'))
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret-key-before-production-' + secrets.token_hex(8))

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'fan', city TEXT DEFAULT '', country TEXT DEFAULT 'Egypt', birth_year INTEGER, gender TEXT DEFAULT '', consent_analytics INTEGER DEFAULT 0, consent_marketing INTEGER DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fan_profiles(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, fan_code TEXT UNIQUE NOT NULL, favorite_ip_id INTEGER, favorite_character TEXT DEFAULT '', genres TEXT DEFAULT '', engagement_score INTEGER DEFAULT 0, segment TEXT DEFAULT 'Casual Fan', points INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ips(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT DEFAULT '', owner TEXT DEFAULT '', image_url TEXT DEFAULT '', active INTEGER DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS characters(id INTEGER PRIMARY KEY AUTOINCREMENT, ip_id INTEGER REFERENCES ips(id) ON DELETE CASCADE, name TEXT NOT NULL, description TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT, product_code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, ip_id INTEGER REFERENCES ips(id), product_type TEXT DEFAULT 'Merchandise', manufacturer TEXT DEFAULT '', distributor TEXT DEFAULT '', retailer TEXT DEFAULT '', batch TEXT DEFAULT '', authorized INTEGER DEFAULT 1, description TEXT DEFAULT '', points INTEGER DEFAULT 30, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS product_scans(id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER REFERENCES products(id), user_id INTEGER REFERENCES users(id), scanned_at TEXT NOT NULL, city TEXT DEFAULT '', status TEXT DEFAULT 'valid', ip_address TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS registered_products(id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER REFERENCES products(id), user_id INTEGER REFERENCES users(id), registered_at TEXT NOT NULL, UNIQUE(product_id,user_id));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, ip_id INTEGER REFERENCES ips(id), location TEXT DEFAULT '', event_date TEXT DEFAULT '', event_time TEXT DEFAULT '', capacity INTEGER DEFAULT 100, description TEXT DEFAULT '', organizer TEXT DEFAULT '', active INTEGER DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event_registrations(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER REFERENCES events(id), user_id INTEGER REFERENCES users(id), ticket_code TEXT UNIQUE NOT NULL, registered_at TEXT NOT NULL, checked_in INTEGER DEFAULT 0, checked_in_at TEXT, UNIQUE(event_id,user_id));
CREATE TABLE IF NOT EXISTS communities(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, ip_id INTEGER REFERENCES ips(id), description TEXT DEFAULT '', city TEXT DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS community_members(id INTEGER PRIMARY KEY AUTOINCREMENT, community_id INTEGER REFERENCES communities(id), user_id INTEGER REFERENCES users(id), joined_at TEXT NOT NULL, UNIQUE(community_id,user_id));
CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY AUTOINCREMENT, community_id INTEGER REFERENCES communities(id), user_id INTEGER REFERENCES users(id), body TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT DEFAULT 'published');
CREATE TABLE IF NOT EXISTS campaigns(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, ip_id INTEGER REFERENCES ips(id), description TEXT DEFAULT '', start_date TEXT DEFAULT '', end_date TEXT DEFAULT '', active INTEGER DEFAULT 1, reward_points INTEGER DEFAULT 50, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_actions(id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER REFERENCES campaigns(id), user_id INTEGER REFERENCES users(id), action TEXT NOT NULL, points INTEGER DEFAULT 0, created_at TEXT NOT NULL, UNIQUE(campaign_id,user_id,action));
CREATE TABLE IF NOT EXISTS rewards(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT DEFAULT '', points_cost INTEGER DEFAULT 100, reward_type TEXT DEFAULT 'Digital Content', active INTEGER DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reward_redemptions(id INTEGER PRIMARY KEY AUTOINCREMENT, reward_id INTEGER REFERENCES rewards(id), user_id INTEGER REFERENCES users(id), points_spent INTEGER NOT NULL, code TEXT UNIQUE NOT NULL, redeemed_at TEXT NOT NULL, status TEXT DEFAULT 'issued');
CREATE TABLE IF NOT EXISTS content(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content_type TEXT DEFAULT 'Article', url TEXT DEFAULT '', description TEXT DEFAULT '', ip_id INTEGER REFERENCES ips(id), created_at TEXT NOT NULL, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS interactions(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id), event_type TEXT NOT NULL, entity_type TEXT DEFAULT '', entity_id INTEGER, metadata TEXT DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT DEFAULT '', target_segment TEXT DEFAULT 'All Fans', ip_id INTEGER REFERENCES ips(id), created_at TEXT NOT NULL, created_by INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS consent_records(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id), consent_type TEXT NOT NULL, granted INTEGER NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS partners(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, partner_type TEXT DEFAULT 'Retailer', email TEXT DEFAULT '', city TEXT DEFAULT '', status TEXT DEFAULT 'active', created_at TEXT NOT NULL);
'''

def now(): return datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
def db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db
@app.teardown_appcontext
def close_db(exc):
    conn = g.pop('db', None)
    if conn is not None: conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row; conn.execute('PRAGMA foreign_keys=ON'); conn.executescript(SCHEMA)
    if conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0:
        ts=now()
        demo=[('Platform Admin','admin@fanintel.demo','Admin123!','admin','Cairo'),('IP Owner','owner@fanintel.demo','Owner123!','ip_owner','Cairo'),('Retail Partner','partner@fanintel.demo','Partner123!','partner','Giza'),('Community Manager','community@fanintel.demo','Community123!','community_manager','Alexandria'),('Demo Fan','fan@fanintel.demo','Fan123!','fan','Cairo')]
        for name,email,pw,role,city in demo:
            cur=conn.execute('INSERT INTO users(name,email,password_hash,role,city,country,consent_analytics,consent_marketing,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(name,email,generate_password_hash(pw),role,city,'Egypt',1,1,ts))
            uid=cur.lastrowid
            if role=='fan': conn.execute('INSERT INTO fan_profiles(user_id,fan_code, favorite_character,genres,engagement_score,segment,points) VALUES(?,?,?,?,?,?,?)',(uid,'FAN-2026-000001','Luffy','Adventure,Anime',87,'Super Fan',2450))
        ip1=conn.execute('INSERT INTO ips(name,description,owner,created_at) VALUES(?,?,?,?)',('One Piece','Official IP demo record. Replace with authorized IP information.','Demo Media Company',ts)).lastrowid
        ip2=conn.execute('INSERT INTO ips(name,description,owner,created_at) VALUES(?,?,?,?)',('Demon Slayer','Second sample IP for testing dynamic dashboards.','Demo Media Company',ts)).lastrowid
        conn.execute('UPDATE fan_profiles SET favorite_ip_id=? WHERE user_id=(SELECT id FROM users WHERE role="fan" LIMIT 1)',(ip1,))
        conn.execute('INSERT INTO characters(ip_id,name,description) VALUES(?,?,?)',(ip1,'Monkey D. Luffy','Sample character'))
        p1=conn.execute('INSERT INTO products(product_code,name,ip_id,product_type,manufacturer,distributor,retailer,batch,authorized,description,points,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',('PROD-ONEPIECE-00092832','Luffy Figure',ip1,'Figure','Demo Manufacturer','Demo Distributor','Demo Store','BATCH-001',1,'Sample authorized product. QR verification is dynamic.',30,ts)).lastrowid
        conn.execute('INSERT INTO products(product_code,name,ip_id,product_type,manufacturer,distributor,retailer,batch,authorized,description,points,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',('PROD-DS-000002','Tanjiro Keychain',ip2,'Accessory','Demo Manufacturer','Demo Distributor','Demo Store','BATCH-002',1,'Sample product for testing.',25,ts))
        conn.execute('INSERT INTO events(name,ip_id,location,event_date,event_time,capacity,description,organizer,created_at) VALUES(?,?,?,?,?,?,?,?,?)',('Egypt Anime Fan Meetup',ip1,'Cairo, Egypt',(datetime.utcnow()+timedelta(days=14)).date().isoformat(),'16:00',250,'Demo event. Register to receive a ticket QR code.','Demo Organizer',ts))
        conn.execute('INSERT INTO communities(name,ip_id,description,city,created_at) VALUES(?,?,?,?,?)',('One Piece Egypt Community',ip1,'A sample fan community for posts and discussions.','Cairo',ts))
        conn.execute('INSERT INTO campaigns(name,ip_id,description,start_date,end_date,active,reward_points,created_at) VALUES(?,?,?,?,?,?,?,?)',('Become an Official One Piece Fan',ip1,'Register, scan an official product and join a community.',datetime.utcnow().date().isoformat(),(datetime.utcnow()+timedelta(days=60)).date().isoformat(),1,100,ts))
        conn.execute('INSERT INTO rewards(name,description,points_cost,reward_type,active,created_at) VALUES(?,?,?,?,?,?)',('Exclusive Digital Badge','A digital badge for your fan profile.',200,'Exclusive Badge',1,ts))
        conn.execute('INSERT INTO rewards(name,description,points_cost,reward_type,active,created_at) VALUES(?,?,?,?,?,?)',('Official Content Access','Sample reward redemption.',500,'Digital Content',1,ts))
        conn.execute('INSERT INTO content(title,content_type,url,description,ip_id,created_at,active) VALUES(?,?,?,?,?,?,?)',('One Piece Official Trailer','Video','https://www.youtube.com/','Demo content record. Replace URL with a verified official link.',ip1,ts,1))
        conn.execute('INSERT INTO partners(name,partner_type,email,city,status,created_at) VALUES(?,?,?,?,?,?)',('Demo Authorized Store','Retailer','store@example.demo','Cairo','active',ts))
        conn.commit()
    conn.close()

@app.context_processor
def inject_globals(): return {'current_user': current_user(), 'role_labels': {'admin':'Platform Admin','ip_owner':'IP Owner','partner':'Distributor / Retailer','event_organizer':'Event Organizer','community_manager':'Community Manager','fan':'Fan / Customer'}, 'year':datetime.utcnow().year}
def current_user():
    if 'user_id' not in session: return None
    return db().execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone()
def login_required(f):
    @wraps(f)
    def decorated(*a,**kw):
        if not current_user(): flash('Please sign in to continue.','warning'); return redirect(url_for('login',next=request.path))
        return f(*a,**kw)
    return decorated
def roles_required(*roles):
    def deco(f):
        @wraps(f)
        def wrapped(*a,**kw):
            u=current_user()
            if not u: return redirect(url_for('login',next=request.path))
            if u['role'] not in roles: abort(403)
            return f(*a,**kw)
        return wrapped
    return deco
def log_event(user_id,event_type,entity_type='',entity_id=None,metadata=None):
    db().execute('INSERT INTO interactions(user_id,event_type,entity_type,entity_id,metadata,created_at) VALUES(?,?,?,?,?,?)',(user_id,event_type,entity_type,entity_id,json.dumps(metadata or {}),now())); db().commit()
def award_points(user_id, amount, reason, entity_type='', entity_id=None):
    if not user_id or amount <= 0: return
    conn=db(); conn.execute('INSERT OR IGNORE INTO fan_profiles(user_id,fan_code) VALUES(?,?)',(user_id,'FAN-'+datetime.utcnow().strftime('%Y')+'-'+str(user_id).zfill(6)))
    conn.execute('UPDATE fan_profiles SET points=points+? WHERE user_id=?',(amount,user_id)); log_event(user_id,reason,entity_type,entity_id,{'points':amount})
    score=conn.execute('SELECT COUNT(*) FROM interactions WHERE user_id=?',(user_id,)).fetchone()[0]
    segment='Super Fan' if score>=20 else 'Engaged Fan' if score>=8 else 'Casual Fan'
    conn.execute('UPDATE fan_profiles SET engagement_score=MIN(100,?), segment=? WHERE user_id=?',(min(100,score*5),segment,user_id)); conn.commit()
def is_adminish():
    u=current_user(); return bool(u and u['role'] in ('admin','ip_owner','partner','event_organizer','community_manager'))
def safe_int(v, default=0):
    try: return int(v)
    except (TypeError,ValueError): return default

@app.route('/')
def index():
    conn=db(); ips=conn.execute('SELECT i.*, (SELECT COUNT(*) FROM products p WHERE p.ip_id=i.id) product_count FROM ips i WHERE active=1 ORDER BY id DESC').fetchall()
    products=conn.execute('SELECT p.*,i.name ip_name FROM products p LEFT JOIN ips i ON i.id=p.ip_id WHERE p.authorized=1 ORDER BY p.id DESC LIMIT 6').fetchall()
    events=conn.execute('SELECT e.*,i.name ip_name FROM events e LEFT JOIN ips i ON i.id=e.ip_id WHERE e.active=1 ORDER BY e.event_date LIMIT 3').fetchall()
    communities=conn.execute('SELECT c.*,i.name ip_name,(SELECT COUNT(*) FROM community_members m WHERE m.community_id=c.id) members FROM communities c ORDER BY c.id DESC LIMIT 3').fetchall()
    return render_template('home.html',ips=ips,products=products,events=events,communities=communities)
@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); pw=request.form.get('password',''); city=request.form.get('city','').strip(); country=request.form.get('country','Egypt').strip(); favorite=safe_int(request.form.get('favorite_ip_id'))
        if not name or not email or len(pw)<8: flash('Enter your name, valid email, and a password of at least 8 characters.','danger')
        elif db().execute('SELECT id FROM users WHERE email=?',(email,)).fetchone(): flash('This email is already registered.','danger')
        else:
            c=db(); uid=c.execute('INSERT INTO users(name,email,password_hash,role,city,country,consent_analytics,consent_marketing,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(name,email,generate_password_hash(pw),'fan',city,country,int(bool(request.form.get('consent_analytics'))),int(bool(request.form.get('consent_marketing'))),now())).lastrowid
            code='FAN-'+datetime.utcnow().strftime('%Y')+'-'+str(uid).zfill(6)
            c.execute('INSERT INTO fan_profiles(user_id,fan_code,favorite_ip_id,favorite_character,genres,engagement_score,segment,points) VALUES(?,?,?,?,?,?,?,?)',(uid,code,favorite or None,request.form.get('favorite_character','').strip(),request.form.get('genres','').strip(),0,'Casual Fan',0))
            for typ,field in [('analytics','consent_analytics'),('marketing','consent_marketing')]: c.execute('INSERT INTO consent_records(user_id,consent_type,granted,recorded_at) VALUES(?,?,?,?)',(uid,typ,int(bool(request.form.get(field))),now()))
            c.commit(); session['user_id']=uid; log_event(uid,'FAN_REGISTERED','user',uid); flash('Welcome! Your digital Fan ID is ready.','success'); return redirect(url_for('dashboard'))
    return render_template('register.html',ips=db().execute('SELECT * FROM ips WHERE active=1').fetchall())
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=db().execute('SELECT * FROM users WHERE email=?',(request.form.get('email','').strip().lower(),)).fetchone()
        if u and check_password_hash(u['password_hash'],request.form.get('password','')):
            session.clear(); session['user_id']=u['id']; flash('Welcome back.','success'); return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Invalid email or password.','danger')
    return render_template('login.html')
@app.route('/logout')
def logout(): session.clear(); flash('You have been signed out.','info'); return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    u=current_user(); c=db()
    if u['role']=='fan':
        profile=c.execute('SELECT fp.*,i.name favorite_ip FROM fan_profiles fp LEFT JOIN ips i ON i.id=fp.favorite_ip_id WHERE fp.user_id=?',(u['id'],)).fetchone()
        scans=c.execute('SELECT s.*,p.name product_name,p.product_code FROM product_scans s JOIN products p ON p.id=s.product_id WHERE s.user_id=? ORDER BY s.id DESC LIMIT 8',(u['id'],)).fetchall()
        regs=c.execute('SELECT er.*,e.name event_name,e.event_date,e.location FROM event_registrations er JOIN events e ON e.id=er.event_id WHERE er.user_id=? ORDER BY er.id DESC',(u['id'],)).fetchall()
        redemptions=c.execute('SELECT rr.*,r.name reward_name FROM reward_redemptions rr JOIN rewards r ON r.id=rr.reward_id WHERE rr.user_id=? ORDER BY rr.id DESC',(u['id'],)).fetchall()
        return render_template('fan_dashboard.html',u=u,profile=profile,scans=scans,regs=regs,redemptions=redemptions,events=c.execute('SELECT * FROM events WHERE active=1 ORDER BY event_date LIMIT 4').fetchall(),rewards=c.execute('SELECT * FROM rewards WHERE active=1 ORDER BY points_cost').fetchall())
    stats={'fans':c.execute("SELECT COUNT(*) FROM users WHERE role='fan'").fetchone()[0],'ips':c.execute('SELECT COUNT(*) FROM ips').fetchone()[0],'products':c.execute('SELECT COUNT(*) FROM products').fetchone()[0],'scans':c.execute('SELECT COUNT(*) FROM product_scans').fetchone()[0],'events':c.execute('SELECT COUNT(*) FROM events').fetchone()[0],'communities':c.execute('SELECT COUNT(*) FROM communities').fetchone()[0],'registrations':c.execute('SELECT COUNT(*) FROM registered_products').fetchone()[0],'suspicious':c.execute("SELECT COUNT(*) FROM product_scans WHERE status='suspicious'").fetchone()[0]}
    recent=c.execute('SELECT i.*,u.name user_name FROM interactions i LEFT JOIN users u ON u.id=i.user_id ORDER BY i.id DESC LIMIT 12').fetchall()
    city_rows=c.execute("SELECT city,COUNT(*) total FROM users WHERE role='fan' AND city<>'' GROUP BY city ORDER BY total DESC LIMIT 6").fetchall()
    top_ips=c.execute('SELECT i.name,COUNT(DISTINCT fp.user_id) fans FROM ips i LEFT JOIN fan_profiles fp ON fp.favorite_ip_id=i.id GROUP BY i.id ORDER BY fans DESC LIMIT 5').fetchall()
    return render_template('admin_dashboard.html',stats=stats,recent=recent,city_rows=city_rows,top_ips=top_ips)

@app.route('/explore')
def explore():
    c=db(); return render_template('explore.html',ips=c.execute('SELECT * FROM ips WHERE active=1').fetchall(),products=c.execute('SELECT p.*,i.name ip_name FROM products p LEFT JOIN ips i ON i.id=p.ip_id WHERE p.authorized=1 ORDER BY p.id DESC').fetchall(),events=c.execute('SELECT e.*,i.name ip_name FROM events e LEFT JOIN ips i ON i.id=e.ip_id WHERE e.active=1 ORDER BY e.event_date').fetchall(),communities=c.execute('SELECT c.*,i.name ip_name FROM communities c LEFT JOIN ips i ON i.id=c.ip_id').fetchall(),content=c.execute('SELECT co.*,i.name ip_name FROM content co LEFT JOIN ips i ON i.id=co.ip_id WHERE co.active=1 ORDER BY co.id DESC').fetchall())
@app.route('/ip/<int:ip_id>/follow',methods=['POST'])
@login_required
def follow_ip(ip_id):
    c=db(); ip=c.execute('SELECT * FROM ips WHERE id=? AND active=1',(ip_id,)).fetchone()
    if not ip: abort(404)
    c.execute('UPDATE fan_profiles SET favorite_ip_id=? WHERE user_id=?',(ip_id,session['user_id'])); c.commit(); log_event(session['user_id'],'IP_FOLLOWED','ip',ip_id); flash('Your favorite IP was updated.','success'); return redirect(request.referrer or url_for('explore'))
@app.route('/product/<int:product_id>/qr.png')
def product_qr(product_id):
    import qrcode
    p=db().execute('SELECT id FROM products WHERE id=?',(product_id,)).fetchone()
    if not p: abort(404)
    target=request.url_root.rstrip('/')+url_for('scan_product',product_id=product_id)
    img=qrcode.make(target); buf=io.BytesIO(); img.save(buf,format='PNG'); buf.seek(0)
    return send_file(buf,mimetype='image/png',max_age=3600)

@app.route('/fan/<int:user_id>/qr.png')
@login_required
def fan_qr(user_id):
    import qrcode
    u=current_user()
    if u['id'] != user_id and u['role'] != 'admin': abort(403)
    profile=db().execute('SELECT fan_code FROM fan_profiles WHERE user_id=?',(user_id,)).fetchone()
    if not profile: abort(404)
    target=request.url_root.rstrip('/')+url_for('dashboard')+'?fan_id='+profile['fan_code']
    img=qrcode.make(target); buf=io.BytesIO(); img.save(buf,format='PNG'); buf.seek(0)
    return send_file(buf,mimetype='image/png',max_age=3600)

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    p=db().execute('SELECT p.*,i.name ip_name FROM products p LEFT JOIN ips i ON i.id=p.ip_id WHERE p.id=?',(product_id,)).fetchone()
    if not p: abort(404)
    return render_template('product_detail.html',p=p)
@app.route('/product/<int:product_id>/scan',methods=['GET','POST'])
def scan_product(product_id):
    c=db(); p=c.execute('SELECT p.*,i.name ip_name FROM products p LEFT JOIN ips i ON i.id=p.ip_id WHERE p.id=?',(product_id,)).fetchone()
    if not p: abort(404)
    uid=session.get('user_id'); scans=c.execute('SELECT COUNT(*) FROM product_scans WHERE product_id=?',(product_id,)).fetchone()[0]
    recent=c.execute('SELECT MAX(scanned_at) FROM product_scans WHERE product_id=?',(product_id,)).fetchone()[0]
    status='valid' if p['authorized'] else 'unauthorized'
    if scans >= 10: status='suspicious'
    city='';
    if uid:
        user=c.execute('SELECT city,consent_analytics FROM users WHERE id=?',(uid,)).fetchone()
        if user and user['consent_analytics']: city=user['city'] or ''
    c.execute('INSERT INTO product_scans(product_id,user_id,scanned_at,city,status,ip_address) VALUES(?,?,?,?,?,?)',(product_id,uid,now(),city,status,request.remote_addr or '')); c.commit()
    if uid: log_event(uid,'PRODUCT_SCANNED','product',product_id,{'status':status})
    if uid and status=='valid':
        if request.method=='POST' and request.form.get('register')=='yes':
            try:
                c.execute('INSERT INTO registered_products(product_id,user_id,registered_at) VALUES(?,?,?)',(product_id,uid,now())); c.commit(); award_points(uid,p['points'],'PRODUCT_REGISTERED','product',product_id); flash(f'Product registered successfully. +{p["points"]} points!','success')
            except sqlite3.IntegrityError: flash('This product is already registered to your account.','info')
            return redirect(url_for('dashboard'))
    return render_template('scan_result.html',p=p,status=status,scan_count=scans+1,first_scan=not bool(recent),logged_in=bool(uid))
@app.route('/event/<int:event_id>/register',methods=['POST'])
@login_required
def event_register(event_id):
    c=db(); e=c.execute('SELECT * FROM events WHERE id=? AND active=1',(event_id,)).fetchone()
    if not e: abort(404)
    if c.execute('SELECT COUNT(*) FROM event_registrations WHERE event_id=?',(event_id,)).fetchone()[0]>=e['capacity']: flash('This event is at capacity.','danger'); return redirect(request.referrer or url_for('explore'))
    ticket='EVT-'+secrets.token_hex(5).upper()
    try: c.execute('INSERT INTO event_registrations(event_id,user_id,ticket_code,registered_at) VALUES(?,?,?,?)',(event_id,session['user_id'],ticket,now())); c.commit(); log_event(session['user_id'],'EVENT_REGISTERED','event',event_id); flash('Event registration confirmed. Ticket: '+ticket,'success')
    except sqlite3.IntegrityError: flash('You are already registered for this event.','info')
    return redirect(url_for('dashboard'))
@app.route('/event/checkin/<ticket>',methods=['POST'])
@roles_required('admin','event_organizer')
def event_checkin(ticket):
    c=db(); row=c.execute('SELECT * FROM event_registrations WHERE ticket_code=?',(ticket,)).fetchone()
    if not row: flash('Ticket not found.','danger')
    elif row['checked_in']: flash('Ticket already checked in.','info')
    else: c.execute('UPDATE event_registrations SET checked_in=1,checked_in_at=? WHERE id=?',(now(),row['id'])); c.commit(); award_points(row['user_id'],20,'EVENT_CHECKED_IN','event',row['event_id']); flash('Check-in successful. +20 points awarded.','success')
    return redirect(url_for('manage',entity='events'))
@app.route('/community/<int:community_id>/join',methods=['POST'])
@login_required
def join_community(community_id):
    c=db(); com=c.execute('SELECT * FROM communities WHERE id=?',(community_id,)).fetchone()
    if not com: abort(404)
    try: c.execute('INSERT INTO community_members(community_id,user_id,joined_at) VALUES(?,?,?)',(community_id,session['user_id'],now())); c.commit(); log_event(session['user_id'],'COMMUNITY_JOINED','community',community_id); award_points(session['user_id'],10,'COMMUNITY_JOINED','community',community_id); flash('You joined the community. +10 points!','success')
    except sqlite3.IntegrityError: flash('You are already a member.','info')
    return redirect(request.referrer or url_for('explore'))
@app.route('/community/<int:community_id>/post',methods=['POST'])
@login_required
def create_post(community_id):
    body=request.form.get('body','').strip()
    if not body or len(body)>2000: flash('Post must be between 1 and 2000 characters.','danger')
    else: db().execute('INSERT INTO posts(community_id,user_id,body,created_at) VALUES(?,?,?,?)',(community_id,session['user_id'],body,now())); db().commit(); log_event(session['user_id'],'COMMUNITY_POSTED','community',community_id); flash('Your post was published.','success')
    return redirect(url_for('community_detail',community_id=community_id))
@app.route('/community/<int:community_id>')
def community_detail(community_id):
    c=db(); community=c.execute('SELECT c.*,i.name ip_name FROM communities c LEFT JOIN ips i ON i.id=c.ip_id WHERE c.id=?',(community_id,)).fetchone()
    if not community: abort(404)
    posts=c.execute('SELECT p.*,u.name author FROM posts p JOIN users u ON u.id=p.user_id WHERE p.community_id=? AND p.status="published" ORDER BY p.id DESC',(community_id,)).fetchall()
    return render_template('community.html',community=community,posts=posts)
@app.route('/rewards/<int:reward_id>/redeem',methods=['POST'])
@login_required
def redeem_reward(reward_id):
    c=db(); reward=c.execute('SELECT * FROM rewards WHERE id=? AND active=1',(reward_id,)).fetchone(); profile=c.execute('SELECT points FROM fan_profiles WHERE user_id=?',(session['user_id'],)).fetchone()
    if not reward: abort(404)
    if not profile or profile['points']<reward['points_cost']: flash('Not enough points for this reward.','danger')
    else:
        code='RWD-'+secrets.token_hex(5).upper()
        c.execute('UPDATE fan_profiles SET points=points-? WHERE user_id=?',(reward['points_cost'],session['user_id'])); c.execute('INSERT INTO reward_redemptions(reward_id,user_id,points_spent,code,redeemed_at) VALUES(?,?,?,?,?)',(reward_id,session['user_id'],reward['points_cost'],code,now())); c.commit(); log_event(session['user_id'],'REWARD_REDEEMED','reward',reward_id); flash('Reward redeemed. Code: '+code,'success')
    return redirect(url_for('dashboard'))

ENTITY_CONFIG={
 'ips':{'title':'IP Catalogue','table':'ips','fields':[('name','IP / Anime Title','text'),('description','Description','textarea'),('owner','Rights Owner','text'),('image_url','Image URL','url'),('active','Active','checkbox')],'admin':['admin','ip_owner'],'columns':['name','owner','active']},
 'characters':{'title':'Characters','table':'characters','fields':[('ip_id','IP','select_ips'),('name','Character Name','text'),('description','Description','textarea')],'admin':['admin','ip_owner'],'columns':['name','ip_id','description']},
 'products':{'title':'Product Traceability','table':'products','fields':[('product_code','Unique Product ID','text'),('name','Product Name','text'),('ip_id','IP','select_ips'),('product_type','Product Type','text'),('manufacturer','Manufacturer','text'),('distributor','Distributor','text'),('retailer','Retailer','text'),('batch','Batch','text'),('authorized','Authorized','checkbox'),('description','Description','textarea'),('points','Registration Points','number')],'admin':['admin','ip_owner','partner'],'columns':['product_code','name','ip_id','authorized']},
 'events':{'title':'Events & Check-in','table':'events','fields':[('name','Event Name','text'),('ip_id','IP','select_ips'),('location','Location','text'),('event_date','Date','date'),('event_time','Time','time'),('capacity','Capacity','number'),('description','Description','textarea'),('organizer','Organizer','text'),('active','Active','checkbox')],'admin':['admin','ip_owner','event_organizer'],'columns':['name','location','event_date','capacity','active']},
 'communities':{'title':'Fan Communities','table':'communities','fields':[('name','Community Name','text'),('ip_id','IP','select_ips'),('description','Description','textarea'),('city','City','text')],'admin':['admin','ip_owner','community_manager'],'columns':['name','ip_id','city']},
 'campaigns':{'title':'Campaign Management','table':'campaigns','fields':[('name','Campaign Name','text'),('ip_id','IP','select_ips'),('description','Description','textarea'),('start_date','Start Date','date'),('end_date','End Date','date'),('active','Active','checkbox'),('reward_points','Completion Points','number')],'admin':['admin','ip_owner'],'columns':['name','start_date','end_date','active','reward_points']},
 'rewards':{'title':'Loyalty & Rewards','table':'rewards','fields':[('name','Reward Name','text'),('description','Description','textarea'),('points_cost','Points Cost','number'),('reward_type','Reward Type','text'),('active','Active','checkbox')],'admin':['admin','ip_owner'],'columns':['name','reward_type','points_cost','active']},
 'content':{'title':'Official Content Hub','table':'content','fields':[('title','Content Title','text'),('content_type','Content Type','text'),('url','URL','url'),('description','Description','textarea'),('ip_id','IP','select_ips'),('active','Active','checkbox')],'admin':['admin','ip_owner'],'columns':['title','content_type','ip_id','active']},
 'partners':{'title':'Partner Directory','table':'partners','fields':[('name','Partner Name','text'),('partner_type','Partner Type','text'),('email','Email','email'),('city','City','text'),('status','Status','text')],'admin':['admin','ip_owner'],'columns':['name','partner_type','email','city','status']},
 'notifications':{'title':'Notifications','table':'notifications','fields':[('title','Notification Title','text'),('body','Message','textarea'),('target_segment','Target Segment','text'),('ip_id','IP (optional)','select_ips')],'admin':['admin','ip_owner'],'columns':['title','target_segment','ip_id','created_at']},
}
@app.route('/manage/<entity>',methods=['GET','POST'])
@login_required
def manage(entity):
    cfg=ENTITY_CONFIG.get(entity)
    if not cfg: abort(404)
    u=current_user()
    if u['role'] not in cfg['admin']: abort(403)
    c=db(); edit_id=safe_int(request.args.get('edit'))
    if request.method=='POST':
        action=request.form.get('action','save')
        if action=='delete':
            rid=safe_int(request.form.get('id')); c.execute(f'DELETE FROM {cfg["table"]} WHERE id=?',(rid,)); c.commit(); flash('Record deleted.','success'); return redirect(url_for('manage',entity=entity))
        vals=[]; cols=[]
        for key,label,typ in cfg['fields']:
            if key in ('created_at',): continue
            if typ=='checkbox': val=1 if request.form.get(key) else 0
            elif typ=='number' or typ=='select_ips': val=safe_int(request.form.get(key)) or None if typ=='select_ips' else safe_int(request.form.get(key),0)
            else: val=request.form.get(key,'').strip()
            cols.append(key); vals.append(val)
        rid=safe_int(request.form.get('id'))
        try:
            if rid:
                c.execute(f'UPDATE {cfg["table"]} SET '+','.join(k+'=?' for k in cols)+' WHERE id=?',vals+[rid]); flash('Record updated.','success')
            else:
                if 'created_at' in [r[1] for r in c.execute(f'PRAGMA table_info({cfg["table"]})').fetchall()]: cols.append('created_at'); vals.append(now())
                c.execute(f'INSERT INTO {cfg["table"]} ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',vals); flash('Record created successfully.','success')
            c.commit()
        except sqlite3.IntegrityError as ex: c.rollback(); flash('Could not save record. Check unique IDs and required fields. '+str(ex),'danger')
        return redirect(url_for('manage',entity=entity))
    rows=c.execute(f'SELECT * FROM {cfg["table"]} ORDER BY id DESC').fetchall()
    record=c.execute(f'SELECT * FROM {cfg["table"]} WHERE id=?',(edit_id,)).fetchone() if edit_id else None
    ips=c.execute('SELECT id,name FROM ips ORDER BY name').fetchall()
    # Decorate common foreign keys for readable tables.
    display=[]
    for row in rows:
        d=dict(row)
        if 'ip_id' in d and d['ip_id']: d['ip_name']= (c.execute('SELECT name FROM ips WHERE id=?',(d['ip_id'],)).fetchone() or {'name':'—'})['name']
        display.append(d)
    return render_template('manage.html',entity=entity,cfg=cfg,rows=display,record=record,ips=ips)

@app.route('/manage/fans')
@login_required
@roles_required('admin','ip_owner','community_manager')
def manage_fans():
    q=request.args.get('q','').strip(); c=db(); sql='SELECT u.*,fp.fan_code,fp.points,fp.segment,fp.engagement_score, i.name favorite_ip FROM users u LEFT JOIN fan_profiles fp ON fp.user_id=u.id LEFT JOIN ips i ON i.id=fp.favorite_ip_id WHERE u.role="fan"'; args=[]
    if q: sql+=' AND (u.name LIKE ? OR u.email LIKE ? OR fp.fan_code LIKE ? OR u.city LIKE ?)'; args=[f'%{q}%']*4
    fans=c.execute(sql+' ORDER BY u.id DESC',args).fetchall()
    return render_template('fans.html',fans=fans,q=q)
@app.route('/manage/fans/<int:uid>/delete',methods=['POST'])
@login_required
@roles_required('admin')
def delete_fan(uid):
    if uid==session['user_id']: flash('You cannot delete your own active account.','danger')
    else: db().execute('DELETE FROM users WHERE id=? AND role="fan"',(uid,)); db().commit(); flash('Fan account deleted.','success')
    return redirect(url_for('manage_fans'))
@app.route('/analytics')
@login_required
@roles_required('admin','ip_owner','partner','event_organizer','community_manager')
def analytics():
    c=db(); daily=c.execute("SELECT substr(created_at,1,10) day,COUNT(*) total FROM interactions GROUP BY day ORDER BY day DESC LIMIT 14").fetchall()
    events=c.execute('SELECT e.name,COUNT(er.id) registrations,SUM(CASE WHEN er.checked_in=1 THEN 1 ELSE 0 END) checkins FROM events e LEFT JOIN event_registrations er ON er.event_id=e.id GROUP BY e.id ORDER BY registrations DESC').fetchall()
    products=c.execute('SELECT p.name,p.product_code,COUNT(s.id) scans,COUNT(rp.id) registrations,SUM(CASE WHEN s.status="suspicious" THEN 1 ELSE 0 END) suspicious FROM products p LEFT JOIN product_scans s ON s.product_id=p.id LEFT JOIN registered_products rp ON rp.product_id=p.id GROUP BY p.id ORDER BY scans DESC').fetchall()
    segments=c.execute('SELECT segment,COUNT(*) total FROM fan_profiles GROUP BY segment ORDER BY total DESC').fetchall()
    funnel=[('Registered Fans',c.execute("SELECT COUNT(*) FROM users WHERE role='fan'").fetchone()[0]),('Product Scans',c.execute('SELECT COUNT(*) FROM product_scans').fetchone()[0]),('Registered Products',c.execute('SELECT COUNT(*) FROM registered_products').fetchone()[0]),('Event Registrations',c.execute('SELECT COUNT(*) FROM event_registrations').fetchone()[0]),('Community Members',c.execute('SELECT COUNT(*) FROM community_members').fetchone()[0])]
    return render_template('analytics.html',daily=daily,events=events,products=products,segments=segments,funnel=funnel)
@app.route('/reports/export.csv')
@login_required
@roles_required('admin','ip_owner','partner')
def export_csv():
    import csv
    c=db(); out=io.StringIO(); w=csv.writer(out); w.writerow(['Fan ID','Name','Email','City','Country','Favorite IP','Points','Segment','Engagement Score','Created At'])
    for r in c.execute('SELECT fp.fan_code,u.name,u.email,u.city,u.country,i.name,fp.points,fp.segment,fp.engagement_score,u.created_at FROM users u JOIN fan_profiles fp ON fp.user_id=u.id LEFT JOIN ips i ON i.id=fp.favorite_ip_id WHERE u.role="fan" ORDER BY u.id'): w.writerow(list(r))
    data=io.BytesIO(out.getvalue().encode('utf-8-sig')); data.seek(0); return send_file(data,mimetype='text/csv',as_attachment=True,download_name='fan-intelligence-report.csv')
@app.route('/settings',methods=['GET','POST'])
@login_required
def settings():
    u=current_user()
    if request.method=='POST':
        name=request.form.get('name','').strip(); city=request.form.get('city','').strip(); country=request.form.get('country','Egypt').strip(); ca=int(bool(request.form.get('consent_analytics'))); cm=int(bool(request.form.get('consent_marketing')))
        c=db(); c.execute('UPDATE users SET name=?,city=?,country=?,consent_analytics=?,consent_marketing=? WHERE id=?',(name,city,country,ca,cm,u['id']))
        c.execute('INSERT INTO consent_records(user_id,consent_type,granted,recorded_at) VALUES(?,?,?,?)',(u['id'],'analytics',ca,now())); c.execute('INSERT INTO consent_records(user_id,consent_type,granted,recorded_at) VALUES(?,?,?,?)',(u['id'],'marketing',cm,now())); c.commit(); flash('Profile and privacy preferences updated.','success'); return redirect(url_for('settings'))
    return render_template('settings.html',u=u)
@app.errorhandler(403)
def forbidden(e): return render_template('error.html',code=403,message='You do not have permission to access this area.'),403
@app.errorhandler(404)
def not_found(e): return render_template('error.html',code=404,message='The page or record could not be found.'),404

if __name__=='__main__':
    init_db()
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=os.environ.get('FLASK_DEBUG')=='1')
