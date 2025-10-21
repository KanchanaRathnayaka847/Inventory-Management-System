from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from flask import g
from sqlalchemy import text
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text
import os

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), nullable=True)
    # Optional FK to normalized category table (back-compat: keep string field too)
    category_id = db.Column(db.Integer, db.ForeignKey('product_category.id'), nullable=True)
    unit = db.Column(db.String(30), nullable=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    price = db.Column(db.Float, nullable=False, default=0.0)
    reorder_level = db.Column(db.Integer, nullable=False, default=0)
    category_rel = db.relationship('ProductCategory', lazy='joined')


class ProductCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)


class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    remaining = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    product = db.relationship('Product')


class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    product = db.relationship('Product')




def create_app(test_config=None):
    """Create and return the Flask application. Accepts optional test_config dict.

    If test_config is provided it will be applied to the app config (useful for tests).
    """
    app = Flask(__name__, template_folder='templates')

    # Default config
    # Persist data to a single SQLite file named inventory.db in the project root
    project_root = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(project_root, 'inventory.db')
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('FLASK_SECRET', 'dev-secret'),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    if test_config:
        app.config.update(test_config)

    db.init_app(app)

    # Ensure database tables exist. Using an application context directly
    # so this works consistently across Flask versions and in tests.
    with app.app_context():
        db.create_all()

        # Try to ensure the 'remaining' column exists. If ALTER fails, fall back to safe mode.
        try:
            res = db.session.execute(text("PRAGMA table_info(purchase)")).fetchall()
            cols = [r[1] for r in res]
            if 'remaining' not in cols:
                # Add the column
                db.session.execute(text("ALTER TABLE purchase ADD COLUMN remaining INTEGER"))
                db.session.commit()
                # Initialize remaining = quantity for existing rows
                db.session.execute(text("UPDATE purchase SET remaining = quantity"))
                db.session.commit()
                app.config['HAS_REMAINING'] = True
            else:
                app.config['HAS_REMAINING'] = True
        except Exception as exc:
            # If we can't add the column, log and continue in compatibility mode
            print('Warning: could not ensure purchase.remaining column exists:', exc)
            app.config['HAS_REMAINING'] = False

        # Ensure product.category_id exists for category mapping and new fields
        try:
            res = db.session.execute(text("PRAGMA table_info(product)")).fetchall()
            pcols = [r[1] for r in res]
            if 'category_id' not in pcols:
                db.session.execute(text("ALTER TABLE product ADD COLUMN category_id INTEGER"))
                db.session.commit()
            if 'unit' not in pcols:
                db.session.execute(text("ALTER TABLE product ADD COLUMN unit VARCHAR(30)"))
                db.session.commit()
            if 'code' not in pcols:
                db.session.execute(text("ALTER TABLE product ADD COLUMN code VARCHAR(20)"))
                db.session.commit()
        except Exception as exc:
            print('Warning: could not ensure product.category_id column exists:', exc)

    # Load current user for requests and templates
    @app.before_request
    def load_current_user():
        user_id = session.get('user_id')
        g.current_user = None
        if user_id is not None:
            try:
                g.current_user = db.session.get(User, user_id)
            except Exception:
                g.current_user = None

    @app.context_processor
    def inject_user():
        return {'current_user': g.get('current_user', None)}

    def login_required(fn):
        from functools import wraps

        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('user_id'):
                flash('You must be logged in to access that page.')
                return redirect(url_for('login'))
            return fn(*args, **kwargs)

        return wrapped

    # No admin or page-permission decorators (removed)

    @app.route('/')
    @login_required
    def home():
        total_products = Product.query.count()

        total_value = 0.0
        if app.config.get('HAS_REMAINING'):
            # Use remaining column
            for purchase in Purchase.query.filter(Purchase.remaining > 0).all():
                total_value += (purchase.remaining or 0) * (purchase.price or 0.0)
        else:
            # Fallback: use quantity as remaining (no per-batch tracking available)
            rows = db.session.execute(text("SELECT quantity, price FROM purchase")).fetchall()
            for qty, price in rows:
                total_value += (qty or 0) * (price or 0.0)

        # Fetch products for dashboard table
        items = Product.query.order_by(Product.id).all()
        return render_template('home.html', total_products=total_products, total_value=total_value, products=items)

    @app.route('/signup', methods=['GET', 'POST'])
    def signup():
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            if not username or not password:
                flash('Username and password are required.')
                return redirect(url_for('signup'))

            if User.query.filter_by(username=username).first():
                flash('Username already exists.')
                return redirect(url_for('signup'))

            user = User(username=username)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('Account created successfully. Please log in.')
            return redirect(url_for('login'))

        return render_template('signup.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                session.clear()
                session['user_id'] = user.id
                return redirect(url_for('home'))
            flash('Invalid username or password.')
            return redirect(url_for('login'))

        return render_template('login.html')

    @app.route('/logout')
    def logout():
        session.clear()
        flash('You have been logged out.')
        return redirect(url_for('home'))

    # Product CRUD
    @app.route('/products')
    @login_required
    def products():
        items = Product.query.order_by(Product.name).all()
        return render_template('products.html', products=items)

    @app.route('/products/add', methods=['GET', 'POST'])
    @login_required
    def add_product():
        categories = ProductCategory.query.order_by(ProductCategory.name).all()
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            category = request.form.get('category', '').strip()
            try:
                category_id = int(request.form.get('category_id')) if request.form.get('category_id') else None
            except ValueError:
                category_id = None
            unit = request.form.get('unit', '').strip() or None
            try:
                quantity = int(request.form.get('quantity', '0'))
            except ValueError:
                quantity = 0
            try:
                price = float(request.form.get('price', '0'))
            except ValueError:
                price = 0.0
            try:
                reorder_level = int(request.form.get('reorder_level', '0'))
            except ValueError:
                reorder_level = 0

            if not name:
                flash('Product name is required.')
                return redirect(url_for('add_product'))

            # Auto-generate product code like P01, P02, ... using max existing numeric suffix
            existing_codes = [row[0] for row in db.session.query(Product.code).filter(Product.code.isnot(None)).all()]
            numeric_vals = []
            for c in existing_codes:
                try:
                    if c and c.startswith('P') and c[1:].isdigit():
                        numeric_vals.append(int(c[1:]))
                except Exception:
                    continue
            next_num = (max(numeric_vals) + 1) if numeric_vals else 1
            # Format: P01..P09, then P10, P11, ...
            code_val = f"P{next_num:02d}" if next_num < 100 else f"P{next_num}"
            # Ensure uniqueness in unlikely collision
            while db.session.query(Product.id).filter_by(code=code_val).first() is not None:
                next_num += 1
                code_val = f"P{next_num:02d}" if next_num < 100 else f"P{next_num}"

            p = Product(code=code_val, name=name, category=category, category_id=category_id, unit=unit, quantity=quantity, price=price, reorder_level=reorder_level)
            db.session.add(p)
            db.session.commit()
            flash('Product added.')
            return redirect(url_for('products'))

        return render_template('product_form.html', product=None, categories=categories)

    @app.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_product(product_id):
        p = db.session.get(Product, product_id)
        if p is None:
            abort(404)
        categories = ProductCategory.query.order_by(ProductCategory.name).all()
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            category = request.form.get('category', '').strip()
            try:
                category_id = int(request.form.get('category_id')) if request.form.get('category_id') else None
            except ValueError:
                category_id = p.category_id
            unit = request.form.get('unit', '').strip() or p.unit
            try:
                quantity = int(request.form.get('quantity', '0'))
            except ValueError:
                quantity = p.quantity
            try:
                price = float(request.form.get('price', '0'))
            except ValueError:
                price = p.price
            try:
                reorder_level = int(request.form.get('reorder_level', '0'))
            except ValueError:
                reorder_level = p.reorder_level

            if not name:
                flash('Product name is required.')
                return redirect(url_for('edit_product', product_id=product_id))

            p.name = name
            p.category = category
            p.category_id = category_id
            p.unit = unit
            p.quantity = quantity
            p.price = price
            p.reorder_level = reorder_level
            db.session.commit()
            flash('Product updated.')
            return redirect(url_for('products'))

        return render_template('product_form.html', product=p, categories=categories)

    # Categories (Master Data)
    @app.route('/categories')
    @login_required
    def categories():
        items = ProductCategory.query.order_by(ProductCategory.name).all()
        return render_template('categories.html', categories=items)

    @app.route('/categories/add', methods=['GET', 'POST'])
    @login_required
    def add_category():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            if not name:
                flash('Category name is required.')
                return redirect(url_for('add_category'))
            if ProductCategory.query.filter_by(name=name).first():
                flash('Category name already exists.')
                return redirect(url_for('add_category'))
            c = ProductCategory(name=name, description=description)
            db.session.add(c)
            db.session.commit()
            flash('Category added.')
            return redirect(url_for('categories'))
        return render_template('category_form.html', category=None)

    @app.route('/categories/<int:category_id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_category(category_id):
        c = db.session.get(ProductCategory, category_id)
        if c is None:
            abort(404)
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            if not name:
                flash('Category name is required.')
                return redirect(url_for('edit_category', category_id=category_id))
            # Ensure unique name (exclude self)
            exists = ProductCategory.query.filter(ProductCategory.name == name, ProductCategory.id != c.id).first()
            if exists:
                flash('Another category with that name already exists.')
                return redirect(url_for('edit_category', category_id=category_id))
            c.name = name
            c.description = description
            db.session.commit()
            flash('Category updated.')
            return redirect(url_for('categories'))
        return render_template('category_form.html', category=c)

    @app.route('/categories/<int:category_id>/delete', methods=['POST'])
    @login_required
    def delete_category(category_id):
        c = db.session.get(ProductCategory, category_id)
        if c is None:
            abort(404)
        # Prevent delete if products map to this category
        in_use = Product.query.filter_by(category_id=c.id).first()
        if in_use:
            flash('Cannot delete category: products are assigned to it.')
            return redirect(url_for('categories'))
        db.session.delete(c)
        db.session.commit()
        flash('Category deleted.')
        return redirect(url_for('categories'))

    @app.route('/products/<int:product_id>/delete', methods=['POST'])
    @login_required
    def delete_product(product_id):
        p = db.session.get(Product, product_id)
        if p is None:
            abort(404)
        db.session.delete(p)
        db.session.commit()
        flash('Product deleted.')
        return redirect(url_for('products'))

    # Purchases
    @app.route('/purchases')
    @login_required
    def purchases():
        items = Purchase.query.order_by(Purchase.timestamp.desc()).all()
        return render_template('purchases.html', purchases=items)

    @app.route('/master-data')
    @login_required
    def master_data():
        # Placeholder master data management page
        return render_template('master_data.html')

    # Admin functionality removed

    @app.route('/purchases/add', methods=['GET', 'POST'])
    @login_required
    def add_purchase():
        products = Product.query.order_by(Product.name).all()
        if request.method == 'POST':
            product_id = int(request.form.get('product_id'))
            try:
                quantity = int(request.form.get('quantity', '0'))
            except ValueError:
                quantity = 0
            try:
                price = float(request.form.get('price', '0'))
            except ValueError:
                price = 0.0

            if quantity <= 0:
                flash('Quantity must be positive.')
                return redirect(url_for('add_purchase'))

            product = db.session.get(Product, product_id)
            if product is None:
                abort(404)
            if app.config.get('HAS_REMAINING'):
                purchase = Purchase(product_id=product.id, quantity=quantity, remaining=quantity, price=price)
                db.session.add(purchase)
            else:
                # Insert without remaining column using raw SQL
                db.session.execute(
                    text("INSERT INTO purchase (product_id, quantity, price, timestamp) VALUES (:pid, :qty, :price, CURRENT_TIMESTAMP)"),
                    {"pid": product.id, "qty": quantity, "price": price},
                )

            product.quantity = product.quantity + quantity
            db.session.commit()
            flash('Purchase recorded')
            return redirect(url_for('purchases'))

        return render_template('purchase_form.html', products=products)

    # Sales
    @app.route('/sales')
    @login_required
    def sales():
        items = Sale.query.order_by(Sale.timestamp.desc()).all()
        return render_template('sales.html', sales=items)

    @app.route('/sales/add', methods=['GET', 'POST'])
    @login_required
    def add_sale():
        products = Product.query.order_by(Product.name).all()
        if request.method == 'POST':
            product_id = int(request.form.get('product_id'))
            try:
                quantity = int(request.form.get('quantity', '0'))
            except ValueError:
                quantity = 0
            try:
                price = float(request.form.get('price', '0'))
            except ValueError:
                price = 0.0

            if quantity <= 0:
                flash('Quantity must be positive.')
                return redirect(url_for('add_sale'))

            product = db.session.get(Product, product_id)
            if product is None:
                abort(404)
            if quantity > product.quantity:
                flash('Not enough stock for this sale.')
                return redirect(url_for('add_sale'))

            if app.config.get('HAS_REMAINING'):
                # Check total remaining across batches
                total_remaining = db.session.query(db.func.coalesce(db.func.sum(Purchase.remaining), 0)).filter(Purchase.product_id == product.id).scalar() or 0
                if total_remaining >= quantity:
                    # Consume purchase batches FIFO
                    remaining_to_consume = quantity
                    with db.session.begin_nested():
                        purchases = (
                            Purchase.query.filter_by(product_id=product.id)
                            .filter(Purchase.remaining > 0)
                            .order_by(Purchase.timestamp.asc())
                            .all()
                        )
                        for p_batch in purchases:
                            if remaining_to_consume <= 0:
                                break
                            take = min(p_batch.remaining, remaining_to_consume)
                            p_batch.remaining = p_batch.remaining - take
                            remaining_to_consume -= take

                        sale = Sale(product_id=product.id, quantity=quantity, price=price)
                        db.session.add(sale)
                        product.quantity = product.quantity - quantity
                    db.session.commit()
                    flash('Sale recorded')
                else:
                    # Not enough batch-tracked stock; fall back to using product.quantity if available
                    if product.quantity >= quantity:
                        # Record sale without consuming batches
                        sale = Sale(product_id=product.id, quantity=quantity, price=price)
                        db.session.add(sale)
                        product.quantity = product.quantity - quantity
                        db.session.commit()
                        flash('Sale recorded')
                    else:
                        flash('Not enough stock for this sale.')
                        return redirect(url_for('add_sale'))
            else:
                # Fallback: no batch tracking, just record sale and decrement product quantity
                db.session.execute(
                    text("INSERT INTO sale (product_id, quantity, price, timestamp) VALUES (:pid, :qty, :price, CURRENT_TIMESTAMP)"),
                    {"pid": product.id, "qty": quantity, "price": price},
                )
                product.quantity = product.quantity - quantity
                db.session.commit()
                flash('Sale recorded')
            return redirect(url_for('sales'))

        return render_template('sale_form.html', products=products)

    # Product Master (minimal fields only)
    @app.route('/product-master')
    @login_required
    def product_master():
        items = Product.query.order_by(Product.name.asc()).all()
        return render_template('product_master.html', products=items)

    @app.route('/product-master/add', methods=['GET', 'POST'])
    @login_required
    def add_product_master():
        categories = ProductCategory.query.order_by(ProductCategory.name).all()
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            try:
                category_id = int(request.form.get('category_id')) if request.form.get('category_id') else None
            except ValueError:
                category_id = None
            unit = request.form.get('unit', '').strip() or None
            try:
                reorder_level = int(request.form.get('reorder_level', '0'))
            except ValueError:
                reorder_level = 0

            if not name:
                flash('Product name is required.')
                return redirect(url_for('add_product_master'))

            # Auto-generate code similar to /products/add
            existing_codes = [row[0] for row in db.session.query(Product.code).filter(Product.code.isnot(None)).all()]
            numeric_vals = []
            for c in existing_codes:
                try:
                    if c and c.startswith('P') and c[1:].isdigit():
                        numeric_vals.append(int(c[1:]))
                except Exception:
                    continue
            next_num = (max(numeric_vals) + 1) if numeric_vals else 1
            code_val = f"P{next_num:02d}" if next_num < 100 else f"P{next_num}"
            while db.session.query(Product.id).filter_by(code=code_val).first() is not None:
                next_num += 1
                code_val = f"P{next_num:02d}" if next_num < 100 else f"P{next_num}"

            # Set legacy text category to keep compatible (optional)
            legacy_cat = None
            if category_id:
                cat = db.session.get(ProductCategory, category_id)
                legacy_cat = cat.name if cat else None

            p = Product(code=code_val, name=name, category_id=category_id, category=legacy_cat, unit=unit, reorder_level=reorder_level)
            db.session.add(p)
            db.session.commit()
            flash('Product saved to master.')
            return redirect(url_for('product_master'))
        return render_template('product_master_form.html', product=None, categories=categories)

    @app.route('/product-master/<int:product_id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_product_master(product_id):
        p = db.session.get(Product, product_id)
        if p is None:
            abort(404)
        categories = ProductCategory.query.order_by(ProductCategory.name).all()
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            try:
                category_id = int(request.form.get('category_id')) if request.form.get('category_id') else None
            except ValueError:
                category_id = p.category_id
            unit = request.form.get('unit', '').strip() or p.unit
            try:
                reorder_level = int(request.form.get('reorder_level', str(p.reorder_level or 0)))
            except ValueError:
                reorder_level = p.reorder_level
            if not name:
                flash('Product name is required.')
                return redirect(url_for('edit_product_master', product_id=product_id))

            legacy_cat = None
            if category_id:
                cat = db.session.get(ProductCategory, category_id)
                legacy_cat = cat.name if cat else None

            p.name = name
            p.category_id = category_id
            p.category = legacy_cat
            p.unit = unit
            p.reorder_level = reorder_level
            db.session.commit()
            flash('Product updated in master.')
            return redirect(url_for('product_master'))
        return render_template('product_master_form.html', product=p, categories=categories)

    # Reports & Dashboard
    @app.route('/reports')
    @login_required
    def reports():
        # Sales summaries
        total_sales_txns = db.session.query(db.func.count(Sale.id)).scalar() or 0
        total_sales_qty = db.session.query(db.func.coalesce(db.func.sum(Sale.quantity), 0)).scalar() or 0
        total_sales_amount = db.session.query(
            db.func.coalesce(db.func.sum(Sale.quantity * Sale.price), 0.0)
        ).scalar() or 0.0

        # Purchase summaries
        total_purchase_txns = db.session.query(db.func.count(Purchase.id)).scalar() or 0
        total_purchase_qty = db.session.query(db.func.coalesce(db.func.sum(Purchase.quantity), 0)).scalar() or 0
        total_purchase_cost = db.session.query(
            db.func.coalesce(db.func.sum(Purchase.quantity * Purchase.price), 0.0)
        ).scalar() or 0.0

        profit_loss = (total_sales_amount or 0.0) - (total_purchase_cost or 0.0)

        return render_template(
            'reports.html',
            total_sales_txns=total_sales_txns,
            total_sales_qty=total_sales_qty,
            total_sales_amount=total_sales_amount,
            total_purchase_txns=total_purchase_txns,
            total_purchase_qty=total_purchase_qty,
            total_purchase_cost=total_purchase_cost,
            profit_loss=profit_loss,
        )

    @app.route('/reports/sales')
    @login_required
    def reports_sales():
        return render_template('report_sales.html')

    @app.route('/reports/purchases')
    @login_required
    def reports_purchases():
        return render_template('report_purchases.html')

    @app.route('/reports/profit-loss')
    @login_required
    def reports_profit_loss():
        return render_template('report_profit_loss.html')

    return app


if __name__ == '__main__':
    create_app().run(debug=True, host='127.0.0.1', port=5000)
