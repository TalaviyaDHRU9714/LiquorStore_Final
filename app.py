import os  # Ensure this is at the top of app.py!
import os
import re
import random
from datetime import datetime
from sqlalchemy import inspect, text
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import pytesseract
from PIL import Image
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, abort

# IMPORTANT: Make sure all these are in your models.py file!
from models import db, User, Product, CartItem, Order, OrderItem

app = Flask(__name__)

# --- CONFIGURATION ---
app.config['SECRET_KEY'] = 'mca_final_project_2026_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///liquor_store.db'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# --- INITIALIZE EXTENSIONS ---
db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- AI OCR LOGIC (GUJARAT VERIFICATION) ---


def get_age_from_aadhaar(image_path):
    try:
        text = pytesseract.image_to_string(Image.open(image_path))
        date_pattern = r"(\d{2}/\d{2}/\d{4})"
        match = re.search(date_pattern, text)
        if match:
            dob = datetime.strptime(match.group(1), '%d/%m/%Y').date()
            today = datetime.today().date()
            age = today.year - dob.year - \
                ((today.month, today.day) < (dob.month, dob.day))
            return age
        return None
    except Exception as e:
        print(f"OCR Error: {e}")
        return None


def verify_gujarat_permit(image_path):
    try:
        text = pytesseract.image_to_string(Image.open(image_path)).lower()
        required_keywords = ['permit', 'gujarat',
                             'prohibition', 'health', 'visitor', 'tourist']
        match_count = sum(1 for word in required_keywords if word in text)
        return match_count >= 2
    except Exception as e:
        print(f"Permit OCR Error: {e}")
        return False


def verify_electricity_bill(image_path):
    try:
        text = pytesseract.image_to_string(Image.open(image_path)).lower()
        keywords = ['electricity', 'bill', 'torrent',
                    'pgvcl', 'ugvcl', 'dgvcl', 'mgvcl', 'energy']
        match_count = sum(1 for word in keywords if word in text)
        return match_count >= 1
    except Exception as e:
        print(f"Bill OCR Error: {e}")
        return False


def sanitize_digits(value):
    return re.sub(r'\D', '', value or '')


def is_valid_card_number(card_number):
    digits = sanitize_digits(card_number)
    if len(digits) < 13 or len(digits) > 19:
        return False

    # Luhn check for realistic card number validation
    total = 0
    reverse_digits = digits[::-1]
    for idx, d in enumerate(reverse_digits):
        n = int(d)
        if idx % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def is_valid_expiry(expiry):
    if not expiry:
        return False
    match = re.fullmatch(r'(\d{2})/(\d{2})', expiry.strip())
    if not match:
        return False
    month = int(match.group(1))
    year = int(match.group(2))
    if month < 1 or month > 12:
        return False

    now = datetime.now()
    current_year = now.year % 100
    current_month = now.month

    if year < current_year:
        return False
    if year == current_year and month < current_month:
        return False
    return True


def is_valid_cvv(cvv):
    return bool(re.fullmatch(r'\d{3,4}', cvv or ''))


def is_valid_mobile_number(phone):
    # Indian mobile format
    return bool(re.fullmatch(r'[6-9]\d{9}', sanitize_digits(phone)))


def clear_card_payment_session():
    session.pop('card_payment_otp', None)
    session.pop('card_payment_phone', None)
    session.pop('card_payment_phone_masked', None)
    session.pop('card_payment_cart_token', None)


def build_cart_token(cart_items, total_price):
    item_parts = [f"{item.product_id}:{item.quantity}" for item in cart_items]
    return f"{current_user.id}|{total_price:.2f}|{'|'.join(item_parts)}"


def render_checkout(total_price, otp_sent=False, masked_phone=None, form_data=None, selected_payment='Cash on Delivery'):
    return render_template(
        'checkout.html',
        total_price=total_price,
        otp_sent=otp_sent,
        masked_phone=masked_phone,
        form_data=form_data or {},
        selected_payment=selected_payment
    )


