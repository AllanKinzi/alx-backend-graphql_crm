import os
import django
from datetime import datetime

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "graphql_crm.settings")
django.setup()

from crm.models import Customer, Product, Order

def seed():
    # Clear old data
    Customer.objects.all().delete()
    Product.objects.all().delete()
    Order.objects.all().delete()

    # Create sample customers
    alice = Customer.objects.create(name="Alice", email="alice@example.com", phone="+1234567890")
    bob = Customer.objects.create(name="Bob", email="bob@example.com", phone="123-456-7890")

    # Create sample products
    laptop = Product.objects.create(name="Laptop", price=999.99, stock=10)
    phone = Product.objects.create(name="Phone", price=499.99, stock=25)
    tablet = Product.objects.create(name="Tablet", price=299.99, stock=15)

    # Create an order for Alice
    order1 = Order.objects.create(
        customer=alice,
        order_date=datetime.now(),
        total_amount=laptop.price + phone.price
    )
    order1.products.set([laptop, phone])

    # Create an order for Bob
    order2 = Order.objects.create(
        customer=bob,
        order_date=datetime.now(),
        total_amount=tablet.price
    )
    order2.products.set([tablet])

    print("✅ Database seeded successfully!")

if __name__ == "__main__":
    seed()
