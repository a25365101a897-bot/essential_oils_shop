from flask import Flask, render_template, request, redirect, url_for, session, abort, flash
import yaml, os
from config import Config
from flask import url_for
from sqlalchemy.orm import joinedload, selectinload
from collections import Counter


app = Flask(__name__)
app.config.from_object(Config)

# ---------- 工具 ----------
def load_yaml(name):
    path = os.path.join(app.config['CONTENT_DIR'], f"{name}.yml")
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}

def save_yaml(name, data):
    path = os.path.join(app.config['CONTENT_DIR'], f"{name}.yml")
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

def parse_price_to_cents(price_text: str) -> int:
    # 支援 "NT$1,234"、"1234"、"1,234"
    p = price_text.replace("NT$", "").replace(",", "").strip()
    try:
        return int(round(float(p) * 100))
    except:
        return 0

def cents_to_ntd(cents: int) -> str:
    return f"NT${cents/100:,.0f}"





@app.template_filter("static_url")
def static_url(path: str) -> str:
    """
    把多種寫法標準化成可用的 URL：
    - 絕對/外部: http(s)://... 或 以 / 開頭 → 原樣回傳
    - 'static/img/x.jpg' → 轉成 url_for('static', filename='img/x.jpg')
    - 'img/x.jpg' → 轉成 url_for('static', filename='img/x.jpg')
    - 空值 → 空字串
    """
    if not path:
        return ""
    p = path.strip()
    if p.startswith(("http://", "https://", "/")):
        return p
    if p.startswith("static/"):
        p = p[len("static/"):]
    return url_for("static", filename=p)

# ====== 新增：套件 ======
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, Integer, String, Column
from sqlalchemy.orm import DeclarativeBase, sessionmaker, scoped_session

from sqlalchemy import create_engine, Integer, String, Column, ForeignKey, DateTime, Numeric, func, Enum
from sqlalchemy.orm import DeclarativeBase, sessionmaker, scoped_session, relationship
import enum
import secrets
import datetime as dt

class Base(DeclarativeBase): pass

# 會員
class User(Base, UserMixin):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    name = Column(String(60), nullable=False)
    password_hash = Column(String(255), nullable=False)
    carts = relationship("Cart", back_populates="user")
    orders = relationship("Order", back_populates="user")

# 購物車（僅保留一筆 open 狀態，結帳後轉為 closed）
class CartStatus(enum.Enum):
    open = "open"
    closed = "closed"

class Cart(Base):
    __tablename__ = "carts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(Enum(CartStatus), nullable=False, default=CartStatus.open)
    created_at = Column(DateTime, server_default=func.now())
    user = relationship("User", back_populates="carts")
    items = relationship("CartItem", cascade="all, delete-orphan", back_populates="cart")

