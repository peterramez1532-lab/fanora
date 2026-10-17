
import os
import io
import csv
import json
import secrets
from datetime import datetime, timedelta
from functools import wraps

import psycopg
from psycopg.rows import dict_row
from psycopg.errors import IntegrityError
from flask import (
    Flask, g, request, redirect, url_for, session,
    flash, render_template, abort, send_file
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")

if not app.secret_key:
    raise RuntimeError("SECRET_KEY must be configured in environment variables")


# =========================================================
# DATABASE
# =========================================================

def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def connect_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=10,
    )


class DBConnection:
    """Compatibility layer for SQL queries using ? placeholders."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        return self.connection.execute(sql.replace("?", "%s"), params)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def db():
    if "db" not in g:
        g.db = DBConnection(connect_db())
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


# =========================================================
# POSTGRESQL SCHEMA
# =========================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'fan',
    city TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT 'Egypt',
    consent_analytics INTEGER NOT NULL DEFAULT 0,
    consent_marketing INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ips (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fan_profiles (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    fan_code TEXT NOT NULL UNIQUE,
    favorite_ip_id BIGINT REFERENCES ips(id) ON DELETE SET NULL,
    favorite_character TEXT NOT NULL DEFAULT '',
    genres TEXT NOT NULL DEFAULT '',
    engagement_score INTEGER NOT NULL DEFAULT 0,
    segment TEXT NOT NULL DEFAULT 'Casual Fan',
    points INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS characters (
    id BIGSERIAL PRIMARY KEY,
    ip_id BIGINT REFERENCES ips(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    product_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    ip_id BIGINT REFERENCES ips(id) ON DELETE SET NULL,
    product_type TEXT NOT NULL DEFAULT '',
    manufacturer TEXT NOT NULL DEFAULT '',
    distributor TEXT NOT NULL DEFAULT '',
    retailer TEXT NOT NULL DEFAULT '',
    batch TEXT NOT NULL DEFAULT '',
    authorized INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL DEFAULT '',
    points INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_scans (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    scanned_at TEXT NOT NULL,
    city TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'valid',
    ip_address TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS registered_products (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    registered_at TEXT NOT NULL,
    UNIQUE(product_id, user_id)
);

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    ip_id BIGINT REFERENCES ips(id) ON DELETE SET NULL,
    location TEXT NOT NULL DEFAULT '',
    event_date TEXT NOT NULL DEFAULT '',
    event_time TEXT NOT NULL DEFAULT '',
    capacity INTEGER NOT NULL DEFAULT 100,
    description TEXT NOT NULL DEFAULT '',
    organizer TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_registrations (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticket_code TEXT NOT NULL UNIQUE,
    registered_at TEXT NOT NULL,
    checked_in INTEGER NOT NULL DEFAULT 0,
    checked_in_at TEXT,
    UNIQUE(event_id, user_id)
);

CREATE TABLE IF NOT EXISTS communities (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    ip_id BIGINT REFERENCES ips(id) ON DELETE SET NULL,
    description TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS community_members (
    id BIGSERIAL PRIMARY KEY,
    community_id BIGINT NOT NULL REFERENCES communities(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    joined_at TEXT NOT NULL,
    UNIQUE(community_id, user_id)
);

CREATE TABLE IF NOT EXISTS posts (
    id BIGSERIAL PRIMARY KEY,
    community_id BIGINT NOT NULL REFERENCES communities(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'published',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaigns (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    ip_id BIGINT REFERENCES ips(id) ON DELETE SET NULL,
    description TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL DEFAULT '',
    end_date TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    reward_points INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaign_actions (
    id BIGSERIAL PRIMARY KEY,
    campaign_id BIGINT REFERENCES campaigns(id) ON DELETE CASCADE,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS rewards (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    points_cost INTEGER NOT NULL DEFAULT 0,
    reward_type TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reward_redemptions (
    id BIGSERIAL PRIMARY KEY,
    reward_id BIGINT NOT NULL REFERENCES rewards(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    points_spent INTEGER NOT NULL DEFAULT 0,
    code TEXT NOT NULL UNIQUE,
    redeemed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    ip_id BIGINT REFERENCES ips(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS interactions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id BIGINT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    target_segment TEXT NOT NULL DEFAULT '',
    ip_id BIGINT REFERENCES ips(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS consent_records (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    consent_type TEXT NOT NULL,
    granted INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS partners (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    partner_type TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scans_product ON product_scans(product_id);
CREATE INDEX IF NOT EXISTS idx_scans_user ON product_scans(user_id);
CREATE INDEX IF NOT EXISTS idx_interactions_user ON interactions(user_id);
CREATE INDEX IF NOT EXISTS idx_registrations_event ON event_registrations(event_id);
"""


