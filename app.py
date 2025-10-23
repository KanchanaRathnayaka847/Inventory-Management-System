# Flask Inventory Management System
# This file contains the main Flask application with models, routes, and business logic

# Import necessary Flask components for web application functionality
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from flask import g  # Application context global object
from sqlalchemy import text  # For raw SQL queries
from flask_sqlalchemy import SQLAlchemy  # ORM for database operations
from werkzeug.security import generate_password_hash, check_password_hash  # Password security
from sqlalchemy import text  # Duplicate import (could be cleaned up)
import os  # Operating system interface

# Initialize SQLAlchemy database instance
# This will be configured and bound to the Flask app later
db = SQLAlchemy()

# ==================== DATABASE MODELS ====================

class User(db.Model):
    """
    User model for authentication and session management.
    Stores user credentials with secure password hashing.
    """
    id = db.Column(db.Integer, primary_key=True)  # Unique identifier for each user
    username = db.Column(db.String(80), unique=True, nullable=False)  # Username (must be unique)
    password_hash = db.Column(db.String(128), nullable=False)  # Hashed password for security

    def set_password(self, password):
        """
        Hash and store the user's password securely.
        Uses Werkzeug's generate_password_hash for security.
        """
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """
        Verify if provided password matches the stored hash.
        Returns True if password is correct, False otherwise.
        """
        return check_password_hash(self.password_hash, password)


class Product(db.Model):
    """
    Product model representing inventory items with operational details.
    Combines master data (from Product Master) with operational fields like quantity and price.
    """
    id = db.Column(db.Integer, primary_key=True)  # Unique product identifier
    code = db.Column(db.String(20), unique=True, index=True)  # Auto-generated product code (P01, P02, etc.)
    name = db.Column(db.String(120), nullable=False)  # Product name
    category = db.Column(db.String(80), nullable=True)  # Legacy string category field for backward compatibility
    # Optional FK to normalized category table (back-compat: keep string field too)
    category_id = db.Column(db.Integer, db.ForeignKey('product_category.id'), nullable=True)  # Link to ProductCategory
    unit = db.Column(db.String(30), nullable=True)  # Unit of measurement (kg, pcs, liters, etc.)
    quantity = db.Column(db.Integer, nullable=False, default=0)  # Current stock quantity
    price = db.Column(db.Float, nullable=False, default=0.0)  # Current unit price
    reorder_level = db.Column(db.Integer, nullable=False, default=0)  # Minimum stock level before reordering
    category_rel = db.relationship('ProductCategory', lazy='joined')  # Relationship to category table


class ProductCategory(db.Model):
    """
    Master data model for product categories.
    Used to normalize and organize products into logical groups.
    """
    id = db.Column(db.Integer, primary_key=True)  # Unique category identifier
    name = db.Column(db.String(120), unique=True, nullable=False)  # Category name (must be unique)
    description = db.Column(db.String(255), nullable=True)  # Optional category description


class Purchase(db.Model):
    """
    Purchase transaction model for recording inventory purchases.
    Implements FIFO (First In, First Out) inventory management using 'remaining' field.
    """
    id = db.Column(db.Integer, primary_key=True)  # Unique purchase transaction ID
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)  # Link to product
    quantity = db.Column(db.Integer, nullable=False)  # Original purchased quantity
    remaining = db.Column(db.Integer, nullable=False)  # Remaining quantity (for FIFO consumption)
    price = db.Column(db.Float, nullable=False)  # Purchase price per unit
    timestamp = db.Column(db.DateTime, server_default=db.func.now())  # Purchase date/time
    product = db.relationship('Product')  # Relationship to access product details