class CartItem(Base):
    __tablename__ = "cart_items"
    id = Column(Integer, primary_key=True)
    cart_id = Column(Integer, ForeignKey("carts.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    image = Column(String(255), nullable=True)
    price_cents = Column(Integer, nullable=False, default=0)  # 以「分」存，避免浮點誤差
    qty = Column(Integer, nullable=False, default=1)
    cart = relationship("Cart", back_populates="items")

# 訂單
class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    order_no = Column(String(24), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())
    total_cents = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="paid")  # demo 直接當已付款
    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", cascade="all, delete-orphan", back_populates="order")

class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    image = Column(String(255), nullable=True)
    price_cents = Column(Integer, nullable=False, default=0)
    qty = Column(Integer, nullable=False, default=1)
    order = relationship("Order", back_populates="items")

# ----------------------------------------------------
# 購物車工具函式：取得或建立一個 open 狀態的購物車
# ----------------------------------------------------
def get_or_create_open_cart(db, user_id: int) -> Cart:
    cart = db.query(Cart).filter_by(user_id=user_id, status=CartStatus.open).first()
    if not cart:
        cart = Cart(user_id=user_id, status=CartStatus.open)
        db.add(cart)
        db.flush()
    return cart




# 建立 DB（放在專案根目錄）
DB_PATH = os.path.join(os.path.dirname(__file__), "site.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)
Base.metadata.create_all(engine)
SessionLocal = scoped_session(sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False
))


# ====== 新增：Flask-Login ======
login_manager = LoginManager()
login_manager.login_view = "login"         # 未登入會導去 /login
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    db = SessionLocal()
    try:
        return db.get(User, int(user_id))
    finally:
        db.close()

# ====== 新增：全站可用變數（原本你已有 inject_site，可共存）======
@app.context_processor
def inject_user_and_cart():
    if current_user.is_authenticated:
        db = SessionLocal()
        try:
            cart = db.query(Cart).filter_by(user_id=current_user.id, status=CartStatus.open).first()
            count = sum(i.qty for i in cart.items) if cart else 0
        finally:
            db.close()
    else:
        cart = session.get("cart", {})
        count = sum(item["qty"] for item in cart.values()) if cart else 0
    return {"current_user": current_user, "cart_count": count}


# ====== 新增：會員相關路由 ======
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        name  = request.form.get("name","").strip()
        pw    = request.form.get("password","")
        if not email or not name or not pw:
            flash("請完整填寫", "error"); return redirect(url_for("register"))

        db = SessionLocal()
        try:
            if db.query(User).filter_by(email=email).first():
                flash("這個 Email 已註冊", "error"); return redirect(url_for("register"))
            u = User(email=email, name=name, password_hash=generate_password_hash(pw))
            db.add(u); db.commit()
            flash("註冊成功，請登入", "success")
            return redirect(url_for("login"))
        finally:
            db.close()
    return render_template("auth/register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        pw    = request.form.get("password","")
        db = SessionLocal()
        try:
            u = db.query(User).filter_by(email=email).first()
            if not u or not check_password_hash(u.password_hash, pw):
                flash("帳號或密碼錯誤", "error"); return redirect(url_for("login"))

            login_user(u)   # 成功登入
            flash("登入成功", "success")

            # 🔽 這裡合併 session 購物車到 DB
            sess_cart = session.get("cart")
            if sess_cart:
                cart = get_or_create_open_cart(db, u.id)
                for _cid, item in sess_cart.items():
                    name  = item.get("name")
                    image = item.get("image")
                    pcs   = parse_price_to_cents(item.get("price","0"))
                    qty   = int(item.get("qty", 1))
                    exist = next((it for it in cart.items
                                  if it.name == name and it.price_cents == pcs), None)
                    if exist:
                        exist.qty += qty
                    else:
                        cart.items.append(CartItem(name=name, image=image,
                                                   price_cents=pcs, qty=qty))
                db.commit()
                session.pop("cart", None)

            return redirect(request.args.get("next") or url_for("index"))
        finally:
            db.close()
    return render_template("auth/login.html")

@app.route("/my/orders")
@login_required
def my_orders():
    db = SessionLocal()
    try:
        orders = (db.query(Order)
                    .options(selectinload(Order.items))
                    .filter_by(user_id=current_user.id)
                    .order_by(Order.id.desc())
                    .all())
        return render_template("auth/my_orders.html",
                               orders=orders, cents_to_ntd=cents_to_ntd)
    finally:
        db.close()




@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("已登出", "info")
    return redirect(url_for("index"))

# ====== 新增：購物車工具 ======
def _cart():
    if "cart" not in session: session["cart"] = {}
    return session["cart"]

def _slugify(name):
    # 輕量 slug（避免額外依賴），你也可用 python-slugify
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-")

# ====== 新增：購物車路由 ======
@app.route("/cart")
def cart_view():
    if current_user.is_authenticated:
        db = SessionLocal()
        try:
            cart = get_or_create_open_cart(db, current_user.id)
            total = sum(i.qty * i.price_cents for i in cart.items)
            return render_template("shop/cart.html",
                                   cart={str(i.id): {"name": i.name, "image": i.image, "qty": i.qty,
                                                     "price": cents_to_ntd(i.price_cents)} for i in cart.items},
                                   total=total/100)
        finally:
            db.close()
    else:
        cart = session.get("cart", {})
        total = sum(item["qty"] * parse_price_to_cents(item["price"]) for item in cart.values()) if cart else 0
        return render_template("shop/cart.html", cart=cart, total=total/100)


from urllib.parse import urlparse

@app.route("/cart/add", methods=["POST"])
def cart_add():
    name  = request.form.get("name"); price = request.form.get("price")
    image = request.form.get("image"); qty = int(request.form.get("qty", "1"))
    next_url = request.form.get("next")  # e.g., "/#products"

    if not name or not price:
        flash("加入購物車失敗：資料不足", "error")
        return redirect(url_for("index"))

    if current_user.is_authenticated:
        db = SessionLocal()
        try:
            cart = get_or_create_open_cart(db, current_user.id)
            pcs = parse_price_to_cents(price)
            exist = next((it for it in cart.items if it.name == name and it.price_cents == pcs), None)
            if exist: exist.qty += qty
            else: cart.items.append(CartItem(name=name, image=image, price_cents=pcs, qty=qty))
            db.commit()
        finally:
            db.close()
    else:
        cid = _slugify(name)
        cart = _cart()
        if cid in cart: cart[cid]["qty"] += qty
        else: cart[cid] = {"name": name, "price": price, "image": image, "qty": qty}
        session.modified = True

    flash("已加入購物車", "success")
    if next_url:
        parsed = urlparse(next_url)
        if (not parsed.scheme) and (not parsed.netloc) and next_url.startswith("/"):
            return redirect(next_url)
    return redirect(url_for("index") + "#products")





@app.route("/cart/update", methods=["POST"])
def cart_update():
    cid = request.form.get("id")
    qty = int(request.form.get("qty", "1"))

    if current_user.is_authenticated:
        db = SessionLocal()
        try:
            item = db.query(CartItem).get(int(cid))
            if item and item.cart.user_id == current_user.id and item.cart.status == CartStatus.open:
                if qty <= 0: db.delete(item)
                else: item.qty = qty
                db.commit()
        finally:
            db.close()
    else:
        cart = _cart()
        if cid in cart:
            if qty <= 0: cart.pop(cid)
            else: cart[cid]["qty"] = qty
            session.modified = True

    return redirect(url_for("cart_view"))


@app.route("/cart/clear", methods=["POST"])
def cart_clear():
    if current_user.is_authenticated:
        db = SessionLocal()
        try:
            cart = get_or_create_open_cart(db, current_user.id)
            cart.items.clear()
            db.commit()
        finally:
            db.close()
    else:
        session.pop("cart", None)

    flash("已清空購物車", "info")
    return redirect(url_for("cart_view"))


def generate_order_no() -> str:
    # yymmdd + 隨機 6 碼
    return dt.datetime.now().strftime("%y%m%d") + "-" + secrets.token_hex(3).upper()

@app.route("/checkout", methods=["POST"])
@login_required
def checkout():
    db = SessionLocal()
    try:
        cart = get_or_create_open_cart(db, current_user.id)
        if not cart.items:
            flash("購物車是空的", "error")
            return redirect(url_for("cart_view"))

        total_cents = sum(i.qty * i.price_cents for i in cart.items)
        order = Order(order_no=generate_order_no(),
                      user_id=current_user.id,
                      total_cents=total_cents,
                      status="pending")
        # Demo 當作已付款
        db.add(order); db.flush()

        for i in cart.items:
            db.add(OrderItem(order_id=order.id, name=i.name, image=i.image, price_cents=i.price_cents, qty=i.qty))

        # 關閉購物車
        cart.status = CartStatus.closed
        db.commit()

        flash(f"下單成功：{order.order_no}（Demo）", "success")
        return redirect(url_for("index"))
    finally:
        db.close()

# ---------- 產品路由 ----------
@app.route("/products")
def products():
    data = load_yaml("products") or {}
    prods = data.get("products", [])
    cat = request.args.get("cat", "all").strip().lower()

    # 統計各分類數量（含 all）
    counts = Counter()
    for p in prods:
        tags = [t.lower() for t in p.get("tags", [])]
        if not tags:
            tags = ["uncategorized"]
        for t in tags:
            counts[t] += 1
        counts["all"] += 1

    # 過濾清單
    if cat != "all":
        view = [p for p in prods if cat in [t.lower() for t in p.get("tags", [])]]
    else:
        view = prods

    # 把可選分類帶進去（並帶上數量）
    cats = data.get("categories", [])
    # 若沒放 "all" 就補上
    if not any(c.get("key") == "all" for c in cats):
        cats = [{"key": "all", "name": "全部商品"}] + cats

    # 附上數量
    for c in cats:
        c["count"] = counts.get(c["key"], 0)

    return render_template("shop/products.html",
                           data=data,
                           categories=cats,
                           current_cat=cat,
                           products=view)
# ---------- 商品詳情 ----------
@app.route("/product/<slug>")
def product_detail(slug):
    data = load_yaml("products") or {}
    prods = data.get("products", [])
    # 嘗試比對 slug 或 name
    item = None
    for p in prods:
        s = p.get("slug") or _slugify(p.get("name", ""))
        if s == slug:
            item = p
            break

    if not item:
        flash("找不到該商品", "error")
        return redirect(url_for("products"))

    return render_template("shop/product_detail.html", item=item)


# ---------- 前台 ----------
@app.route('/')
def index():
    data = load_yaml('home') or {}

    # ▼ 將 from_products 的 slug 轉成完整商品物件，供模板渲染
    prods_all = (load_yaml('products') or {}).get('products', [])
    # 建立 slug -> 商品 速查表（若無 slug 用 _slugify(name)）
    lookup = {}
    for p in prods_all:
        s = p.get('slug') or _slugify(p.get('name', ''))
        pp = dict(p)            # 複製，避免修改到原資料
        pp['slug'] = s
        lookup[s] = pp

    for sec in data.get('sections', []):
        if sec.get('type') == 'product_grid' and 'from_products' in sec:
            resolved = [lookup[s] for s in sec['from_products'] if s in lookup]
            sec['products'] = resolved   # 直接丟回模板
            # 可選：若想保底至少 3 件，補齊沒指定到的
            # while len(sec['products']) < 3:
            #     for x in prods_all:
            #         sx = x.get('slug') or _slugify(x.get('name',''))
            #         if sx not in sec['from_products']:
            #             sec['products'].append(lookup[sx]); break

    return render_template('shop/index.html', data=data)


@app.route('/about')
def about():
    data = load_yaml('about')
    return render_template('shop/about.html', data=data)







# ---------- 後台：登入 ----------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        pw = request.form.get('password', '')
        if pw == app.config['ADMIN_PASSWORD']:
            session['admin'] = True
            flash('登入成功', 'success')
            return redirect(url_for('admin_dashboard'))
        flash('密碼錯誤', 'error')
    return render_template('admin/admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    flash('已登出', 'info')
    return redirect(url_for('index'))

# ---------- 後台：內容清單 ----------
@app.route('/admin')
def admin_dashboard():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    files = []
    for fn in os.listdir(app.config['CONTENT_DIR']):
        if fn.endswith('.yml'):
            files.append(fn[:-4])
    files.sort()
    return render_template('admin/admin_dashboard.html', files=files)

# ---------- 後台：會員與訂購清單 ----------
@app.route("/admin/users")
def admin_users():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.id.desc()).all()
        return render_template("admin/users.html", users=users)
    finally:
        db.close()


@app.route("/admin/orders")
def admin_orders():
    if not session.get("admin"): return redirect(url_for("admin_login"))
    db = SessionLocal()
    try:
        orders = (db.query(Order)
                    .options(joinedload(Order.user),
                             selectinload(Order.items))
                    .order_by(Order.id.desc())
                    .all())
        return render_template("admin/orders.html",
                               orders=orders, cents_to_ntd=cents_to_ntd)
    finally:
        db.close()

# ---------- 後台：單筆訂單詳情 + 狀態修改 ----------
@app.route("/admin/orders/<int:oid>", methods=["GET", "POST"])
def admin_order_detail(oid):
    if not session.get("admin"): return redirect(url_for("admin_login"))
    db = SessionLocal()
    try:
        o = (db.query(Order)
               .options(joinedload(Order.user), selectinload(Order.items))
               .get(oid))
        if not o:
            flash("找不到訂單", "error")
            return redirect(url_for("admin_orders"))

        if request.method == "POST":
            new_status = request.form.get("status", "").strip()
            # 建議的狀態清單
            allowed = {"pending","paid","shipped","completed","canceled"}
            if new_status in allowed:
                o.status = new_status
                db.commit()
                flash("已更新訂單狀態", "success")
            else:
                flash("狀態不合法", "error")
            return redirect(url_for("admin_order_detail", oid=oid))

        return render_template("admin/order_detail.html",
                               o=o, cents_to_ntd=cents_to_ntd)
    finally:
        db.close()



# ---------- 後台：編輯 ----------
@app.route('/admin/edit/<name>', methods=['GET', 'POST'])
def admin_edit(name):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        # 直寫 YAML：表單中以 data[key] 命名
        data = load_yaml(name)
        for k, v in request.form.items():
            if not k.startswith('data['):
                continue
            key = k[5:-1]
            data[key] = v
        save_yaml(name, data)
        flash('已儲存', 'success')
        return redirect(url_for('admin_dashboard'))
    data = load_yaml(name)
    return render_template('admin/admin_edit.html', name=name, data=data)


@app.context_processor
def inject_site():
    """
    全站可用的 site 變數，預設讀 home.yml 以取得 footer/seo 等共用資訊。
    這樣就算個別模板沒有傳 data 也能安全取用。
    """
    try:
        site = load_yaml("home") or {}
    except Exception:
        site = {}
    return {"site": site}


# ---------- 錯誤頁 ----------
@app.errorhandler(404)
def not_found(e):
    return render_template('shop/error.html', code=404, msg='Page Not Found'), 404


if __name__ == '__main__':
    app.run(debug=True)