def init_db():
    # Execute statements individually for compatibility with psycopg.
    with connect_db() as connection:
        for statement in SCHEMA.split(";"):
            statement = statement.strip()
            if statement:
                connection.execute(statement)

        existing = connection.execute(
            "SELECT COUNT(*) AS total FROM users"
        ).fetchone()["total"]

        if existing:
            return

        timestamp = now()
        demo_users = [
            ("Platform Admin", "admin@fanintel.demo", "Admin123!", "admin", "Cairo"),
            ("IP Owner", "owner@fanintel.demo", "Owner123!", "ip_owner", "Cairo"),
            ("Retail Partner", "partner@fanintel.demo", "Partner123!", "partner", "Giza"),
            ("Community Manager", "community@fanintel.demo", "Community123!", "community_manager", "Alexandria"),
            ("Demo Fan", "fan@fanintel.demo", "Fan123!", "fan", "Cairo"),
        ]

        ids = {}
        for name, email, password, role, city in demo_users:
            user_id = connection.execute(
                """
                INSERT INTO users
                (name,email,password_hash,role,city,country,
                 consent_analytics,consent_marketing,created_at)
                VALUES (%s,%s,%s,%s,%s,'Egypt',1,1,%s)
                RETURNING id
                """,
                (
                    name, email, generate_password_hash(password),
                    role, city, timestamp
                ),
            ).fetchone()["id"]

            ids[role] = user_id

            if role == "fan":
                connection.execute(
                    """
                    INSERT INTO fan_profiles
                    (user_id,fan_code,favorite_character,genres,
                     engagement_score,segment,points)
                    VALUES (%s,%s,'Luffy','Adventure,Anime',87,'Super Fan',2450)
                    """,
                    (user_id, f"FAN-2026-{user_id:06d}"),
                )

        ip1 = connection.execute(
            """
            INSERT INTO ips(name,description,owner,created_at)
            VALUES (%s,%s,%s,%s) RETURNING id
            """,
            (
                "One Piece",
                "Demo record. Replace with authorized IP information.",
                "Demo Media Company",
                timestamp,
            ),
        ).fetchone()["id"]

        ip2 = connection.execute(
            """
            INSERT INTO ips(name,description,owner,created_at)
            VALUES (%s,%s,%s,%s) RETURNING id
            """,
            (
                "Demon Slayer",
                "Sample IP record for testing.",
                "Demo Media Company",
                timestamp,
            ),
        ).fetchone()["id"]

        connection.execute(
            "UPDATE fan_profiles SET favorite_ip_id=%s WHERE user_id=%s",
            (ip1, ids["fan"]),
        )

        connection.execute(
            "INSERT INTO characters(ip_id,name,description,created_at) VALUES (%s,%s,%s,%s)",
            (ip1, "Monkey D. Luffy", "Sample character", timestamp),
        )

        connection.execute(
            """
            INSERT INTO products
            (product_code,name,ip_id,product_type,manufacturer,distributor,
             retailer,batch,authorized,description,points,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s)
            """,
            (
                "PROD-ONEPIECE-00092832", "Luffy Figure", ip1, "Figure",
                "Demo Manufacturer", "Demo Distributor", "Demo Store",
                "BATCH-001", "Sample authorized product.", 30, timestamp,
            ),
        )

        connection.execute(
            """
            INSERT INTO products
            (product_code,name,ip_id,product_type,manufacturer,distributor,
             retailer,batch,authorized,description,points,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s)
            """,
            (
                "PROD-DS-000002", "Tanjiro Keychain", ip2, "Accessory",
                "Demo Manufacturer", "Demo Distributor", "Demo Store",
                "BATCH-002", "Sample product.", 25, timestamp,
            ),
        )

        connection.execute(
            """
            INSERT INTO events
            (name,ip_id,location,event_date,event_time,capacity,
             description,organizer,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                "Egypt Anime Fan Meetup", ip1, "Cairo, Egypt",
                (datetime.utcnow() + timedelta(days=14)).date().isoformat(),
                "16:00", 250, "Demo event.", "Demo Organizer", timestamp,
            ),
        )

        connection.execute(
            """
            INSERT INTO communities(name,ip_id,description,city,created_at)
            VALUES (%s,%s,%s,%s,%s)
            """,
            ( "One Piece Egypt Community", ip1, "Sample fan community.", "Cairo", timestamp ),
        )

        connection.execute(
            """
            INSERT INTO campaigns
            (name,ip_id,description,start_date,end_date,active,reward_points,created_at)
            VALUES (%s,%s,%s,%s,%s,1,%s,%s)
            """,
            (
                "Become an Official One Piece Fan", ip1,
                "Register, scan an official product and join a community.",
                datetime.utcnow().date().isoformat(),
                (datetime.utcnow() + timedelta(days=60)).date().isoformat(),
                100, timestamp,
            ),
        )

        connection.execute(
            """
            INSERT INTO rewards(name,description,points_cost,reward_type,active,created_at)
            VALUES (%s,%s,%s,%s,1,%s)
            """,
            ("Exclusive Digital Badge", "A digital badge for your fan profile.", 200, "Exclusive Badge", timestamp),
        )

        connection.execute(
            """
            INSERT INTO rewards(name,description,points_cost,reward_type,active,created_at)
            VALUES (%s,%s,%s,%s,1,%s)
            """,
            ("Official Content Access", "Sample reward redemption.", 500, "Digital Content", timestamp),
        )

        connection.execute(
            """
            INSERT INTO content(title,content_type,url,description,ip_id,created_at,active)
            VALUES (%s,%s,%s,%s,%s,%s,1)
            """,
            (
                "One Piece Official Trailer", "Video", "https://www.youtube.com/",
                "Demo content. Replace with a verified official link.", ip1, timestamp,
            ),
        )

        connection.execute(
            """
            INSERT INTO partners(name,partner_type,email,city,status,created_at)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            ("Demo Authorized Store", "Retailer", "store@example.demo", "Cairo", "active", timestamp),
        )


# =========================================================
# AUTHENTICATION AND SHARED HELPERS
# =========================================================

def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "role_labels": {
            "admin": "Platform Admin",
            "ip_owner": "IP Owner",
            "partner": "Distributor / Retailer",
            "event_organizer": "Event Organizer",
            "community_manager": "Community Manager",
            "fan": "Fan / Customer",
        },
        "year": datetime.utcnow().year,
    }


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return function(*args, **kwargs)
    return wrapper


def roles_required(*roles):
    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                return redirect(url_for("login", next=request.path))
            if user["role"] not in roles:
                abort(403)
            return function(*args, **kwargs)
        return wrapper
    return decorator


