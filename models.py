from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    # Verification Status
    # Turns True only when all 3 pass
    is_verified = db.Column(db.Boolean, default=False)
    age = db.Column(db.Integer)
    permit_verified = db.Column(db.Boolean, default=False)
    address_verified = db.Column(db.Boolean, default=False)


# NEW: The Master Admin Key
    is_admin = db.Column(db.Boolean, default=False)


cart_items = db.relationship('CartItem', backref='buyer', lazy=True)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50))
    image_file = db.Column(db.String(100), default='default.jpg')
    quantity = db.Column(db.Integer, nullable=False, default=0)
    alcohol_percentage = db.Column(db.Float, nullable=False, default=0.0)


class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey(
        'product.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    product = db.relationship('Product')


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), default='Processing')
    date_ordered = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship('OrderItem', backref='order', lazy=True)
    # ADD THIS LINE RIGHT HERE:
    buyer = db.relationship('User', backref='orders', lazy=True)

# NEW: The Items Inside the Order


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey(
        'product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price_at_purchase = db.Column(db.Float, nullable=False)

    # Easy access to the product name/image later
    product = db.relationship('Product')