class Sale(db.Model):
    """
    Sales transaction model for recording inventory sales.
    Works with Purchase model to implement FIFO consumption of inventory.
    """
    id = db.Column(db.Integer, primary_key=True)  # Unique sale transaction ID
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)  # Link to product sold
    quantity = db.Column(db.Integer, nullable=False)  # Quantity sold
    price = db.Column(db.Float, nullable=False)  # Sale price per unit
    timestamp = db.Column(db.DateTime, server_default=db.func.now())  # Sale date/time
    product = db.relationship('Product')  # Relationship to access product details


# ==================== APPLICATION FACTORY ====================

def create_app(test_config=None):
    """
    Application factory function that creates and configures the Flask application.
    
    Args:
        test_config (dict, optional): Configuration dictionary for testing.
                                    If provided, overrides default config settings.
    
    Returns:
        Flask: Configured Flask application instance ready to run.
    """
    # Create Flask application instance with template folder configuration
    app = Flask(__name__, template_folder='templates')

    # ==================== APPLICATION CONFIGURATION ====================
    # Default configuration settings for the application
    # SQLite database will be stored in the project root directory
    project_root = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(project_root, 'inventory.db')
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('FLASK_SECRET', 'dev-secret'),  # Secret key for sessions (use env var in production)
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",  # SQLite database file path
        SQLALCHEMY_TRACK_MODIFICATIONS=False,  # Disable modification tracking for performance
    )

    # Override config with test settings if provided (useful for unit tests)
    if test_config:
        app.config.update(test_config)

    # Initialize SQLAlchemy with the Flask app
    db.init_app(app)

    # ==================== DATABASE INITIALIZATION ====================
    # Ensure database tables exist and handle schema migrations
    # Using application context to ensure database operations work correctly
    with app.app_context():
        # Create all database tables defined in the models
        db.create_all()

        # *** SCHEMA MIGRATION: Ensure 'remaining' column exists in purchase table ***
        # This column is crucial for FIFO inventory management
        # Try to ensure the 'remaining' column exists. If ALTER fails, fall back to safe mode.
        try:
            # Check if 'remaining' column exists in purchase table
            res = db.session.execute(text("PRAGMA table_info(purchase)")).fetchall()
            cols = [r[1] for r in res]  # Extract column names
            if 'remaining' not in cols:
                # Add the missing column for FIFO functionality
                db.session.execute(text("ALTER TABLE purchase ADD COLUMN remaining INTEGER"))
                db.session.commit()
                # Initialize remaining = quantity for existing purchase records
                db.session.execute(text("UPDATE purchase SET remaining = quantity"))
                db.session.commit()
                app.config['HAS_REMAINING'] = True  # Flag that FIFO is supported
            else:
                app.config['HAS_REMAINING'] = True  # Column already exists
        except Exception as exc:
            # If schema migration fails, continue in compatibility mode without FIFO
            print('Warning: could not ensure purchase.remaining column exists:', exc)
            app.config['HAS_REMAINING'] = False

        # *** SCHEMA MIGRATION: Ensure additional product columns exist ***
        # These columns were added in later versions for enhanced functionality
        try:
            res = db.session.execute(text("PRAGMA table_info(product)")).fetchall()
            pcols = [r[1] for r in res]  # Get existing column names
            
            # Add category_id column for linking to ProductCategory table
            if 'category_id' not in pcols:
                db.session.execute(text("ALTER TABLE product ADD COLUMN category_id INTEGER"))
                db.session.commit()
            
            # Add unit column for measurement units (kg, pcs, liters, etc.)
            if 'unit' not in pcols:
                db.session.execute(text("ALTER TABLE product ADD COLUMN unit VARCHAR(30)"))
                db.session.commit()
            
            # Add code column for auto-generated product IDs (P01, P02, etc.)
            if 'code' not in pcols:
                db.session.execute(text("ALTER TABLE product ADD COLUMN code VARCHAR(20)"))
                db.session.commit()
        except Exception as exc:
            print('Warning: could not ensure product columns exist:', exc)

    # ==================== AUTHENTICATION & SESSION MANAGEMENT ====================
    
    @app.before_request
    def load_current_user():
        """
        Load the current user from session before each request.
        Makes user object available in request context (g.current_user).
        """
        user_id = session.get('user_id')  # Get user ID from session
        g.current_user = None  # Default to no user
        if user_id is not None:
            try:
                # Fetch user from database by ID
                g.current_user = db.session.get(User, user_id)
            except Exception:
                # Handle database errors gracefully
                g.current_user = None

    @app.context_processor
    def inject_user():
        """
        Make current_user available in all Jinja2 templates.
        This allows templates to check authentication status and show user info.
        """
        return {'current_user': g.get('current_user', None)}

    def login_required(fn):
        """
        Decorator to protect routes that require authentication.
        Redirects unauthenticated users to login page with flash message.
        
        Usage:
            @login_required
            def protected_route():
                # This route requires authentication
                pass
        """
        from functools import wraps

        @wraps(fn)
        def wrapped(*args, **kwargs):
            # Check if user is logged in (has user_id in session)
            if not session.get('user_id'):
                flash('You must be logged in to access that page.')
                return redirect(url_for('login'))
            # User is authenticated, proceed with original function
            return fn(*args, **kwargs)

        return wrapped

    # ==================== MAIN APPLICATION ROUTES ====================

    @app.route('/')
    @login_required
    def home():
        """
        Home dashboard route - displays company overview and product inventory status.
        Shows total products count, inventory valuation, and detailed product table.
        Requires user authentication to access.
        """
        # Calculate basic statistics for dashboard
        total_products = Product.query.count()

        # Calculate total inventory value using FIFO method (if supported)
        total_value = 0.0
        if app.config.get('HAS_REMAINING'):
            # Use 'remaining' column for accurate FIFO valuation
            # Sum up value of all unsold inventory batches at their purchase prices
            for purchase in Purchase.query.filter(Purchase.remaining > 0).all():
                total_value += (purchase.remaining or 0) * (purchase.price or 0.0)
        else:
            # Fallback: use simple quantity-based calculation (less accurate)
            # This mode is used when schema migration failed
            rows = db.session.execute(text("SELECT quantity, price FROM purchase")).fetchall()
            for qty, price in rows:
                total_value += (qty or 0) * (price or 0.0)

        # Fetch all products for the dashboard table with category information
        # Order by ID to maintain consistent display order
        items = Product.query.order_by(Product.id).all()
        return render_template('home.html', total_products=total_products, total_value=total_value, products=items)

    # ==================== AUTHENTICATION ROUTES ====================

    @app.route('/signup', methods=['GET', 'POST'])
    def signup():
        """
        User registration route.
        GET: Display signup form
        POST: Process new user registration with validation
        """
        if request.method == 'POST':
            # Extract and validate form data
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            
            # Basic validation
            if not username or not password:
                flash('Username and password are required.')
                return redirect(url_for('signup'))

            # Check if username already exists
            if User.query.filter_by(username=username).first():
                flash('Username already exists.')
                return redirect(url_for('signup'))

            # Create new user with hashed password
            user = User(username=username)
            user.set_password(password)  # This hashes the password securely
            db.session.add(user)
            db.session.commit()
            
            flash('Account created successfully. Please log in.')
            return redirect(url_for('login'))

        # GET request - show signup form
        return render_template('signup.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """
        User login route.
        GET: Display login form
        POST: Authenticate user and create session
        """
        if request.method == 'POST':
            # Extract credentials from form
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            
            # Find user and verify password
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                # Authentication successful - create session
                session.clear()  # Clear any existing session data
                session['user_id'] = user.id  # Store user ID in session
                return redirect(url_for('home'))  # Redirect to home dashboard
            
            # Authentication failed
            flash('Invalid username or password.')
            return redirect(url_for('login'))

        # GET request - show login form
        return render_template('login.html')

    @app.route('/logout')
    def logout():
        """
        User logout route.
        Clears the user session and redirects to home page.
        """
        session.clear()  # Remove all session data
        flash('You have been logged out.')
        return redirect(url_for('home'))

    # ==================== PRODUCT MANAGEMENT ROUTES ====================

    @app.route('/products')
    @login_required
    def products():
        """
        Display list of all products with operational details.
        This route is hidden from sidebar but accessible directly.
        Used for administrative product management.
        """
        items = Product.query.order_by(Product.name).all()  # Order alphabetically
        return render_template('products.html', products=items)

    @app.route('/products/add', methods=['GET', 'POST'])
    @login_required
    def add_product():
        """
        Add new product with operational details.
        GET: Show product creation form with category dropdown
        POST: Create new product with auto-generated code and validation
        """
        # Get categories for dropdown selection
        categories = ProductCategory.query.order_by(ProductCategory.name).all()
        
        if request.method == 'POST':
            # Extract form data
            name = request.form.get('name', '').strip()
            category = request.form.get('category', '').strip()  # Legacy string category
            
            try:
                # Parse category_id from form (links to ProductCategory table)
                category_id = int(request.form.get('category_id')) if request.form.get('category_id') else None
            except ValueError:
                category_id = None
            
            # Extract other form fields with error handling
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

            # Validate required fields
            if not name:
                flash('Product name is required.')
                return redirect(url_for('add_product'))

            # *** AUTO-GENERATE PRODUCT CODE ***
            # Generate sequential product codes like P01, P02, P03, etc.
            # Find the highest existing numeric suffix and increment by 1
            existing_codes = [row[0] for row in db.session.query(Product.code).filter(Product.code.isnot(None)).all()]
            numeric_vals = []
            for c in existing_codes:
                try:
                    # Check if code follows pattern P + digits (e.g., P01, P123)
                    if c and c.startswith('P') and c[1:].isdigit():
                        numeric_vals.append(int(c[1:]))  # Extract numeric part
                except Exception:
                    continue  # Skip invalid codes
            
            # Calculate next sequential number
            next_num = (max(numeric_vals) + 1) if numeric_vals else 1
            
            # Format product code with zero-padding for numbers < 100
            code_val = f"P{next_num:02d}" if next_num < 100 else f"P{next_num}"
            
            # Ensure uniqueness in case of unlikely collision
            while db.session.query(Product.id).filter_by(code=code_val).first() is not None:
                next_num += 1
                code_val = f"P{next_num:02d}" if next_num < 100 else f"P{next_num}"

            # Create new product with all provided data and auto-generated code
            p = Product(
                code=code_val, 
                name=name, 
                category=category,  # Legacy string field 
                category_id=category_id,  # FK to ProductCategory
                unit=unit, 
                quantity=quantity, 
                price=price, 
                reorder_level=reorder_level
            )
            db.session.add(p)
            db.session.commit()
            flash('Product added.')
            return redirect(url_for('products'))

        # GET request - show form
        return render_template('product_form.html', product=None, categories=categories)

    @app.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_product(product_id):
        """
        Edit existing product details.
        GET: Show edit form pre-filled with current data
        POST: Update product with new data and validation
        """
        # Fetch product or return 404 if not found
        p = db.session.get(Product, product_id)
        if p is None:
            abort(404)
        
        # Get categories for dropdown
        categories = ProductCategory.query.order_by(ProductCategory.name).all()
        
        if request.method == 'POST':
            # Extract form data with error handling
            name = request.form.get('name', '').strip()
            category = request.form.get('category', '').strip()
            
            try:
                category_id = int(request.form.get('category_id')) if request.form.get('category_id') else None
            except ValueError:
                category_id = p.category_id  # Keep existing value on error
            
            # Parse other fields with fallbacks to existing values
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

            # Validate required fields
            if not name:
                flash('Product name is required.')
                return redirect(url_for('edit_product', product_id=product_id))

            # Update product with new values
            p.name = name
            p.category = category  # Legacy string field
            p.category_id = category_id  # FK to ProductCategory
            p.unit = unit
            p.quantity = quantity
            p.price = price
            p.reorder_level = reorder_level
            
            db.session.commit()
            flash('Product updated.')
            return redirect(url_for('products'))

        # GET request - show edit form with current data
        return render_template('product_form.html', product=p, categories=categories)

    # ==================== MASTER DATA MANAGEMENT ROUTES ====================

    @app.route('/categories')
    @login_required
    def categories():
        """
        Display list of all product categories (master data).
        Categories are used to organize and classify products.
        """
        items = ProductCategory.query.order_by(ProductCategory.name).all()
        return render_template('categories.html', categories=items)

    @app.route('/categories/add', methods=['GET', 'POST'])
    @login_required
    def add_category():
        """
        Create new product category (master data).
        GET: Show category creation form
        POST: Validate and create new category with uniqueness check
        """
        if request.method == 'POST':
            # Extract form data
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            
            # Validate required fields
            if not name:
                flash('Category name is required.')
                return redirect(url_for('add_category'))
            
            # Check for duplicate category name
            if ProductCategory.query.filter_by(name=name).first():
                flash('Category name already exists.')
                return redirect(url_for('add_category'))
            
            # Create new category
            c = ProductCategory(name=name, description=description)
            db.session.add(c)
            db.session.commit()
            flash('Category added.')
            return redirect(url_for('categories'))
        
        # GET request - show form
        return render_template('category_form.html', category=None)

    @app.route('/categories/<int:category_id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_category(category_id):
        """
        Edit existing product category.
        GET: Show edit form with current data
        POST: Update category with validation and uniqueness check
        """
        # Fetch category or return 404
        c = db.session.get(ProductCategory, category_id)
        if c is None:
            abort(404)
        
        if request.method == 'POST':
            # Extract form data
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            
            # Validate required fields
            if not name:
                flash('Category name is required.')
                return redirect(url_for('edit_category', category_id=category_id))
            
            # Ensure unique name (exclude current category from check)
            exists = ProductCategory.query.filter(ProductCategory.name == name, ProductCategory.id != c.id).first()
            if exists:
                flash('Another category with that name already exists.')
                return redirect(url_for('edit_category', category_id=category_id))
            
            # Update category
            c.name = name
            c.description = description
            db.session.commit()
            flash('Category updated.')
            return redirect(url_for('categories'))
        
        # GET request - show edit form
        return render_template('category_form.html', category=c)

    @app.route('/categories/<int:category_id>/delete', methods=['POST'])
    @login_required
    def delete_category(category_id):
        """
        Delete product category with referential integrity check.
        Prevents deletion if any products are assigned to this category.
        """
        # Fetch category or return 404
        c = db.session.get(ProductCategory, category_id)
        if c is None:
            abort(404)
        
        # Prevent deletion if products are using this category
        in_use = Product.query.filter_by(category_id=c.id).first()
        if in_use:
            flash('Cannot delete category: products are assigned to it.')
            return redirect(url_for('categories'))
        
        # Safe to delete
        db.session.delete(c)
        db.session.commit()
        flash('Category deleted.')
        return redirect(url_for('categories'))

    @app.route('/products/<int:product_id>/delete', methods=['POST'])
    @login_required
    def delete_product(product_id):
        """
        Delete product from inventory.
        Note: This will also remove associated purchase/sale history.
        """
        # Fetch product or return 404
        p = db.session.get(Product, product_id)
        if p is None:
            abort(404)
        
        # Delete product (cascading deletes handled by database)
        db.session.delete(p)
        db.session.commit()
        flash('Product deleted.')
        return redirect(url_for('products'))

    # ==================== INVENTORY TRANSACTION ROUTES ====================

    @app.route('/purchases')
    @login_required
    def purchases():
        """
        Display list of all purchase transactions.
        Shows purchase history ordered by most recent first.
        """
        items = Purchase.query.order_by(Purchase.timestamp.desc()).all()
        return render_template('purchases.html', purchases=items)

    @app.route('/master-data')
    @login_required
    def master_data():
        """
        Master data management hub page.
        Provides navigation to Product Categories and Product Master management.
        """
        return render_template('master_data.html')

    @app.route('/purchases/add', methods=['GET', 'POST'])
    @login_required
    def add_purchase():
        """
        Add new purchase transaction to inventory.
        GET: Show purchase form with product dropdown
        POST: Create purchase record and update product quantity using FIFO logic
        """
        # Get products for dropdown selection
        products = Product.query.order_by(Product.name).all()
        
        if request.method == 'POST':
            # Extract and validate form data
            product_id = int(request.form.get('product_id'))
            try:
                quantity = int(request.form.get('quantity', '0'))
            except ValueError:
                quantity = 0
            try:
                price = float(request.form.get('price', '0'))
            except ValueError:
                price = 0.0

            # Validate purchase quantity
            if quantity <= 0:
                flash('Quantity must be positive.')
                return redirect(url_for('add_purchase'))

            # Get product to update inventory
            product = db.session.get(Product, product_id)
            if product is None:
                abort(404)
            
            # *** FIFO INVENTORY MANAGEMENT ***
            # Create purchase record with remaining quantity for FIFO tracking
            if app.config.get('HAS_REMAINING'):
                # Schema supports FIFO - create purchase with remaining field
                purchase = Purchase(product_id=product.id, quantity=quantity, remaining=quantity, price=price)
                db.session.add(purchase)
            else:
                # Fallback mode - create purchase without remaining field
                db.session.execute(
                    text("INSERT INTO purchase (product_id, quantity, price, timestamp) VALUES (:pid, :qty, :price, CURRENT_TIMESTAMP)"),
                    {"pid": product.id, "qty": quantity, "price": price},
                )

            # Update total product quantity (simple addition)
            product.quantity = product.quantity + quantity
            db.session.commit()
            flash('Purchase recorded')
            return redirect(url_for('purchases'))

        # GET request - show form
        return render_template('purchase_form.html', products=products)

    @app.route('/sales')
    @login_required
    def sales():
        """
        Display list of all sales transactions.
        Shows sales history ordered by most recent first.
        """
        items = Sale.query.order_by(Sale.timestamp.desc()).all()
        return render_template('sales.html', sales=items)

    @app.route('/sales/add', methods=['GET', 'POST'])
    @login_required
    def add_sale():
        """
        Process sales transaction with FIFO inventory consumption.
        GET: Show sales form with product dropdown
        POST: Create sale record and consume inventory using FIFO method
        """
        # Get products for dropdown selection
        products = Product.query.order_by(Product.name).all()
        
        if request.method == 'POST':
            # Extract and validate form data
            product_id = int(request.form.get('product_id'))
            try:
                quantity = int(request.form.get('quantity', '0'))
            except ValueError:
                quantity = 0
            try:
                price = float(request.form.get('price', '0'))
            except ValueError:
                price = 0.0

            # Validate sale quantity
            if quantity <= 0:
                flash('Quantity must be positive.')
                return redirect(url_for('add_sale'))

            # Get product and check availability
            product = db.session.get(Product, product_id)
            if product is None:
                abort(404)
            if quantity > product.quantity:
                flash('Not enough stock for this sale.')
                return redirect(url_for('add_sale'))

            # *** FIFO INVENTORY CONSUMPTION LOGIC ***
            if app.config.get('HAS_REMAINING'):
                # Advanced FIFO mode - consume from purchase batches in chronological order
                # Check total remaining across all purchase batches
                total_remaining = db.session.query(db.func.coalesce(db.func.sum(Purchase.remaining), 0)).filter(Purchase.product_id == product.id).scalar() or 0
                
                if total_remaining >= quantity:
                    # Sufficient batch-tracked inventory available
                    # Consume purchase batches in FIFO order (oldest first)
                    remaining_to_consume = quantity
                    with db.session.begin_nested():  # Nested transaction for atomicity
                        # Get purchase batches ordered by timestamp (FIFO)
                        purchases = (
                            Purchase.query.filter_by(product_id=product.id)
                            .filter(Purchase.remaining > 0)
                            .order_by(Purchase.timestamp.asc())  # Oldest first (FIFO)
                            .all()
                        )
                        
                        # Consume from each batch until sale quantity is satisfied
                        for p_batch in purchases:
                            if remaining_to_consume <= 0:
                                break  # Sale quantity fully consumed
                            
                            # Take what we can from this batch (up to remaining_to_consume)
                            take = min(p_batch.remaining, remaining_to_consume)
                            p_batch.remaining = p_batch.remaining - take
                            remaining_to_consume -= take

                        # Record the sale transaction
                        sale = Sale(product_id=product.id, quantity=quantity, price=price)
                        db.session.add(sale)
                        # Update total product quantity
                        product.quantity = product.quantity - quantity
                    
                    db.session.commit()
                    flash('Sale recorded')
                else:
                    # Not enough batch-tracked stock; fallback to simple quantity check
                    if product.quantity >= quantity:
                        # Record sale without consuming specific batches
                        sale = Sale(product_id=product.id, quantity=quantity, price=price)
                        db.session.add(sale)
                        product.quantity = product.quantity - quantity
                        db.session.commit()
                        flash('Sale recorded')
                    else:
                        flash('Not enough stock for this sale.')
                        return redirect(url_for('add_sale'))
            else:
                # Fallback mode: no batch tracking available
                # Simply record sale and decrement total product quantity
                db.session.execute(
                    text("INSERT INTO sale (product_id, quantity, price, timestamp) VALUES (:pid, :qty, :price, CURRENT_TIMESTAMP)"),
                    {"pid": product.id, "qty": quantity, "price": price},
                )
                product.quantity = product.quantity - quantity
                db.session.commit()
                flash('Sale recorded')
            
            return redirect(url_for('sales'))

        # GET request - show form
        return render_template('sale_form.html', products=products)

    # ==================== PRODUCT MASTER DATA ROUTES ====================

    @app.route('/product-master')
    @login_required
    def product_master():
        """
        Display Product Master data (minimal fields only).
        Used for managing product definitions separate from operational data.
        """
        items = Product.query.order_by(Product.name.asc()).all()
        return render_template('product_master.html', products=items)

    @app.route('/product-master/add', methods=['GET', 'POST'])
    @login_required
    def add_product_master():
        """
        Add new product through Product Master interface.
        Creates product with minimal master data fields and auto-generated code.
        """
        # Get categories for dropdown
        categories = ProductCategory.query.order_by(ProductCategory.name).all()
        
        if request.method == 'POST':
            # Extract master data fields only
            # Extract master data fields
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

            # Validate required fields
            if not name:
                flash('Product name is required.')
                return redirect(url_for('add_product_master'))

            # *** AUTO-GENERATE PRODUCT CODE (same logic as operational products) ***
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

            # Set legacy category text for backward compatibility
            legacy_cat = None
            if category_id:
                cat = db.session.get(ProductCategory, category_id)
                legacy_cat = cat.name if cat else None

            # Create product with master data only (no operational fields like quantity/price)
            p = Product(
                code=code_val, 
                name=name, 
                category_id=category_id, 
                category=legacy_cat, 
                unit=unit, 
                reorder_level=reorder_level
                # Note: quantity and price default to 0 (set via operational interface)
            )
            db.session.add(p)
            db.session.commit()
            flash('Product saved to master.')
            return redirect(url_for('product_master'))
        
        # GET request - show form
        return render_template('product_master_form.html', product=None, categories=categories)

    @app.route('/product-master/<int:product_id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_product_master(product_id):
        """
        Edit Product Master data (minimal fields only).
        Updates master data while preserving operational data like quantity and price.
        """
        # Fetch product or return 404
        p = db.session.get(Product, product_id)
        if p is None:
            abort(404)
        
        # Get categories for dropdown
        categories = ProductCategory.query.order_by(ProductCategory.name).all()
        
        if request.method == 'POST':
            # Extract form data with error handling
            name = request.form.get('name', '').strip()
            try:
                category_id = int(request.form.get('category_id')) if request.form.get('category_id') else None
            except ValueError:
                category_id = p.category_id  # Keep existing on error
            
            unit = request.form.get('unit', '').strip() or p.unit
            try:
                reorder_level = int(request.form.get('reorder_level', str(p.reorder_level or 0)))
            except ValueError:
                reorder_level = p.reorder_level
            
            # Validate required fields
            if not name:
                flash('Product name is required.')
                return redirect(url_for('edit_product_master', product_id=product_id))

            # Update legacy category text for compatibility
            legacy_cat = None
            if category_id:
                cat = db.session.get(ProductCategory, category_id)
                legacy_cat = cat.name if cat else None

            # Update master data fields only
            p.name = name
            p.category_id = category_id
            p.category = legacy_cat
            p.unit = unit
            p.reorder_level = reorder_level
            # Note: quantity and price are NOT updated here (operational data)
            
            db.session.commit()
            flash('Product updated in master.')
            return redirect(url_for('product_master'))
        
        # GET request - show edit form
        return render_template('product_master_form.html', product=p, categories=categories)

    # ==================== REPORTS & DASHBOARD ROUTES ====================

    @app.route('/reports')
    @login_required
    def reports():
        """
        Main Reports & Dashboard page with summary KPIs.
        Calculates and displays high-level business metrics for sales, purchases, and P&L.
        Provides navigation tiles to detailed report subpages.
        """
        # *** SALES SUMMARY CALCULATIONS ***
        total_sales_txns = db.session.query(db.func.count(Sale.id)).scalar() or 0
        total_sales_qty = db.session.query(db.func.coalesce(db.func.sum(Sale.quantity), 0)).scalar() or 0
        total_sales_amount = db.session.query(
            db.func.coalesce(db.func.sum(Sale.quantity * Sale.price), 0.0)
        ).scalar() or 0.0

        # *** PURCHASE SUMMARY CALCULATIONS ***
        total_purchase_txns = db.session.query(db.func.count(Purchase.id)).scalar() or 0
        total_purchase_qty = db.session.query(db.func.coalesce(db.func.sum(Purchase.quantity), 0)).scalar() or 0
        total_purchase_cost = db.session.query(
            db.func.coalesce(db.func.sum(Purchase.quantity * Purchase.price), 0.0)
        ).scalar() or 0.0

        # *** PROFIT & LOSS CALCULATION ***
        # Simple P&L = Total Sales Revenue - Total Purchase Cost
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
        """
        Detailed Sales Report page.
        Placeholder for sales analytics, charts, and detailed breakdowns.
        """
        return render_template('report_sales.html')

    @app.route('/reports/purchases')
    @login_required
    def reports_purchases():
        """
        Detailed Purchases Report page.
        Placeholder for purchase analytics, charts, and detailed breakdowns.
        """
        return render_template('report_purchases.html')

    @app.route('/reports/profit-loss')
    @login_required
    def reports_profit_loss():
        """
        Detailed Profit & Loss Report page.
        Placeholder for P&L analytics, charts, and financial breakdowns.
        """
        return render_template('report_profit_loss.html')

    # Return the configured Flask application
    return app


# ==================== APPLICATION ENTRY POINT ====================

if __name__ == '__main__':
    """
    Development server entry point.
    Creates and runs the Flask application with debug mode enabled.
    Only executes when this file is run directly (not imported).
    """
    create_app().run(debug=True, host='127.0.0.1', port=5000)