def place_order_and_generate_invoice(cart_items, total_price, payment_method):
    # 1. Create order
    new_order = Order(
        user_id=current_user.id,
        total_amount=total_price,
        payment_method=payment_method
    )
    db.session.add(new_order)
    db.session.commit()

    # 2. Build invoice text
    invoice_text = "====================================\n"
    invoice_text += "       OFFICIAL GUJARAT PERMIT ORDER \n"
    invoice_text += "====================================\n"
    invoice_text += f"Order ID: ORD-00{new_order.id}\n"
    invoice_text += f"Customer: {current_user.name}\n"
    invoice_text += f"Payment Method: {payment_method}\n"
    invoice_text += "Status: Verified & Approved\n"
    invoice_text += "------------------------------------\n"

    # 3. Move items from cart to order items
    for cart_item in cart_items:
        order_item = OrderItem(
            order_id=new_order.id,
            product_id=cart_item.product_id,
            quantity=cart_item.quantity,
            price_at_purchase=cart_item.product.price
        )
        db.session.add(order_item)

        invoice_text += f"{cart_item.quantity}x {cart_item.product.name} - ₹{cart_item.product.price * cart_item.quantity}\n"
        db.session.delete(cart_item)

    invoice_text += "------------------------------------\n"
    invoice_text += f"GRAND TOTAL: ₹{total_price}\n"
    invoice_text += "====================================\n"
    db.session.commit()

    # 4. Save invoice
    invoice_dir = os.path.join(app.root_path, 'invoices')
    if not os.path.exists(invoice_dir):
        os.makedirs(invoice_dir)

    file_path = os.path.join(
        invoice_dir, f"Admin_Invoice_ORD00{new_order.id}.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(invoice_text)

    return new_order


# --- SECURITY LOCK ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # If they aren't an admin, throw a 403 Forbidden Error
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# --- ROUTES ---


@app.route('/')
@app.route('/shop')
def shop():
    search_query = request.args.get('search', '')
    if search_query:
        search_results = Product.query.filter(
            Product.name.ilike(f'%{search_query}%')).all()
        return render_template('shop.html', search_results=search_results, search_query=search_query)

    all_products = Product.query.all()
    beers = [p for p in all_products if p.category.lower() == 'beer']
    wines = [p for p in all_products if p.category.lower() == 'wine']
    rums = [p for p in all_products if p.category.lower() == 'rum']
    tequilas = [p for p in all_products if p.category.lower() == 'tequila']
    vodkas = [p for p in all_products if p.category.lower() == 'vodka']
    gins = [p for p in all_products if p.category.lower() == 'gin']
    cognacs = [p for p in all_products if p.category.lower() == 'cognac']

    return render_template('shop.html',
                           beers=beers, wines=wines,
                           rums=rums, tequilas=tequilas,
                           vodkas=vodkas, gins=gins, cognacs=cognacs)


@app.route('/product/<int:product_id>')
def product_details(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template('product_detail.html', product=product)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')

        if User.query.filter_by(email=email).first():
            flash('Email already registered.')
            return redirect(url_for('signup'))

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(name=name, email=email, password=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        flash('Account created! Please login.')
        return redirect(url_for('login'))
    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            if user.is_verified:
                return redirect(url_for('shop'))
            return redirect(url_for('verify'))
        else:
            flash('Login Failed. Please check email and password.')
    return render_template('login.html')


@app.route('/verify', methods=['GET', 'POST'])
@login_required
def verify():
    if current_user.is_verified:
        return redirect(url_for('shop'))

    if request.method == 'POST':
        if 'aadhaar_image' not in request.files or 'permit_image' not in request.files or 'bill_image' not in request.files:
            flash('All three documents are required.')
            return redirect(request.url)

        aadhaar_file = request.files['aadhaar_image']
        permit_file = request.files['permit_image']
        bill_file = request.files['bill_image']

        if not aadhaar_file or not permit_file or not bill_file:
            flash('Please select files for all three documents.')
            return redirect(request.url)

        aadhaar_path = os.path.join(
            app.config['UPLOAD_FOLDER'], f"aadhaar_{current_user.id}.jpg")
        permit_path = os.path.join(
            app.config['UPLOAD_FOLDER'], f"permit_{current_user.id}.jpg")
        bill_path = os.path.join(
            app.config['UPLOAD_FOLDER'], f"bill_{current_user.id}.jpg")

        aadhaar_file.save(aadhaar_path)
        permit_file.save(permit_path)
        bill_file.save(bill_path)

        age = get_age_from_aadhaar(aadhaar_path)
        is_permit_valid = verify_gujarat_permit(permit_path)
        is_bill_valid = verify_electricity_bill(bill_path)

        errors = []
        if not (age and age >= 21):
            errors.append("Aadhaar failed: You must be 21+.")
        if not is_permit_valid:
            errors.append("Permit failed: Invalid Gujarat Permit.")
        if not is_bill_valid:
            errors.append("Address failed: Unclear Electricity Bill.")

        if not errors:
            current_user.age = age
            current_user.permit_verified = True
            current_user.address_verified = True
            current_user.is_verified = True
            db.session.commit()
            flash('Strict Gujarat Verification Successful! Welcome to the store.')
            return redirect(url_for('shop'))
        else:
            for error in errors:
                flash(error)
            return redirect(url_for('verify'))
    return render_template('verify.html')


@app.route('/add_to_cart/<int:product_id>')
@login_required
def add_to_cart(product_id):
    if not current_user.is_verified:
        flash('You must verify your Age, Permit, and Address before purchasing liquor.')
        return redirect(url_for('verify'))

    existing_item = CartItem.query.filter_by(
        user_id=current_user.id, product_id=product_id).first()
    if existing_item:
        existing_item.quantity += 1
    else:
        new_item = CartItem(user_id=current_user.id, product_id=product_id)
        db.session.add(new_item)

    db.session.commit()
    flash('Item added to your cart!')
    return redirect(url_for('shop'))


@app.route('/cart')
@login_required
def cart():
    if not current_user.is_verified:
        flash('You must verify your documents to view the cart.')
        return redirect(url_for('verify'))

    items = CartItem.query.filter_by(user_id=current_user.id).all()
    total_price = sum(item.product.price * item.quantity for item in items)
    return render_template('cart.html', items=items, total_price=total_price)


@app.route('/remove_from_cart/<int:item_id>')
@login_required
def remove_from_cart(item_id):
    item_to_remove = CartItem.query.get(item_id)
    if item_to_remove and item_to_remove.user_id == current_user.id:
        db.session.delete(item_to_remove)
        db.session.commit()
        flash('Item removed from your cart.')
    return redirect(url_for('cart'))


@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    # 1. Grab items from the cart
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    if not cart_items:
        flash('Your cart is empty.')
        return redirect(url_for('shop'))

    total_price = sum(item.product.price *
                      item.quantity for item in cart_items)
    cart_token = build_cart_token(cart_items, total_price)

    # Prevent stale OTP/card session from older cart states
    if session.get('card_payment_cart_token') and session.get('card_payment_cart_token') != cart_token:
        clear_card_payment_session()

    otp_sent = bool(session.get('card_payment_otp'))
    masked_phone = session.get('card_payment_phone_masked')

    if request.method == 'POST':
        payment_method = request.form.get('payment_method')
        action = request.form.get('action', 'confirm_order')

        if payment_method == 'Credit/Debit Card':
            card_number = request.form.get('card_number', '')
            expiry = request.form.get('expiry', '')
            cvv = request.form.get('cvv', '')
            card_phone = request.form.get('card_phone', '')
            otp = request.form.get('otp', '')

            if action == 'send_otp':
                if not is_valid_card_number(card_number):
                    flash('Invalid card number. Please enter a valid debit/credit card number.')
                    return render_checkout(
                        total_price,
                        otp_sent=False,
                        masked_phone=None,
                        form_data={'card_number': card_number, 'expiry': expiry, 'cvv': cvv, 'card_phone': card_phone},
                        selected_payment='Credit/Debit Card'
                    )

                if not is_valid_expiry(expiry):
                    flash('Invalid expiry date. Use MM/YY and make sure the card is not expired.')
                    return render_checkout(
                        total_price,
                        otp_sent=False,
                        masked_phone=None,
                        form_data={'card_number': card_number, 'expiry': expiry, 'cvv': cvv, 'card_phone': card_phone},
                        selected_payment='Credit/Debit Card'
                    )

                if not is_valid_cvv(cvv):
                    flash('Invalid CVV. Enter a 3 or 4 digit CVV.')
                    return render_checkout(
                        total_price,
                        otp_sent=False,
                        masked_phone=None,
                        form_data={'card_number': card_number, 'expiry': expiry, 'cvv': cvv, 'card_phone': card_phone},
                        selected_payment='Credit/Debit Card'
                    )

                if not is_valid_mobile_number(card_phone):
                    flash('Invalid registered mobile number. Enter a valid 10-digit Indian mobile number.')
                    return render_checkout(
                        total_price,
                        otp_sent=False,
                        masked_phone=None,
                        form_data={'card_number': card_number, 'expiry': expiry, 'cvv': cvv, 'card_phone': card_phone},
                        selected_payment='Credit/Debit Card'
                    )

                digits = sanitize_digits(card_phone)
                generated_otp = f"{random.randint(100000, 999999)}"
                session['card_payment_otp'] = generated_otp
                session['card_payment_phone'] = digits
                session['card_payment_phone_masked'] = f"{digits[:2]}******{digits[-2:]}"
                session['card_payment_cart_token'] = cart_token

                # Demo-mode OTP delivery message
                flash(f'OTP sent to your registered card mobile number: {session["card_payment_phone_masked"]}. Demo OTP: {generated_otp}')
                return render_checkout(
                    total_price,
                    otp_sent=True,
                    masked_phone=session['card_payment_phone_masked'],
                    form_data={'card_number': card_number, 'expiry': expiry, 'cvv': cvv, 'card_phone': card_phone},
                    selected_payment='Credit/Debit Card'
                )

            if action == 'confirm_card_payment':
                if not session.get('card_payment_otp'):
                    flash('Please generate OTP first.')
                    return render_checkout(
                        total_price,
                        otp_sent=False,
                        masked_phone=None,
                        form_data={'card_number': card_number, 'expiry': expiry, 'cvv': cvv, 'card_phone': card_phone},
                        selected_payment='Credit/Debit Card'
                    )

                if sanitize_digits(otp) != session.get('card_payment_otp'):
                    flash('Invalid OTP. Please enter the correct OTP.')
                    return render_checkout(
                        total_price,
                        otp_sent=True,
                        masked_phone=session.get('card_payment_phone_masked'),
                        form_data={'card_number': card_number, 'expiry': expiry, 'cvv': cvv, 'card_phone': card_phone, 'otp': otp},
                        selected_payment='Credit/Debit Card'
                    )

                new_order = place_order_and_generate_invoice(
                    cart_items, total_price, payment_method)
                clear_card_payment_session()
                return redirect(url_for('order_success', order_id=new_order.id))

            flash('Invalid card payment action.')
            return render_checkout(
                total_price,
                otp_sent=otp_sent,
                masked_phone=masked_phone,
                form_data={'card_number': card_number, 'expiry': expiry, 'cvv': cvv, 'card_phone': card_phone, 'otp': otp},
                selected_payment='Credit/Debit Card'
            )

        clear_card_payment_session()
        new_order = place_order_and_generate_invoice(
            cart_items, total_price, payment_method or 'Cash on Delivery')
        return redirect(url_for('order_success', order_id=new_order.id))

    return render_checkout(total_price, otp_sent=otp_sent, masked_phone=masked_phone)


@app.route('/order_success/<int:order_id>')
@login_required
def order_success(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        return redirect(url_for('shop'))
    return render_template('order_success.html', order=order)


# 1. THE MAIN ADMIN DASHBOARD
@app.route('/admin/orders')
@login_required
@admin_required
def admin_orders():
    # Fetch all orders from newest to oldest
    all_orders = Order.query.order_by(Order.date_ordered.desc()).all()

    # Calculate business metrics for the dashboard
    total_revenue = sum(order.total_amount for order in all_orders)
    total_orders_count = len(all_orders)

    return render_template('admin_orders.html',
                           orders=all_orders,
                           revenue=total_revenue,
                           total_orders=total_orders_count)

# 2. THE STATUS UPDATE ENGINE


@app.route('/admin/update_order/<int:order_id>', methods=['POST'])
@login_required
def update_order_status(order_id):
    # Find the specific order
    order = Order.query.get_or_404(order_id)

    # Get the new status from the dropdown menu in the HTML
    new_status = request.form.get('status')

    # Update the database
    order.status = new_status
    db.session.commit()

    flash(f'Order ORD-00{order.id} has been updated to: {new_status}')
    return redirect(url_for('admin_orders'))

# 3. ADMIN: ADD NEW PRODUCT


@app.route('/admin/add_product', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_product():
    if request.method == 'POST':
        # 1. Get text data from the form
        name = request.form.get('name')
        price = request.form.get('price')
        category = request.form.get('category')
        quantity = request.form.get('quantity')
        alcohol_percentage = request.form.get('alcohol_percentage')
        image = request.files.get('image_file')

        # 2. Handle the Image Upload automatically
        if image and image.filename != '':
            filename = image.filename
            # Create the dynamic folder path (e.g., static/images/rum)
            category_folder = os.path.join(
                app.root_path, 'static', 'images', category.lower())

            # If the folder doesn't exist, create it safely
            if not os.path.exists(category_folder):
                os.makedirs(category_folder)

            # Save the image file into that specific folder
            image_path = os.path.join(category_folder, filename)
            image.save(image_path)
        else:
            filename = 'default.jpg'  # Fallback if admin forgets an image

        # 3. Save to the Database
        new_product = Product(
            name=name,
            price=float(price),
            category=category,
            image_file=filename,
            quantity=int(quantity),
            alcohol_percentage=float(alcohol_percentage)
        )
        db.session.add(new_product)
        db.session.commit()

        flash(f'Success: {name} has been added to the {category} catalog!')
        return redirect(url_for('admin_add_product'))

    return render_template('admin_add_product.html')


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('shop'))


def ensure_product_columns():
    inspector = inspect(db.engine)
    columns = {column['name'] for column in inspector.get_columns('product')}

    if 'quantity' not in columns:
        db.session.execute(
            text("ALTER TABLE product ADD COLUMN quantity INTEGER NOT NULL DEFAULT 0")
        )
    if 'alcohol_percentage' not in columns:
        db.session.execute(
            text(
                "ALTER TABLE product ADD COLUMN alcohol_percentage FLOAT NOT NULL DEFAULT 0.0"
            )
        )
    db.session.commit()


# THIS MUST ALWAYS BE AT THE VERY BOTTOM!
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_product_columns()
    app.run(debug=True)