def log_event(user_id, event_type, entity_type="", entity_id=None, metadata=None):
    connection = db()
    connection.execute(
        """
        INSERT INTO interactions
        (user_id,event_type,entity_type,entity_id,metadata,created_at)
        VALUES (?,?,?,?,?,?)
        """,
        (
            user_id, event_type, entity_type, entity_id,
            json.dumps(metadata or {}), now()
        ),
    )
    connection.commit()


def award_points(user_id, amount, reason, entity_type="", entity_id=None):
    if not user_id or amount <= 0:
        return

    connection = db()
    code = f"FAN-{datetime.utcnow().year}-{user_id:06d}"

    connection.execute(
        """
        INSERT INTO fan_profiles(user_id,fan_code)
        VALUES (?,?)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (user_id, code),
    )

    connection.execute(
        "UPDATE fan_profiles SET points=points+? WHERE user_id=?",
        (amount, user_id),
    )

    log_event(user_id, reason, entity_type, entity_id, {"points": amount})

    score = connection.execute(
        "SELECT COUNT(*) AS total FROM interactions WHERE user_id=?",
        (user_id,),
    ).fetchone()["total"]

    segment = (
        "Super Fan" if score >= 20
        else "Engaged Fan" if score >= 8
        else "Casual Fan"
    )

    connection.execute(
        "UPDATE fan_profiles SET engagement_score=?,segment=? WHERE user_id=?",
        (min(100, score * 5), segment, user_id),
    )
    connection.commit()


# =========================================================
# HOME, REGISTRATION, LOGIN
# =========================================================

@app.route("/")
def index():
    connection = db()

    ips = connection.execute(
        """
        SELECT i.*,
        (SELECT COUNT(*) FROM products p WHERE p.ip_id=i.id) product_count
        FROM ips i WHERE active=1 ORDER BY id DESC
        """
    ).fetchall()

    products = connection.execute(
        """
        SELECT p.*,i.name ip_name
        FROM products p LEFT JOIN ips i ON i.id=p.ip_id
        WHERE p.authorized=1 ORDER BY p.id DESC LIMIT 6
        """
    ).fetchall()

    events = connection.execute(
        """
        SELECT e.*,i.name ip_name
        FROM events e LEFT JOIN ips i ON i.id=e.ip_id
        WHERE e.active=1 ORDER BY e.event_date LIMIT 3
        """
    ).fetchall()

    communities = connection.execute(
        """
        SELECT c.*,
            i.name AS ip_name,
            (SELECT COUNT(*)
                FROM community_members m
                WHERE m.community_id = c.id) AS members
        FROM communities c
        LEFT JOIN ips i ON i.id = c.ip_id
        ORDER BY c.id DESC
        LIMIT 3
        """
    ).fetchall()

    return render_template(
        "home.html", ips=ips, products=products,
        events=events, communities=communities
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        city = request.form.get("city", "").strip()
        country = request.form.get("country", "Egypt").strip() or "Egypt"
        favorite_ip = safe_int(request.form.get("favorite_ip_id"))

        if not name or not email or len(password) < 8:
            flash("Enter your name, email, and a password of at least 8 characters.", "danger")
        elif db().execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            flash("This email is already registered.", "danger")
        else:
            connection = db()
            try:
                user_id = connection.execute(
                    """
                    INSERT INTO users
                    (name,email,password_hash,role,city,country,
                     consent_analytics,consent_marketing,created_at)
                    VALUES (?,?,?,'fan',?,?,?,?,?)
                    RETURNING id
                    """,
                    (
                        name, email, generate_password_hash(password), city, country,
                        int(bool(request.form.get("consent_analytics"))),
                        int(bool(request.form.get("consent_marketing"))), now(),
                    ),
                ).fetchone()["id"]

                fan_code = f"FAN-{datetime.utcnow().year}-{user_id:06d}"

                connection.execute(
                    """
                    INSERT INTO fan_profiles
                    (user_id,fan_code,favorite_ip_id,favorite_character,
                     genres,engagement_score,segment,points)
                    VALUES (?,?,?,?,?,0,'Casual Fan',0)
                    """,
                    (
                        user_id, fan_code, favorite_ip or None,
                        request.form.get("favorite_character", "").strip(),
                        request.form.get("genres", "").strip(),
                    ),
                )

                for consent_type, field in [
                    ("analytics", "consent_analytics"),
                    ("marketing", "consent_marketing"),
                ]:
                    connection.execute(
                        """
                        INSERT INTO consent_records
                        (user_id,consent_type,granted,recorded_at)
                        VALUES (?,?,?,?)
                        """,
                        (
                            user_id, consent_type,
                            int(bool(request.form.get(field))), now()
                        ),
                    )

                connection.commit()
                session["user_id"] = user_id
                log_event(user_id, "FAN_REGISTERED", "user", user_id)
                flash("Welcome! Your digital Fan ID is ready.", "success")
                return redirect(url_for("dashboard"))

            except IntegrityError:
                connection.rollback()
                flash("Could not create the account. Check the email and try again.", "danger")

    ips = db().execute("SELECT * FROM ips WHERE active=1").fetchall()
    return render_template("register.html", ips=ips)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = db().execute(
            "SELECT * FROM users WHERE email=?", (email,)
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash("Welcome back.", "success")
            return redirect(request.args.get("next") or url_for("dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("index"))


# =========================================================
# DASHBOARDS
# =========================================================

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    connection = db()

    if user["role"] == "fan":
        profile = connection.execute(
            """
            SELECT fp.*,i.name favorite_ip
            FROM fan_profiles fp LEFT JOIN ips i ON i.id=fp.favorite_ip_id
            WHERE fp.user_id=?
            """,
            (user["id"],),
        ).fetchone()

        scans = connection.execute(
            """
            SELECT s.*,p.name product_name,p.product_code
            FROM product_scans s JOIN products p ON p.id=s.product_id
            WHERE s.user_id=? ORDER BY s.id DESC LIMIT 8
            """,
            (user["id"],),
        ).fetchall()

        registrations = connection.execute(
            """
            SELECT er.*,e.name event_name,e.event_date,e.location
            FROM event_registrations er JOIN events e ON e.id=er.event_id
            WHERE er.user_id=? ORDER BY er.id DESC
            """,
            (user["id"],),
        ).fetchall()

        redemptions = connection.execute(
            """
            SELECT rr.*,r.name reward_name
            FROM reward_redemptions rr JOIN rewards r ON r.id=rr.reward_id
            WHERE rr.user_id=? ORDER BY rr.id DESC
            """,
            (user["id"],),
        ).fetchall()

        events = connection.execute(
            "SELECT * FROM events WHERE active=1 ORDER BY event_date LIMIT 4"
        ).fetchall()

        rewards = connection.execute(
            "SELECT * FROM rewards WHERE active=1 ORDER BY points_cost"
        ).fetchall()

        return render_template(
            "fan_dashboard.html", u=user, profile=profile,
            scans=scans, regs=registrations,
            redemptions=redemptions, events=events, rewards=rewards
        )

    stats = {
        "fans": connection.execute("SELECT COUNT(*) n FROM users WHERE role='fan'").fetchone()["n"],
        "ips": connection.execute("SELECT COUNT(*) n FROM ips").fetchone()["n"],
        "products": connection.execute("SELECT COUNT(*) n FROM products").fetchone()["n"],
        "scans": connection.execute("SELECT COUNT(*) n FROM product_scans").fetchone()["n"],
        "events": connection.execute("SELECT COUNT(*) n FROM events").fetchone()["n"],
        "communities": connection.execute("SELECT COUNT(*) n FROM communities").fetchone()["n"],
        "registrations": connection.execute("SELECT COUNT(*) n FROM registered_products").fetchone()["n"],
        "suspicious": connection.execute("SELECT COUNT(*) n FROM product_scans WHERE status='suspicious'").fetchone()["n"],
    }

    recent = connection.execute(
        """
        SELECT i.*,u.name user_name
        FROM interactions i LEFT JOIN users u ON u.id=i.user_id
        ORDER BY i.id DESC LIMIT 12
        """
    ).fetchall()

    city_rows = connection.execute(
        """
        SELECT city,COUNT(*) total FROM users
        WHERE role='fan' AND city<>''
        GROUP BY city ORDER BY total DESC LIMIT 6
        """
    ).fetchall()

    top_ips = connection.execute(
        """
        SELECT i.name,COUNT(DISTINCT fp.user_id) fans
        FROM ips i LEFT JOIN fan_profiles fp ON fp.favorite_ip_id=i.id
        GROUP BY i.id ORDER BY fans DESC LIMIT 5
        """
    ).fetchall()

    return render_template(
        "admin_dashboard.html",
        stats=stats, recent=recent, city_rows=city_rows, top_ips=top_ips
    )


@app.route("/explore")
def explore():
    connection = db()

    return render_template(
        "explore.html",
        ips=connection.execute("SELECT * FROM ips WHERE active=1").fetchall(),
        products=connection.execute(
            """
            SELECT p.*,i.name ip_name FROM products p
            LEFT JOIN ips i ON i.id=p.ip_id
            WHERE p.authorized=1 ORDER BY p.id DESC
            """
        ).fetchall(),
        events=connection.execute(
            """
            SELECT e.*,i.name ip_name FROM events e
            LEFT JOIN ips i ON i.id=e.ip_id
            WHERE e.active=1 ORDER BY e.event_date
            """
        ).fetchall(),
        communities=connection.execute(
            "SELECT c.*,i.name ip_name FROM communities c LEFT JOIN ips i ON i.id=c.ip_id"
        ).fetchall(),
        content=connection.execute(
            """
            SELECT co.*,i.name ip_name FROM content co
            LEFT JOIN ips i ON i.id=co.ip_id
            WHERE co.active=1 ORDER BY co.id DESC
            """
        ).fetchall(),
    )


@app.route("/ip/<int:ip_id>/follow", methods=["POST"])
@login_required
def follow_ip(ip_id):
    connection = db()
    ip = connection.execute(
        "SELECT * FROM ips WHERE id=? AND active=1", (ip_id,)
    ).fetchone()

    if not ip:
        abort(404)

    user_id = session["user_id"]
    code = f"FAN-{datetime.utcnow().year}-{user_id:06d}"

    connection.execute(
        """
        INSERT INTO fan_profiles(user_id,fan_code,favorite_ip_id)
        VALUES (?,?,?)
        ON CONFLICT (user_id) DO UPDATE
        SET favorite_ip_id=EXCLUDED.favorite_ip_id
        """,
        (user_id, code, ip_id),
    )
    connection.commit()

    log_event(user_id, "IP_FOLLOWED", "ip", ip_id)
    flash("Your favorite IP was updated.", "success")
    return redirect(request.referrer or url_for("explore"))


# =========================================================
# PRODUCT QR, PRODUCT DETAILS AND SCANNING
# =========================================================

@app.route("/product/<int:product_id>/qr.png")
def product_qr(product_id):
    import qrcode

    product = db().execute(
        "SELECT id FROM products WHERE id=?", (product_id,)
    ).fetchone()

    if not product:
        abort(404)

    target = request.url_root.rstrip("/") + url_for(
        "scan_product", product_id=product_id
    )
    image = qrcode.make(target)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    return send_file(buffer, mimetype="image/png", max_age=3600)


@app.route("/fan/<int:user_id>/qr.png")
@login_required
def fan_qr(user_id):
    import qrcode

    user = current_user()
    if user["id"] != user_id and user["role"] != "admin":
        abort(403)

    profile = db().execute(
        "SELECT fan_code FROM fan_profiles WHERE user_id=?", (user_id,)
    ).fetchone()

    if not profile:
        abort(404)

    target = (
        request.url_root.rstrip("/")
        + url_for("dashboard")
        + "?fan_id="
        + profile["fan_code"]
    )

    image = qrcode.make(target)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    return send_file(buffer, mimetype="image/png", max_age=3600)


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = db().execute(
        """
        SELECT p.*,i.name ip_name FROM products p
        LEFT JOIN ips i ON i.id=p.ip_id WHERE p.id=?
        """,
        (product_id,),
    ).fetchone()

    if not product:
        abort(404)

    return render_template("product_detail.html", p=product)


@app.route("/product/<int:product_id>/scan", methods=["GET", "POST"])
def scan_product(product_id):
    connection = db()

    product = connection.execute(
        """
        SELECT p.*,i.name ip_name FROM products p
        LEFT JOIN ips i ON i.id=p.ip_id WHERE p.id=?
        """,
        (product_id,),
    ).fetchone()

    if not product:
        abort(404)

    user_id = session.get("user_id")

    scan_count = connection.execute(
        "SELECT COUNT(*) n FROM product_scans WHERE product_id=?",
        (product_id,),
    ).fetchone()["n"]

    last_scan = connection.execute(
        "SELECT MAX(scanned_at) last_scan FROM product_scans WHERE product_id=?",
        (product_id,),
    ).fetchone()["last_scan"]

    status = "valid" if product["authorized"] else "unauthorized"
    if scan_count >= 10:
        status = "suspicious"

    city = ""
    if user_id:
        user = connection.execute(
            "SELECT city,consent_analytics FROM users WHERE id=?",
            (user_id,),
        ).fetchone()

        if user and user["consent_analytics"]:
            city = user["city"] or ""

    connection.execute(
        """
        INSERT INTO product_scans
        (product_id,user_id,scanned_at,city,status,ip_address)
        VALUES (?,?,?,?,?,?)
        """,
        (
            product_id, user_id, now(), city, status,
            request.remote_addr or "",
        ),
    )
    connection.commit()

    if user_id:
        log_event(
            user_id, "PRODUCT_SCANNED", "product",
            product_id, {"status": status}
        )

    if (
        user_id and status == "valid"
        and request.method == "POST"
        and request.form.get("register") == "yes"
    ):
        try:
            connection.execute(
                """
                INSERT INTO registered_products
                (product_id,user_id,registered_at)
                VALUES (?,?,?)
                """,
                (product_id, user_id, now()),
            )
            connection.commit()

            award_points(
                user_id, product["points"],
                "PRODUCT_REGISTERED", "product", product_id
            )
            flash(
                f"Product registered successfully. +{product['points']} points!",
                "success",
            )

        except IntegrityError:
            connection.rollback()
            flash("This product is already registered to your account.", "info")

        return redirect(url_for("dashboard"))

    return render_template(
        "scan_result.html",
        p=product,
        status=status,
        scan_count=scan_count + 1,
        first_scan=not bool(last_scan),
        logged_in=bool(user_id),
    )


# =========================================================
# EVENTS
# =========================================================

@app.route("/event/<int:event_id>/register", methods=["POST"])
@login_required
def event_register(event_id):
    connection = db()
    event = connection.execute(
        "SELECT * FROM events WHERE id=? AND active=1", (event_id,)
    ).fetchone()

    if not event:
        abort(404)

    count = connection.execute(
        "SELECT COUNT(*) n FROM event_registrations WHERE event_id=?",
        (event_id,),
    ).fetchone()["n"]

    if count >= event["capacity"]:
        flash("This event is at capacity.", "danger")
        return redirect(request.referrer or url_for("explore"))

    ticket = "EVT-" + secrets.token_hex(5).upper()

    try:
        connection.execute(
            """
            INSERT INTO event_registrations
            (event_id,user_id,ticket_code,registered_at)
            VALUES (?,?,?,?)
            """,
            (event_id, session["user_id"], ticket, now()),
        )
        connection.commit()

        log_event(session["user_id"], "EVENT_REGISTERED", "event", event_id)
        flash("Event registration confirmed. Ticket: " + ticket, "success")

    except IntegrityError:
        connection.rollback()
        flash("You are already registered for this event.", "info")

    return redirect(url_for("dashboard"))


@app.route("/event/checkin/<ticket>", methods=["POST"])
@roles_required("admin", "event_organizer")
def event_checkin(ticket):
    connection = db()
    registration = connection.execute(
        "SELECT * FROM event_registrations WHERE ticket_code=?",
        (ticket,),
    ).fetchone()

    if not registration:
        flash("Ticket not found.", "danger")
    elif registration["checked_in"]:
        flash("Ticket already checked in.", "info")
    else:
        connection.execute(
            """
            UPDATE event_registrations
            SET checked_in=1,checked_in_at=? WHERE id=?
            """,
            (now(), registration["id"]),
        )
        connection.commit()

        award_points(
            registration["user_id"], 20,
            "EVENT_CHECKED_IN", "event", registration["event_id"]
        )
        flash("Check-in successful. +20 points awarded.", "success")

    return redirect(url_for("manage", entity="events"))


# =========================================================
# COMMUNITIES
# =========================================================

@app.route("/community/<int:community_id>/join", methods=["POST"])
@login_required
def join_community(community_id):
    connection = db()
    community = connection.execute(
        "SELECT * FROM communities WHERE id=?", (community_id,)
    ).fetchone()

    if not community:
        abort(404)

    try:
        connection.execute(
            """
            INSERT INTO community_members(community_id,user_id,joined_at)
            VALUES (?,?,?)
            """,
            (community_id, session["user_id"], now()),
        )
        connection.commit()

        log_event(session["user_id"], "COMMUNITY_JOINED", "community", community_id)
        award_points(
            session["user_id"], 10, "COMMUNITY_JOINED",
            "community", community_id
        )
        flash("You joined the community. +10 points!", "success")

    except IntegrityError:
        connection.rollback()
        flash("You are already a member.", "info")

    return redirect(request.referrer or url_for("explore"))


@app.route("/community/<int:community_id>/post", methods=["POST"])
@login_required
def create_post(community_id):
    body = request.form.get("body", "").strip()

    if not body or len(body) > 2000:
        flash("Post must be between 1 and 2000 characters.", "danger")
    else:
        community = db().execute(
            "SELECT id FROM communities WHERE id=?", (community_id,)
        ).fetchone()

        if not community:
            abort(404)

        db().execute(
            """
            INSERT INTO posts(community_id,user_id,body,created_at)
            VALUES (?,?,?,?)
            """,
            (community_id, session["user_id"], body, now()),
        )
        db().commit()

        log_event(session["user_id"], "COMMUNITY_POSTED", "community", community_id)
        flash("Your post was published.", "success")

    return redirect(url_for("community_detail", community_id=community_id))


@app.route("/community/<int:community_id>")
def community_detail(community_id):
    connection = db()

    community = connection.execute(
        """
        SELECT c.*,i.name ip_name FROM communities c
        LEFT JOIN ips i ON i.id=c.ip_id WHERE c.id=?
        """,
        (community_id,),
    ).fetchone()

    if not community:
        abort(404)

    posts = connection.execute(
        """
        SELECT p.*,u.name author FROM posts p
        JOIN users u ON u.id=p.user_id
        WHERE p.community_id=? AND p.status='published'
        ORDER BY p.id DESC
        """,
        (community_id,),
    ).fetchall()

    return render_template("community.html", community=community, posts=posts)


# =========================================================
# REWARDS
# =========================================================

@app.route("/rewards/<int:reward_id>/redeem", methods=["POST"])
@login_required
def redeem_reward(reward_id):
    connection = db()

    reward = connection.execute(
        "SELECT * FROM rewards WHERE id=? AND active=1",
        (reward_id,),
    ).fetchone()

    profile = connection.execute(
        "SELECT points FROM fan_profiles WHERE user_id=?",
        (session["user_id"],),
    ).fetchone()

    if not reward:
        abort(404)

    if not profile or profile["points"] < reward["points_cost"]:
        flash("Not enough points for this reward.", "danger")
    else:
        code = "RWD-" + secrets.token_hex(5).upper()

        connection.execute(
            "UPDATE fan_profiles SET points=points-? WHERE user_id=?",
            (reward["points_cost"], session["user_id"]),
        )

        connection.execute(
            """
            INSERT INTO reward_redemptions
            (reward_id,user_id,points_spent,code,redeemed_at)
            VALUES (?,?,?,?,?)
            """,
            (
                reward_id, session["user_id"],
                reward["points_cost"], code, now()
            ),
        )

        connection.commit()
        log_event(session["user_id"], "REWARD_REDEEMED", "reward", reward_id)
        flash("Reward redeemed. Code: " + code, "success")

    return redirect(url_for("dashboard"))


# =========================================================
# MANAGEMENT CONFIGURATION
# =========================================================

ENTITY_CONFIG = {
    "ips": {
        "title": "IP Catalogue", "table": "ips",
        "fields": [
            ("name", "IP / Anime Title", "text"),
            ("description", "Description", "textarea"),
            ("owner", "Rights Owner", "text"),
            ("image_url", "Image URL", "url"),
            ("active", "Active", "checkbox"),
        ],
        "admin": ["admin", "ip_owner"],
        "columns": ["name", "owner", "active"],
    },
    "characters": {
        "title": "Characters", "table": "characters",
        "fields": [
            ("ip_id", "IP", "select_ips"),
            ("name", "Character Name", "text"),
            ("description", "Description", "textarea"),
        ],
        "admin": ["admin", "ip_owner"],
        "columns": ["name", "ip_id", "description"],
    },
    "products": {
        "title": "Product Traceability", "table": "products",
        "fields": [
            ("product_code", "Unique Product ID", "text"),
            ("name", "Product Name", "text"),
            ("ip_id", "IP", "select_ips"),
            ("product_type", "Product Type", "text"),
            ("manufacturer", "Manufacturer", "text"),
            ("distributor", "Distributor", "text"),
            ("retailer", "Retailer", "text"),
            ("batch", "Batch", "text"),
            ("authorized", "Authorized", "checkbox"),
            ("description", "Description", "textarea"),
            ("points", "Registration Points", "number"),
        ],
        "admin": ["admin", "ip_owner", "partner"],
        "columns": ["product_code", "name", "ip_id", "authorized"],
    },
    "events": {
        "title": "Events & Check-in", "table": "events",
        "fields": [
            ("name", "Event Name", "text"),
            ("ip_id", "IP", "select_ips"),
            ("location", "Location", "text"),
            ("event_date", "Date", "date"),
            ("event_time", "Time", "time"),
            ("capacity", "Capacity", "number"),
            ("description", "Description", "textarea"),
            ("organizer", "Organizer", "text"),
            ("active", "Active", "checkbox"),
        ],
        "admin": ["admin", "ip_owner", "event_organizer"],
        "columns": ["name", "location", "event_date", "capacity", "active"],
    },
    "communities": {
        "title": "Fan Communities", "table": "communities",
        "fields": [
            ("name", "Community Name", "text"),
            ("ip_id", "IP", "select_ips"),
            ("description", "Description", "textarea"),
            ("city", "City", "text"),
        ],
        "admin": ["admin", "ip_owner", "community_manager"],
        "columns": ["name", "ip_id", "city"],
    },
    "campaigns": {
        "title": "Campaign Management", "table": "campaigns",
        "fields": [
            ("name", "Campaign Name", "text"),
            ("ip_id", "IP", "select_ips"),
            ("description", "Description", "textarea"),
            ("start_date", "Start Date", "date"),
            ("end_date", "End Date", "date"),
            ("active", "Active", "checkbox"),
            ("reward_points", "Completion Points", "number"),
        ],
        "admin": ["admin", "ip_owner"],
        "columns": ["name", "start_date", "end_date", "active", "reward_points"],
    },
    "rewards": {
        "title": "Loyalty & Rewards", "table": "rewards",
        "fields": [
            ("name", "Reward Name", "text"),
            ("description", "Description", "textarea"),
            ("points_cost", "Points Cost", "number"),
            ("reward_type", "Reward Type", "text"),
            ("active", "Active", "checkbox"),
        ],
        "admin": ["admin", "ip_owner"],
        "columns": ["name", "reward_type", "points_cost", "active"],
    },
    "content": {
        "title": "Official Content Hub", "table": "content",
        "fields": [
            ("title", "Content Title", "text"),
            ("content_type", "Content Type", "text"),
            ("url", "URL", "url"),
            ("description", "Description", "textarea"),
            ("ip_id", "IP", "select_ips"),
            ("active", "Active", "checkbox"),
        ],
        "admin": ["admin", "ip_owner"],
        "columns": ["title", "content_type", "ip_id", "active"],
    },
    "partners": {
        "title": "Partner Directory", "table": "partners",
        "fields": [
            ("name", "Partner Name", "text"),
            ("partner_type", "Partner Type", "text"),
            ("email", "Email", "email"),
            ("city", "City", "text"),
            ("status", "Status", "text"),
        ],
        "admin": ["admin", "ip_owner"],
        "columns": ["name", "partner_type", "email", "city", "status"],
    },
    "notifications": {
        "title": "Notifications", "table": "notifications",
        "fields": [
            ("title", "Notification Title", "text"),
            ("body", "Message", "textarea"),
            ("target_segment", "Target Segment", "text"),
            ("ip_id", "IP (optional)", "select_ips"),
        ],
        "admin": ["admin", "ip_owner"],
        "columns": ["title", "target_segment", "ip_id", "created_at"],
    },
}


@app.route("/manage/<entity>", methods=["GET", "POST"])
@login_required
def manage(entity):
    config = ENTITY_CONFIG.get(entity)
    if not config:
        abort(404)

    user = current_user()
    if user["role"] not in config["admin"]:
        abort(403)

    connection = db()
    edit_id = safe_int(request.args.get("edit"))

    if request.method == "POST":
        action = request.form.get("action", "save")
        record_id = safe_int(request.form.get("id"))

        if action == "delete":
            connection.execute(
                f'DELETE FROM {config["table"]} WHERE id=?',
                (record_id,),
            )
            connection.commit()
            flash("Record deleted.", "success")
            return redirect(url_for("manage", entity=entity))

        columns = []
        values = []

        for key, label, field_type in config["fields"]:
            if field_type == "checkbox":
                value = 1 if request.form.get(key) else 0
            elif field_type == "select_ips":
                value = safe_int(request.form.get(key)) or None
            elif field_type == "number":
                value = safe_int(request.form.get(key), 0)
            else:
                value = request.form.get(key, "").strip()

            columns.append(key)
            values.append(value)

        try:
            if record_id:
                assignments = ",".join(f"{column}=?" for column in columns)
                connection.execute(
                    f'UPDATE {config["table"]} SET {assignments} WHERE id=?',
                    values + [record_id],
                )
            else:
                columns.append("created_at")
                values.append(now())
                placeholders = ",".join("?" for _ in columns)
                connection.execute(
                    f'INSERT INTO {config["table"]} ({",".join(columns)}) VALUES ({placeholders})',
                    values,
                )

            connection.commit()
            flash("Record saved successfully.", "success")

        except IntegrityError:
            connection.rollback()
            flash("Could not save record. Check unique IDs and required fields.", "danger")

        return redirect(url_for("manage", entity=entity))

    rows = connection.execute(
        f'SELECT * FROM {config["table"]} ORDER BY id DESC'
    ).fetchall()

    record = None
    if edit_id:
        record = connection.execute(
            f'SELECT * FROM {config["table"]} WHERE id=?',
            (edit_id,),
        ).fetchone()

    ips = connection.execute("SELECT id,name FROM ips ORDER BY name").fetchall()

    display_rows = []
    for row in rows:
        item = dict(row)
        if item.get("ip_id"):
            ip = connection.execute(
                "SELECT name FROM ips WHERE id=?", (item["ip_id"],)
            ).fetchone()
            item["ip_name"] = ip["name"] if ip else "—"
        display_rows.append(item)

    return render_template(
        "manage.html", entity=entity, cfg=config,
        rows=display_rows, record=record, ips=ips
    )


# =========================================================
# FAN MANAGEMENT
# =========================================================

@app.route("/manage/fans")
@login_required
@roles_required("admin", "ip_owner", "community_manager")
def manage_fans():
    query = request.args.get("q", "").strip()
    sql = """
        SELECT u.*,fp.fan_code,fp.points,fp.segment,fp.engagement_score,
               i.name favorite_ip
        FROM users u
        LEFT JOIN fan_profiles fp ON fp.user_id=u.id
        LEFT JOIN ips i ON i.id=fp.favorite_ip_id
        WHERE u.role='fan'
    """
    parameters = []

    if query:
        sql += """
            AND (
                u.name ILIKE ? OR u.email ILIKE ?
                OR fp.fan_code ILIKE ? OR u.city ILIKE ?
            )
        """
        parameters = [f"%{query}%"] * 4

    fans = db().execute(
        sql + " ORDER BY u.id DESC", parameters
    ).fetchall()

    return render_template("fans.html", fans=fans, q=query)


@app.route("/manage/fans/<int:uid>/delete", methods=["POST"])
@login_required
@roles_required("admin")
def delete_fan(uid):
    if uid == session["user_id"]:
        flash("You cannot delete your own active account.", "danger")
    else:
        db().execute(
            "DELETE FROM users WHERE id=? AND role='fan'", (uid,)
        )
        db().commit()
        flash("Fan account deleted.", "success")

    return redirect(url_for("manage_fans"))


# =========================================================
# ANALYTICS AND CSV EXPORT
# =========================================================

@app.route("/analytics")
@login_required
@roles_required("admin", "ip_owner", "partner", "event_organizer", "community_manager")
def analytics():
    connection = db()

    daily = connection.execute(
        """
        SELECT substr(created_at,1,10) day,COUNT(*) total
        FROM interactions GROUP BY day ORDER BY day DESC LIMIT 14
        """
    ).fetchall()

    events = connection.execute(
        """
        SELECT e.name,COUNT(er.id) registrations,
        SUM(CASE WHEN er.checked_in=1 THEN 1 ELSE 0 END) checkins
        FROM events e
        LEFT JOIN event_registrations er ON er.event_id=e.id
        GROUP BY e.id ORDER BY registrations DESC
        """
    ).fetchall()

    products = connection.execute(
        """
        SELECT p.name,p.product_code,
        COUNT(DISTINCT s.id) scans,
        COUNT(DISTINCT rp.id) registrations,
        COUNT(DISTINCT CASE WHEN s.status='suspicious' THEN s.id END) suspicious
        FROM products p
        LEFT JOIN product_scans s ON s.product_id=p.id
        LEFT JOIN registered_products rp ON rp.product_id=p.id
        GROUP BY p.id ORDER BY scans DESC
        """
    ).fetchall()

    segments = connection.execute(
        "SELECT segment,COUNT(*) total FROM fan_profiles GROUP BY segment ORDER BY total DESC"
    ).fetchall()

    funnel = [
        ("Registered Fans", connection.execute("SELECT COUNT(*) n FROM users WHERE role='fan'").fetchone()["n"]),
        ("Product Scans", connection.execute("SELECT COUNT(*) n FROM product_scans").fetchone()["n"]),
        ("Registered Products", connection.execute("SELECT COUNT(*) n FROM registered_products").fetchone()["n"]),
        ("Event Registrations", connection.execute("SELECT COUNT(*) n FROM event_registrations").fetchone()["n"]),
        ("Community Members", connection.execute("SELECT COUNT(*) n FROM community_members").fetchone()["n"]),
    ]

    return render_template(
        "analytics.html", daily=daily, events=events,
        products=products, segments=segments, funnel=funnel
    )


@app.route("/reports/export.csv")
@login_required
@roles_required("admin", "ip_owner", "partner")
def export_csv():
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Fan ID", "Name", "Email", "City", "Country",
        "Favorite IP", "Points", "Segment", "Engagement Score", "Created At"
    ])

    rows = db().execute(
        """
        SELECT fp.fan_code,u.name,u.email,u.city,u.country,i.name,
               fp.points,fp.segment,fp.engagement_score,u.created_at
        FROM users u
        JOIN fan_profiles fp ON fp.user_id=u.id
        LEFT JOIN ips i ON i.id=fp.favorite_ip_id
        WHERE u.role='fan' ORDER BY u.id
        """
    ).fetchall()

    for row in rows:
        writer.writerow(list(row.values()))

    data = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    data.seek(0)

    return send_file(
        data, mimetype="text/csv",
        as_attachment=True,
        download_name="fan-intelligence-report.csv"
    )


# =========================================================
# USER SETTINGS
# =========================================================

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = current_user()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        city = request.form.get("city", "").strip()
        country = request.form.get("country", "Egypt").strip() or "Egypt"
        analytics_consent = int(bool(request.form.get("consent_analytics")))
        marketing_consent = int(bool(request.form.get("consent_marketing")))

        connection = db()
        connection.execute(
            """
            UPDATE users
            SET name=?,city=?,country=?,consent_analytics=?,consent_marketing=?
            WHERE id=?
            """,
            (
                name, city, country, analytics_consent,
                marketing_consent, user["id"]
            ),
        )

        for consent_type, granted in [
            ("analytics", analytics_consent),
            ("marketing", marketing_consent),
        ]:
            connection.execute(
                """
                INSERT INTO consent_records
                (user_id,consent_type,granted,recorded_at)
                VALUES (?,?,?,?)
                """,
                (user["id"], consent_type, granted, now()),
            )

        connection.commit()
        flash("Profile and privacy preferences updated.", "success")
        return redirect(url_for("settings"))

    return render_template("settings.html", u=user)


# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(403)
def forbidden(error):
    return render_template(
        "error.html",
        code=403,
        message="You do not have permission to access this area."
    ), 403


@app.errorhandler(404)
def not_found(error):
    return render_template(
        "error.html",
        code=404,
        message="The page or record could not be found."
    ), 404


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

# On Vercel, the module is imported rather than executed as __main__.
# Set REQUIRE_DATABASE_INIT=1 in Vercel if deployment should fail immediately
# when database initialization fails.
try:
    init_db()
except Exception:
    app.logger.exception("Database initialization failed")
    if os.environ.get("REQUIRE_DATABASE_INIT") == "1":
        raise


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
